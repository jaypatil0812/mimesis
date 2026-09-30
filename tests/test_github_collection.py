import asyncio
import json
import pytest
from datetime import UTC, datetime
from hashlib import sha256
from uuid import uuid4
from types import SimpleNamespace
from memesis.extraction.pipeline import EvidenceGraphPipeline
from memesis.extraction.resolution import _belief_signature
from memesis.domain.schemas import Evidence
from memesis.extraction.deterministic import DeterministicExtractor
from memesis.ingestion.http import HttpResult
from memesis.sources.github import GitHubAdapter


class Pages:
    def __init__(self, capped=False):
        self.calls = []
        self.capped = capped

    async def get(self, url, **kwargs):
        self.calls.append(kwargs)
        page = kwargs["params"]["page"]
        item = {"id": page, "html_url": f"https://github.com/example/tool/issues/{page}",
            "title": "Latency depends on workload", "body": "Not slow for every workload",
            "created_at": "2026-09-01T00:00:00Z", "updated_at": "2026-09-02T00:00:00Z",
            "user": {"login": "someone", "id": 123, "html_url": "https://github.com/someone"}}
        return HttpResult(json.dumps({"items": [item], "total_count": 1001 if self.capped else 2,
            "incomplete_results": self.capped}), 200, {}, False, 1)


def test_github_preserves_identity_dates_and_frozen_pagination():
    async def run():
        http = Pages()
        adapter = GitHubAdapter(http)
        first = await adapter.collect("repo:example/tool is:issue latency", cursor="2026-09-01T00:00:00Z", limit=1)
        second = await adapter.collect("repo:example/tool is:issue latency", cursor=first.continuation_cursor, limit=1)
        assert not first.complete and second.complete
        assert first.next_cursor == second.next_cursor
        assert http.calls[0]["params"]["q"] == http.calls[1]["params"]["q"]
        assert first.documents[0].metadata["author_github_id"] == 123
        assert first.documents[0].published_at < first.documents[0].updated_at
        assert not first.documents[0].metadata["comments_collected"]
    asyncio.run(run())


def test_github_caps_are_visible_and_repo_boundary_is_required():
    async def run():
        adapter = GitHubAdapter(Pages(capped=True))
        result = await adapter.collect("repo:example/tool latency", cursor=None, limit=100)
        assert result.failures and not result.complete
        with pytest.raises(ValueError):
            await adapter.collect("latency", cursor=None, limit=100)
    asyncio.run(run())


def test_github_author_uses_numeric_identity_across_handle_changes():
    text = "Latency depends on workload."
    evidence = Evidence(source_id=uuid4(), source_url="https://github.com/example/tool/issues/1", source_type="github",
        retrieved_at=datetime.now(UTC), original_reference=text, raw_text=text, normalized_text=text,
        content_hash=sha256(text.encode()).hexdigest(), metadata={"author_handle": "old-name", "author_github_id": 123})
    first = DeterministicExtractor().extract_metadata(evidence)
    second = DeterministicExtractor().extract_metadata(evidence.model_copy(update={
        "metadata": {"author_handle": "new-name", "author_github_id": 123}}))
    first_author = next(e for e in first.entities if e.key == "metadata_author")
    second_author = next(e for e in second.entities if e.key == "metadata_author")
    assert first_author.external_ids == second_author.external_ids
    assert first_author.external_ids[0].identifier_type == "github_user_id"
    assert first_author.external_ids[0].value == "123"


def test_synchronous_extraction_batches_yield_for_heartbeat():
    async def run():
        records = [SimpleNamespace(id=uuid4()) for _ in range(4)]
        pipeline = EvidenceGraphPipeline(SimpleNamespace(list_evidence=lambda limit: records, list_nodes=lambda: []))
        pulses = []
        async def process(evidence, report):
            return True
        async def pulse():
            for _ in records:
                pulses.append(True)
                await asyncio.sleep(0)
        pipeline._process = process
        task = asyncio.create_task(pulse())
        report = await pipeline.run()
        assert len(pulses) == len(records)
        assert report.evidence_processed == len(records)
        await task
    asyncio.run(run())


def test_long_belief_identifiers_preserve_scope_without_truncation():
    proposal = SimpleNamespace(proposition="A long qualified claim " * 40, scope="workload A",
        modality="conditional", horizon="current")
    first = _belief_signature(proposal)
    assert len(first) <= 500 and first.startswith("memory-v1-sha256|")
    assert first == _belief_signature(proposal)
    proposal.scope = "workload B"
    assert first != _belief_signature(proposal)
