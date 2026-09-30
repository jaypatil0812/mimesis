"""Offline acceptance checks: pagination, restart recovery, scoped discovery and fencing."""
import asyncio
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4
import httpx
import pytest
from memesis.domain.schemas import Source, SourcePolicy, NodeType, GraphEdge, EdgeType
from memesis.ingestion.contracts import CollectedDocument, CollectionBatch
from memesis.ingestion.http import HttpResult
from memesis.ingestion.service import IngestionService
from memesis.ingestion.normalizer import sha256_text
from memesis.investigations.contracts import InvestigationConfig, PatternCandidate
from memesis.investigations.store import InvestigationStore
from memesis.investigations.worker import InvestigationWorker
from memesis.investigations.service import InvestigationService, PatternModel, validate_candidates
from memesis.reasoning.contracts import IntelligencePacket
from memesis.reasoning.classifier import QueryIntent, IntentType
from memesis.sources.hackernews import HackerNewsAdapter
from memesis.sources.bluesky import BlueskyAdapter
from memesis.sources.rss import RssAdapter
from memesis.extraction.pipeline import EvidenceGraphPipeline

class Pages:
    source = Source(source_key="fixture:paged", source_type="fixture", base_url="https://test.invalid")
    def __init__(self, fail=False):
        self.calls, self.fail = [], fail
    def source_policy(self, key):
        return SourcePolicy(source_id=key, terms_url="https://test.invalid", reviewed_at=datetime.now(UTC), active=True, policy={})
    async def collect(self, query, *, cursor, limit):
        self.calls.append(cursor)
        if self.fail:
            return CollectionBatch([], None, failures=[{"error": "simulated_failure"}], complete=False)
        key = "two" if cursor == "page:2" else "one"
        doc = CollectedDocument(key, f"https://test.invalid/{key}", f"https://test.invalid/{key}", "fixture",
            "Raw " + key, "A distinct durable document " + key, key, datetime.now(UTC))
        return CollectionBatch([doc], "watermark:complete", complete=key == "two", continuation_cursor="page:2")

def config(**kwargs):
    return InvestigationConfig(name="Test watch", question="Investigate possible connections", scope={},
        sources=[{"source": "hackernews", "query": "research boundary"}], max_investigation_rounds=0, **kwargs)

def test_completed_checkpoint_waits_for_all_pages_and_pending_survives_restart(repository):
    service, pages = IngestionService(repository), Pages()
    first = asyncio.run(service.collect(pages, "topic", limit=1, max_pages=1))
    source = repository.add_source(pages.source)
    key = "query:" + sha256_text("topic")
    assert repository.get_collection_cursor(source.id, key) is None
    assert repository.get_collection_cursor(source.id, key + ":pending") == "page:2"
    assert not first.checkpoint_advanced and not first.pagination_complete
    second = asyncio.run(IngestionService(repository).collect(pages, "topic", limit=1))
    assert pages.calls == [None, "page:2"]
    assert second.checkpoint_advanced and repository.get_collection_cursor(source.id, key) == "watermark:complete"
    assert repository.get_collection_cursor(source.id, key + ":pending") is None
    assert repository.storage_metrics()["evidence"] == 2

def test_partial_or_failed_page_never_commits_high_water_mark(repository):
    report = asyncio.run(IngestionService(repository).collect(Pages(fail=True), "topic", max_pages=3))
    assert report.failures and not report.checkpoint_advanced

class PageHttp:
    def __init__(self, payloads):
        self.payloads, self.calls = payloads, []
    async def get(self, url, *, params=None, **kwargs):
        self.calls.append(params)
        payload = self.payloads[len(self.calls) - 1]
        return HttpResult(payload if isinstance(payload, str) else json.dumps(payload), 200, {}, False, 1)

def test_hn_uses_frozen_scan_boundary_across_pages():
    http = PageHttp([{"hits": [{"objectID": "1", "title": "Newest", "created_at_i": 120}], "nbPages": 2, "nbHits": 2},
                     {"hits": [{"objectID": "2", "title": "Older", "created_at_i": 100}], "nbPages": 2, "nbHits": 2}])
    adapter = HackerNewsAdapter(http)
    first = asyncio.run(adapter.collect("topic", cursor="99", limit=1))
    second = asyncio.run(adapter.collect("topic", cursor=first.continuation_cursor, limit=1))
    assert not first.complete and second.complete and second.next_cursor == "120"
    assert http.calls[0]["numericFilters"] == http.calls[1]["numericFilters"]
    assert http.calls[1]["page"] == 1

def test_bluesky_provider_cap_is_visible_not_exhaustive_success():
    http = PageHttp([{"posts": [], "hitsTotal": 100}])
    result = asyncio.run(BlueskyAdapter(http).collect("topic", cursor=None, limit=2))
    assert result.failures and "provider_result_cap" in result.failures[0]["error"]

def test_rss_paginates_frozen_feed_without_skip_or_keyword_feed_bug():
    body = '<rss version="2.0"><channel><title>Feed</title>' + ''.join(
        f'<item><title>Entry {i}</title><description>Different content {i}</description><link>https://test.invalid/{i}</link><guid>{i}</guid></item>' for i in range(5)) + '</channel></rss>'
    http = PageHttp([body])
    adapter = RssAdapter(http, "https://test.invalid/feed")
    a = asyncio.run(adapter.collect("feed:any", cursor=None, limit=2))
    b = asyncio.run(adapter.collect("feed:any", cursor=a.continuation_cursor, limit=2))
    c = asyncio.run(adapter.collect("feed:any", cursor=b.continuation_cursor, limit=2))
    assert len(http.calls) == 1 and c.complete
    assert {d.external_id for batch in (a, b, c) for d in batch.documents} == {str(i) for i in range(5)}

def test_worker_lease_fences_expired_owner_and_prevents_parallel_jobs(repository):
    store = InvestigationStore(repository.session_factory)
    now = datetime.now(UTC)
    assert store.acquire("first", now=now, seconds=1)
    assert not store.acquire("second", now=now)
    assert store.acquire("second", now=now + timedelta(seconds=2))
    with pytest.raises(RuntimeError):
        with repository.session_factory.begin() as session:
            store.fenced(session, "first")
    assert not store.renew("first")

def test_worker_recovers_committed_collection_receipts_after_restart(repository):
    store = InvestigationStore(repository.session_factory)
    watch = store.create(config(enabled=True))
    # Collection completed, but the worker crashed before its extraction queue
    # was saved. Receipts must recover both evidence IDs on restart.
    asyncio.run(IngestionService(repository).collect(Pages(), "research boundary", max_pages=2,
        namespace=f"watch:{watch['id']}:"))
    worker = InvestigationWorker(repository, store, adapter_factory=lambda source: Pages())
    asyncio.run(worker.tick())
    saved = store.get(watch["id"])
    assert len(saved["state"]["tracked_evidence_ids"]) == 2
    assert saved["state"]["pending_evidence_ids"] == []
    assert len(store.history(watch["id"])) == 1
    store.request_run(watch["id"])
    asyncio.run(worker.tick())
    assert len(store.history(watch["id"])) == 1
    assert store.runs(watch["id"])[0]["receipt"]["analysis"].startswith("unchanged")

def test_interpretation_version_permits_reprocessing_preserving_raw_evidence(repository):
    report = asyncio.run(IngestionService(repository).collect(Pages(), "topic", max_pages=2))
    ids = [UUID(eid) for eid in report.evidence_ids]
    first = asyncio.run(EvidenceGraphPipeline(repository, interpretation_version="v1").run(evidence_ids=ids))
    repeated = asyncio.run(EvidenceGraphPipeline(repository, interpretation_version="v1").run(evidence_ids=ids))
    rebuilt = asyncio.run(EvidenceGraphPipeline(repository, interpretation_version="v2").run(evidence_ids=ids))
    assert first.evidence_processed == rebuilt.evidence_processed == 2
    assert repeated.evidence_processed == 0
    assert repository.storage_metrics()["evidence"] == 2

def synthetic_packet():
    return IntelligencePacket(question="Investigate", query_intent=QueryIntent(raw_query="Investigate", intents=[IntentType.GENERAL_RESEARCH]),
        memory_observations=[{"id": "o1", "subject_id": "company", "observation_type": "company_statement", "review_state": "proposed", "evidence_ids": ["e1"]},
                             {"id": "o2", "subject_id": "product", "observation_type": "customer_experience", "review_state": "proposed", "evidence_ids": ["e2"]}],
        graph_relationships=[{"id": "edge1", "from_id": "company", "to_id": "product", "from": "Unfamiliar maker", "to": "Unusual controller", "type": "BUILDS", "evidence_ids": ["e1"], "valid_from": "2026-09-01", "recorded_at": "2026-09-01"}],
        primary_evidence_references=[{"id": "e1", "text": "Company statement", "source_family": {"id": "one"}}, {"id": "e2", "text": "Customer experience", "source_family": {"id": "two"}}],
        estimated_tokens=10, packet_hash="a" * 64)

def test_discovery_preserves_unusual_typed_paths_without_keyword_match(repository):
    service, packet = InvestigationService(repository), synthetic_packet()
    result = service.investigate(config(), packet)
    pattern = result["patterns"][0]
    assert pattern["connecting_paths"] == [["edge1"]]
    assert pattern["supporting_observation_ids"] == ["o1", "o2"]
    assert pattern["epistemic_status"] == "SPECULATIVE" and pattern["review_state"] == "proposed"
    assert pattern["alternative_explanations"] and pattern["missing_information"]
    assert pattern["independence_status"] == "not_established_by_source_family_count"

def test_pattern_model_rejects_invalid_observation_and_path(repository):
    p = synthetic_packet()
    body = {"patterns": [{"category": "invented", "explanation": "Possible connection", "supporting_observation_ids": ["missing"],
        "connecting_paths": [["made-up-edge"]], "alternative_explanations": ["Other cause"], "missing_information": ["Unverified"]}]}
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(body)}}]}))
    cfg = SimpleNamespace(model_api_key="simulated", reason_strong_model="simulated", reasoning_max_packet_tokens=5000,
        reasoning_timeout_seconds=1, model_api_base_url="https://test.invalid")
    model = PatternModel(cfg, transport)
    assert model.propose(p, p.memory_observations, [], config()) == []
    assert model.execution["status"] == "invalid_response"

def test_empty_scoped_investigation_has_gaps_not_invented_patterns(repository):
    result = InvestigationService(repository).investigate(config())
    assert not result["patterns"] and not result["evidence_ids"]
    assert result["missing_information"]


def test_successful_empty_model_result_does_not_restore_structural_story(repository):
    received = []
    def respond(request):
        received.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"patterns": []}'}}]})
    cfg = SimpleNamespace(model_api_key="simulated", reason_strong_model="simulated", reasoning_max_packet_tokens=5000,
        reasoning_timeout_seconds=1, model_api_base_url="https://test.invalid")
    model = PatternModel(cfg, httpx.MockTransport(respond))
    packet = synthetic_packet()
    previous = {"patterns": [{"id": "old", "evidence_ids": ["out-of-scope"], "explanation": "Excluded prior premise"}]}
    result = InvestigationService(repository, model).investigate(config(), packet, previous)
    assert result["reasoning_execution"]["status"] == "completed"
    assert result["patterns"] == []
    assert json.loads(received[0]["messages"][1]["content"])["previous_scoped_hypotheses"] == []

def test_watch_revision_conflict_and_rebuild_queue(repository):
    store = InvestigationStore(repository.session_factory)
    record = store.create(config())
    changed = store.configure(record["id"], config(processing_version="v2"), record["revision"])
    assert changed["state"]["projection_review_required"]
    with pytest.raises(ValueError):
        store.configure(record["id"], config(), record["revision"])

def test_followup_rounds_do_not_reset_when_followup_changes_evidence(repository):
    class EmptyPrimary(Pages):
        async def collect(self, query, *, cursor, limit):
            if not query.startswith("gap-"):
                return CollectionBatch([], None)
            key = query
            doc = CollectedDocument(key, f"https://test.invalid/{key}", f"https://test.invalid/{key}", "fixture",
                key, "A followup observation " + key, key, datetime.now(UTC))
            return CollectionBatch([doc], "complete")
    class ChangingInvestigation:
        def __init__(self):
            self.count = 0
        def context(self, config, seeds=None):
            self.count += 1
            return synthetic_packet()
        def fingerprint(self, packet, config):
            return str(self.count)
        def investigate(self, config, packet, previous=None):
            return {"fingerprint": str(self.count), "evidence_ids": [], "reasoning_execution": {"status": "not_configured"},
                "patterns": [{"id": "candidate-" + str(self.count), "next_investigation": {
                    "source": "hackernews", "query": "gap-" + str(self.count), "question": "Find counterevidence"}}]}
    store = InvestigationStore(repository.session_factory)
    cfg = config(enabled=True).model_copy(update={"max_investigation_rounds": 2})
    watch = store.create(cfg)
    worker = InvestigationWorker(repository, store, adapter_factory=lambda source: EmptyPrimary(), service=ChangingInvestigation())
    total = 0
    for _ in range(4):
        store.request_run(watch["id"])
        result = asyncio.run(worker.tick())
        total += len(result["jobs"][0]["followup_collection"])
    assert total == 2
    assert store.get(watch["id"])["state"]["rounds_remaining"] == 0

def test_evidence_seed_scope_is_hop_bounded_and_never_overrides_market(repository):
    from memesis.knowledge.service import KnowledgeService
    from memesis.retrieval.scope import ScopedGraphRepository, QueryScope
    nodes, evidence_ids = [], []
    for i in range(6):
        pages = Pages()
        pages.source = Source(source_key=f"fixture:seed:{i}", source_type="fixture", base_url="https://test.invalid")
        async def collect(query, *, cursor, limit, index=i):
            key = f"seed-{index}"
            return CollectionBatch([CollectedDocument(key, f"https://test.invalid/{key}", f"https://test.invalid/{key}", "fixture",
                key, "A distinct sector definition " + key, key, datetime.now(UTC))], None)
        pages.collect = collect
        report = asyncio.run(IngestionService(repository).collect(pages, "seed"))
        eid = UUID(report.evidence_ids[0])
        evidence_ids.append(eid)
        nodes.append(KnowledgeService(repository).create_node(NodeType.MARKET, f"Unusual sector {i}", eid))
    for i in range(4):
        provenance = nodes[i + 1].provenance.model_copy(update={"entity_ids": (nodes[i].id, nodes[i + 1].id)})
        repository.add_edge(GraphEdge(edge_type=EdgeType.ADJACENT_TO, from_node_id=nodes[i].id, to_node_id=nodes[i + 1].id,
            provenance=provenance, valid_from=datetime.now(UTC), recorded_at=datetime.now(UTC)))
    view = ScopedGraphRepository(repository, QueryScope(evidence_seeds=(evidence_ids[0],), graph_hops=2))
    assert {n.id for n in view.list_nodes()} == {n.id for n in nodes[:3]}
    assert {e.id for e in view.list_evidence()} == set(evidence_ids[:3])
    empty = ScopedGraphRepository(repository, QueryScope(market_id=nodes[5].id, evidence_seeds=(evidence_ids[0],)))
    assert not empty.list_evidence() and not empty.list_nodes()

def test_api_enqueues_work_without_collecting_and_reviews_do_not_promote_graph(repository, monkeypatch):
    from memesis.app import create_app
    monkeypatch.setattr(IngestionService, "collect", lambda *args, **kwargs: pytest.fail("API must not collect"))
    app = create_app("sqlite://")
    app.state.repository = repository
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            created = await client.post("/api/investigations", json=config().model_dump(mode="json"))
            assert created.status_code == 201
            watch = created.json()
            queued = await client.post(f"/api/investigations/{watch['id']}/run")
            assert queued.status_code == 202 and queued.json()["collection_started_by_api"] is False
            return watch
    watch = asyncio.run(scenario())
    store = InvestigationStore(repository.session_factory)
    assert store.acquire("review-test")
    claimed = store.claim("review-test", watch["id"])
    pattern = InvestigationService(repository).investigate(config(), synthetic_packet())
    store.complete("review-test", claimed, {}, {"status": "completed"}, pattern, 60)
    count = len(repository.list_edges())
    store.review(watch["id"], pattern["patterns"][0]["id"], "reviewed", "analyst", "Useful hypothesis; premises still need verification")
    assert len(repository.list_edges()) == count
    assert store.reviews(watch["id"])[0]["state"] == "reviewed"

def test_inactive_source_policy_is_not_silently_replaced(repository):
    pages = Pages()
    source = repository.add_source(pages.source)
    repository.add_source_policy(SourcePolicy(source_id=source.id, terms_url="https://test.invalid", reviewed_at=datetime.now(UTC), active=False, policy={}))
    with pytest.raises(PermissionError):
        asyncio.run(IngestionService(repository).collect(pages, "topic"))
    assert not pages.calls
