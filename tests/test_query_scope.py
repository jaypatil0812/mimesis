"""Market and date boundaries hold across graph traversal, scoring and API answers."""

import asyncio
import hashlib
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI

from memesis.config import settings
from memesis.analysis.scoring import DeterministicScoringService
from memesis.db.session import initialize_schema, make_engine, make_session_factory
from memesis.graph.sql_repository import SqlGraphRepository
from memesis.domain.schemas import (
    Belief, Company, Content, EdgeType, Evidence, ExtractionMethod,
    GraphEdge, Market, Person, Provenance, Source,
)
from memesis.reasoning.engine import MemesisReasoningEngine
from memesis.reasoning.market_motion import MarketMotionAnalyzer, MarketMotionStatus
from memesis.retrieval.context_builder import MinimumSufficientSubgraph
from memesis.retrieval.scope import QueryScope, ScopedGraphRepository
from memesis.web.api import api_router

BASE = datetime(2026, 4, 1, tzinfo=UTC)


@pytest.fixture
def repository(tmp_path):
    # File-backed SQLite lets FastAPI worker threads see the same fixture database.
    engine = make_engine(f"sqlite:///{tmp_path / 'scope.sqlite3'}")
    initialize_schema(engine)
    yield SqlGraphRepository(make_session_factory(engine))
    engine.dispose()


@pytest.fixture
def graph(repository, monkeypatch):
    monkeypatch.setattr(settings, "verify_claim_support", False)
    source = repository.add_source(Source(
        source_key="scope-fixture", source_type="reviewed_fixture",
        base_url="https://example.org/scope",
    ))

    def evidence(label, day, entities=(), retrieved_day=None):
        text = f"Source for {label}; an evidence-backed relationship."
        return repository.add_evidence(Evidence(
            source_id=source.id, source_url=f"https://example.org/scope/{label}",
            source_type=source.source_type, original_reference=label,
            raw_text=text, content_hash=hashlib.sha256(text.encode()).hexdigest(),
            published_at=BASE + timedelta(days=day),
            retrieved_at=BASE + timedelta(days=retrieved_day if retrieved_day is not None else day),
            entity_ids=tuple(entities),
        ))

    identity = evidence("identities", 0)

    def provenance(ev, entities):
        return Provenance(
            source_url=ev.source_url, source_type=ev.source_type,
            original_reference=ev.original_reference, retrieved_at=ev.retrieved_at,
            published_at=ev.published_at, evidence_ids=(ev.id,), entity_ids=tuple(entities),
            confidence=1.0, extraction_method=ExtractionMethod.DETERMINISTIC,
        )

    def node(schema, name):
        nid = uuid4()
        return repository.add_node(schema(id=nid, name=name, provenance=provenance(identity, [nid])))

    a = node(Market, "Orbital sensing")
    b = node(Market, "Dental devices")
    adjacent = node(Market, "Power storage")
    empty = node(Market, "Unlinked market")
    company = node(Company, "Lumen")
    actor = node(Person, "Ari")
    belief = node(Belief, "Acoustic events foreshadow component failures")
    content = node(Content, "Unexpected acoustic signal")
    foreign_company = node(Company, "DentalCo")
    foreign_belief = node(Belief, "Dental procurement changes")
    foreign_actor = node(Person, "Dentist")
    power_company = node(Company, "BatteryCo")
    old_company = node(Company, "EarlyCo")
    future_company = node(Company, "FutureCo")
    delayed_company = node(Company, "DelayedCo")
    lower = node(Company, "Lower boundary")
    upper = node(Company, "Upper boundary")
    wrong_event = node(Company, "Future effective relationship")
    evs = {}

    def edge(kind, left, right, label, day=15, tags=(), retrieved_day=None, effective_day=None):
        ev = evidence(label, day, tags, retrieved_day)
        evs[label] = ev
        return repository.add_edge(GraphEdge(
            edge_type=kind, from_node_id=left.id, to_node_id=right.id,
            valid_from=BASE + timedelta(days=day if effective_day is None else effective_day),
            recorded_at=ev.retrieved_at, provenance=provenance(ev, [left.id, right.id]),
        ))

    edge(EdgeType.SERVES, company, a, "selected")
    edge(EdgeType.WORKS_AT, actor, company, "bridge")
    edge(EdgeType.BELIEVES, actor, belief, "hidden_pattern")
    edge(EdgeType.PUBLISHED, actor, content, "publication")
    edge(EdgeType.EXPRESSES, content, belief, "expression")
    edge(EdgeType.SERVES, foreign_company, b, "foreign", tags=[b.id])
    edge(EdgeType.BELIEVES, foreign_actor, foreign_belief, "foreign_belief", tags=[b.id])
    edge(EdgeType.BELIEVES, actor, foreign_belief, "shared_actor_foreign", tags=[b.id])
    edge(EdgeType.ADJACENT_TO, a, adjacent, "adjacency")
    edge(EdgeType.SERVES, power_company, adjacent, "adjacent_company", tags=[adjacent.id])
    edge(EdgeType.SERVES, old_company, a, "too_early", day=9)
    edge(EdgeType.SERVES, future_company, a, "future", day=21)
    edge(EdgeType.SERVES, delayed_company, a, "delayed", retrieved_day=25)
    edge(EdgeType.SERVES, lower, a, "lower", day=10)
    edge(EdgeType.SERVES, upper, a, "upper", day=20)
    edge(EdgeType.SERVES, wrong_event, a, "future_relation", effective_day=21)
    # Direct source membership works before the source is projected into graph edges.
    evs["direct"] = evidence("direct", 14, [a.id])
    evs["unlinked_actor_post"] = evidence("unlinked_actor_post", 14, [actor.id])
    return {"repo": repository, "a": a, "b": b, "empty": empty,
            "belief": belief, "actor": actor, "evs": evs}


def scope(graph, **updates):
    return QueryScope(**{
        "market_id": graph["a"].id, "start_at": BASE + timedelta(days=10),
        "as_of": BASE + timedelta(days=20), **updates,
    })


def test_scope_keeps_novel_connected_patterns_without_importing_shared_actor_history(graph):
    view = ScopedGraphRepository(graph["repo"], scope(graph))
    names = {node.name for node in view.nodes}
    ev_ids = {ev.id for ev in view.evidence}
    assert graph["belief"].name in names  # no AI/model keywords; reached via a three-edge path
    assert "BatteryCo" in names
    assert "DentalCo" not in names
    assert "Dental procurement changes" not in names
    for label in ("foreign", "foreign_belief", "shared_actor_foreign", "unlinked_actor_post"):
        assert graph["evs"][label].id not in ev_ids
    assert graph["evs"]["direct"].id in ev_ids
    assert view.node_distances[graph["belief"].id] == 3


def test_date_bounds_exclude_old_future_and_future_effective_records(graph):
    view = ScopedGraphRepository(graph["repo"], scope(graph))
    ev_ids = {ev.id for ev in view.evidence}
    assert {graph["evs"][key].id for key in ("lower", "upper")} <= ev_ids
    assert not {graph["evs"][key].id for key in ("too_early", "future", "future_relation")} & ev_ids
    assert "FutureCo" not in {node.name for node in view.nodes}
    assert view.coverage["latest_evidence_at"] == (BASE + timedelta(days=20)).isoformat()


def test_known_at_excludes_material_collected_after_the_cutoff(graph):
    published = ScopedGraphRepository(graph["repo"], scope(graph))
    known = ScopedGraphRepository(graph["repo"], scope(graph, time_basis="known_at"))
    assert graph["evs"]["delayed"].id in {ev.id for ev in published.evidence}
    assert graph["evs"]["delayed"].id not in {ev.id for ev in known.evidence}
    assert known.scope_metadata()["knowledge_cutoff_enforced"] is True


def test_known_at_excludes_versions_updated_after_cutoff(graph, monkeypatch):
    repo = graph["repo"]
    selected_id = graph["evs"]["selected"].id
    evidence = [ev.model_copy(update={"updated_at": BASE + timedelta(days=25)})
                if ev.id == selected_id else ev for ev in repo.list_evidence()]
    monkeypatch.setattr(repo, "list_evidence", lambda limit=None: evidence)
    known = ScopedGraphRepository(repo, scope(graph, time_basis="known_at"))
    assert selected_id not in {ev.id for ev in known.evidence}


def test_adjacent_branches_and_hop_depth_are_explicit(graph):
    isolated = ScopedGraphRepository(graph["repo"], scope(graph, include_adjacent_markets=False))
    assert "Power storage" not in {node.name for node in isolated.nodes}
    shallow = ScopedGraphRepository(graph["repo"], scope(graph, graph_hops=1))
    assert "Lumen" in {node.name for node in shallow.nodes}
    assert graph["belief"].id not in {node.id for node in shallow.nodes}


@pytest.mark.parametrize("full_context", [False, True])
def test_reasoning_scope_applies_to_full_and_ranked_retrieval_and_scores(graph, full_context):
    output, _, packet = MemesisReasoningEngine(graph["repo"]).answer_query(
        "Give me every post about patterns.", scope=scope(graph), force_full_context=full_context,
    )
    expected = {str(ev.id) for ev in ScopedGraphRepository(graph["repo"], scope(graph)).evidence}
    assert {ref["id"] for ref in packet.primary_evidence_references} <= expected
    assert {ref["id"] for ref in packet.primary_evidence_references}
    assert packet.query_scope["market_id"] == str(graph["a"].id)
    assert output.query_scope == packet.query_scope
    assert output.coverage == packet.coverage
    assert all(score["subject"] != "Dental procurement changes" for score in packet.memesis_scores)
    assert all(eid in expected for actor in packet.key_actors for eid in actor["evidence_ids"])
    assert packet.coverage["retained_evidence"] <= packet.coverage["scoped_evidence"]


def test_scope_changes_packet_fingerprint_even_when_the_same_records_match(graph):
    engine = MemesisReasoningEngine(graph["repo"])
    _, _, first = engine.answer_query("Give me every post about patterns.", scope=scope(graph))
    _, _, second = engine.answer_query(
        "Give me every post about patterns.",
        scope=scope(graph, start_at=BASE + timedelta(days=9, hours=23)),
    )
    assert first.packet_hash != second.packet_hash


def test_scoped_scores_recompute_instead_of_using_future_global_cache(graph):
    repo = graph["repo"]
    DeterministicScoringService(repo).compute_all(as_of=BASE + timedelta(days=30), persist=True)
    stored_count = len(repo.list_scores())
    _, _, packet = MemesisReasoningEngine(repo).answer_query(
        "What is changing in this market and should we care?", scope=scope(graph),
    )
    assert packet.memesis_scores
    assert all(score["as_of"] == scope(graph).as_of.isoformat() for score in packet.memesis_scores)
    assert all(score["subject"] != "Dental procurement changes" for score in packet.memesis_scores)
    assert packet.coverage["scores_recomputed_from_scope"] is True
    assert packet.coverage["score_comparison_window_days"] == 5
    assert len(repo.list_scores()) == stored_count


def test_short_scopes_do_not_invent_acceleration_from_a_missing_baseline(graph):
    view = ScopedGraphRepository(graph["repo"], scope(
        graph, start_at=BASE + timedelta(days=14), as_of=BASE + timedelta(days=15),
    ))
    scores = view.compute_scores()
    assert "belief_velocity" in view.coverage["unavailable_score_types"]
    subgraph = MinimumSufficientSubgraph(
        nodes=view.nodes, edges=view.edges, evidence=view.evidence,
        nodes_considered=len(view.nodes), nodes_retained=len(view.nodes),
        evidence_considered=len(view.evidence), evidence_retained=len(view.evidence),
        query_scope=view.scope_metadata(), coverage=view.coverage,
    )
    motion = MarketMotionAnalyzer().analyze(subgraph, scores, view.scope.as_of)
    assert motion.velocity_trend == "unknown"
    assert motion.status == MarketMotionStatus.UNCERTAIN


def api_call(graph, method, path, **kwargs):
    app = FastAPI()
    app.state.repository = graph["repo"]
    app.include_router(api_router)

    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            return await client.request(method, path, **kwargs)

    return asyncio.run(run())


def test_workspace_and_ask_share_scope_and_empty_markets_never_fall_back(graph):
    options = scope(graph).model_dump(mode="json", exclude={"market_id"})
    options["include_adjacent_markets"] = "true"
    response = api_call(graph, "GET", f"/api/markets/{graph['a'].id}", params=options)
    assert response.status_code == 200
    workspace = response.json()
    catalog = api_call(graph, "GET", "/api/markets", params=options)
    assert catalog.status_code == 200
    catalog_market = next(row for row in catalog.json() if row["id"] == str(graph["a"].id))
    assert catalog_market["evidence_count"] == workspace["overview"]["evidence_count"]
    assert catalog_market["query_scope"] == workspace["query_scope"]
    assert graph["belief"].name in {row["name"] for row in workspace["beliefs"]}
    assert "DentalCo" not in {row["name"] for row in workspace["companies"]}
    node_ids = {row["id"] for row in workspace["graph"]["nodes"]}
    assert all(edge["from"] in node_ids and edge["to"] in node_ids for edge in workspace["graph"]["edges"])
    expected = {ref["id"] for ref in workspace["timeline"]}
    options["include_adjacent_markets"] = True
    answer = api_call(graph, "POST", f"/api/markets/{graph['a'].id}/ask", json={
        "question": "Give me every post about patterns.", **options,
    })
    assert answer.status_code == 200
    assert {ref["id"] for ref in answer.json()["evidence"]} <= expected
    assert answer.json()["query_scope"] == workspace["query_scope"]

    empty = api_call(graph, "GET", f"/api/markets/{graph['empty'].id}", params=options).json()
    assert empty["timeline"] == []
    assert empty["people"] == empty["beliefs"] == empty["companies"] == []
    empty_answer = api_call(graph, "POST", f"/api/markets/{graph['empty'].id}/ask", json={
        "question": "Give me every post about patterns.", **options,
    }).json()
    assert empty_answer["evidence"] == []
    assert empty_answer["coverage"]["scoped_evidence"] == 0


def test_invalid_windows_and_depths_are_rejected_in_both_api_routes(graph):
    bad_dates = {"start_at": "2026-04-22T00:00:00Z", "as_of": "2026-04-20T00:00:00Z"}
    assert api_call(graph, "GET", f"/api/markets/{graph['a'].id}", params=bad_dates).status_code == 422
    assert api_call(graph, "POST", f"/api/markets/{graph['a'].id}/ask", json={
        "question": "What changed?", **bad_dates,
    }).status_code == 422
    assert api_call(graph, "GET", f"/api/markets/{graph['a'].id}", params={"graph_hops": 7}).status_code == 422
    assert api_call(graph, "GET", f"/api/markets/{uuid4()}").status_code == 404


def test_naive_and_offset_timestamps_normalize_to_utc(graph):
    window = scope(graph, start_at="2026-04-11T05:30:00+05:30", as_of="2026-04-21T00:00:00")
    assert window.start_at == BASE + timedelta(days=10)
    assert window.as_of == BASE + timedelta(days=20)
