"""Offline acceptance coverage for the deterministic Phase 2 boundary."""

import asyncio
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

from memesis.domain.schemas import Source, SourcePolicy
from memesis.ingestion.contracts import CollectedDocument, CollectionBatch
from memesis.ingestion.http import HttpResult
from memesis.ingestion.service import IngestionService
from memesis.sources.bluesky import BlueskyAdapter, JetstreamEventNormalizer
from memesis.sources.hackernews import HackerNewsAdapter
from memesis.sources.openalex import RESOURCE_TYPES, OpenAlexAdapter


class FakeHttp:
    def __init__(self, payloads: dict[str, object]) -> None:
        self.payloads = payloads
        self.calls: list[tuple[str, dict[str, object] | None]] = []

    async def get(self, url: str, *, params=None, **_kwargs) -> HttpResult:
        self.calls.append((url, params))
        return HttpResult(json.dumps(self.payloads[url]), 200, {}, False, 1)


def test_hackernews_checkpoint_is_forward_high_water_mark():
    http = FakeHttp(
        {
            "https://hn.algolia.com/api/v1/search_by_date": {
                "hits": [
                    {"objectID": "1", "title": "AI infrastructure", "created_at_i": 100},
                    {"objectID": "2", "title": "small model", "created_at_i": 120},
                ]
            }
        }
    )
    batch = asyncio.run(HackerNewsAdapter(http).collect("AI infrastructure", cursor="99", limit=3))
    assert batch.next_cursor == "120"
    assert http.calls[0][1]["numericFilters"].startswith("created_at_i>=99,created_at_i<")


def test_bluesky_and_jetstream_normalize_to_common_document_envelope():
    post = {
        "uri": "at://did:plc:test/app.bsky.feed.post/abc",
        "indexedAt": "2026-09-29T01:00:00Z",
        "author": {"handle": "test.bsky.social", "did": "did:plc:test"},
        "record": {"text": "AI infrastructure", "createdAt": "2026-09-29T00:00:00Z"},
    }
    http = FakeHttp({"https://api.bsky.app/xrpc/app.bsky.feed.searchPosts": {"posts": [post]}})
    batch = asyncio.run(
        BlueskyAdapter(http).collect(
            "AI infrastructure", cursor="2026-09-28T00:00:00+00:00", limit=2
        )
    )
    jetstream = JetstreamEventNormalizer.normalize(
        {
            "did": "did:plc:test",
            "time_us": 1,
            "commit": {"operation": "create", "rkey": "abc", "record": post["record"]},
        }
    )
    assert batch.documents[0].__class__ is CollectedDocument
    assert jetstream is not None and jetstream.__class__ is CollectedDocument
    assert http.calls[0][1]["since"] == "2026-09-28T00:00:00+00:00"
    assert batch.next_cursor == http.calls[0][1]["until"]


def test_openalex_searches_all_required_resources_with_limited_fields():
    result = {
        "results": [
            {
                "id": "https://openalex.org/W1",
                "display_name": "AI infrastructure",
                "updated_date": "2026-09-29",
                "ids": {"openalex": "https://openalex.org/W1"},
            }
        ]
    }
    http = FakeHttp({f"https://api.openalex.org/{resource}": result for resource in RESOURCE_TYPES})
    adapter = OpenAlexAdapter(http, SimpleNamespace(openalex_api_key=None))
    batch = asyncio.run(adapter.collect("AI infrastructure", cursor=None, limit=1))
    assert len(batch.documents) == 4
    assert {document.metadata["openalex_resource"] for document in batch.documents} == set(
        RESOURCE_TYPES
    )
    assert all("select" in (params or {}) for _, params in http.calls)
    assert all(
        document.external_id.startswith("https://openalex.org/") for document in batch.documents
    )


def test_openalex_converts_updated_timestamp_to_supported_daily_boundary():
    result = {
        "results": [
            {
                "id": "https://openalex.org/W1",
                "display_name": "AI infrastructure",
                "updated_date": "2026-09-29T08:30:00",
                "ids": {},
            }
        ]
    }
    http = FakeHttp({f"https://api.openalex.org/{resource}": result for resource in RESOURCE_TYPES})
    adapter = OpenAlexAdapter(http, SimpleNamespace(openalex_api_key=None))
    batch = asyncio.run(adapter.collect("AI infrastructure", cursor=None, limit=1))
    assert json.loads(batch.next_cursor)["works"] == "2026-09-29"


class OneDocumentAdapter:
    source = Source(
        source_key="fixture:ingest", source_type="fixture", base_url="https://example.org"
    )

    def source_policy(self, source_id: UUID) -> SourcePolicy:
        return SourcePolicy(
            source_id=source_id,
            terms_url="https://example.org/terms",
            reviewed_at=datetime.now(UTC),
            active=True,
            policy={"llm_collection": False},
        )

    async def collect(self, query: str, *, cursor: str | None, limit: int) -> CollectionBatch:
        doc = CollectedDocument(
            external_id="one",
            canonical_url="https://example.org/one",
            source_url="https://example.org/one",
            source_type="fixture",
            raw_payload='{"text":"evidence"}',
            text="Evidence text",
            original_reference="Evidence text",
            retrieved_at=datetime.now(UTC),
        )
        return CollectionBatch([doc], "done", api_requests=1)


def test_unchanged_hash_is_not_normalized_or_emitted_twice(repository):
    service = IngestionService(repository)
    first = asyncio.run(service.collect(OneDocumentAdapter(), "AI infrastructure"))
    second = asyncio.run(service.collect(OneDocumentAdapter(), "AI infrastructure"))
    assert (first.documents_persisted, first.normalized_evidence_emitted) == (1, 1)
    assert (second.duplicates_removed, second.normalized_evidence_emitted) == (1, 0)
    assert repository.storage_metrics()["evidence"] == 1
