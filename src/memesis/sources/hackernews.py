"""Hacker News evidence through the public Algolia API."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import UUID

from memesis.domain.schemas import Source, SourcePolicy
from memesis.ingestion.contracts import CollectedDocument, CollectionBatch
from memesis.ingestion.http import ResilientHttpClient
from memesis.ingestion.normalizer import normalize_text
from memesis.sources.base import active_api_policy


class HackerNewsAdapter:
    def __init__(self, http: ResilientHttpClient) -> None:
        self._http = http
        self._source = Source(
            source_key="hackernews:algolia",
            source_type="hackernews",
            base_url="https://hn.algolia.com",
            terms_url="https://hn.algolia.com/about",
            metadata={"adapter": "algolia-search_by_date", "license": "source-policy"},
        )

    @property
    def source(self) -> Source:
        return self._source

    def source_policy(self, source_id: UUID) -> SourcePolicy:
        return active_api_policy(source_id, "https://hn.algolia.com/about", rate_limit=120)

    async def collect(self, query: str, *, cursor: str | None, limit: int) -> CollectionBatch:
        state = json.loads(cursor) if cursor and cursor.startswith("{") else {
            "since": cursor, "until": int(datetime.now(UTC).timestamp()), "page": 0, "high_water": cursor}
        params: dict[str, object] = {
            "query": query,
            "tags": "(story,comment)",
            "hitsPerPage": min(limit, 100),
            "typoTolerance": "false",
            "page": state["page"],
        }
        # `search_by_date` is newest-first. Treat the checkpoint as a
        # high-water mark rather than an Algolia page number, which is only
        # appropriate for an explicit historical backfill.
        filters = [f"created_at_i<{state['until']}"]
        if state["since"]:
            filters.insert(0, f"created_at_i>={state['since']}")
        params["numericFilters"] = ",".join(filters)
        response = await self._http.get(
            "https://hn.algolia.com/api/v1/search_by_date", params=params, min_interval_seconds=0.5
        )
        payload = json.loads(response.body)
        documents: list[CollectedDocument] = []
        timestamps: list[int] = []
        for hit in payload.get("hits", []):
            object_id = str(hit.get("objectID") or "")
            if not object_id:
                continue
            created_at_i = hit.get("created_at_i")
            if created_at_i:
                timestamps.append(int(created_at_i))
            title = hit.get("title") or hit.get("story_title") or ""
            body = normalize_text(hit.get("comment_text") or hit.get("story_text") or "")
            text = normalize_text(f"{title}\n{body}")
            if not text:
                continue
            published_at = datetime.fromtimestamp(int(created_at_i), UTC) if created_at_i else None
            documents.append(
                CollectedDocument(
                    external_id=object_id,
                    canonical_url=f"https://news.ycombinator.com/item?id={object_id}",
                    source_url=f"https://news.ycombinator.com/item?id={object_id}",
                    source_type="hackernews",
                    raw_payload=json.dumps(hit, sort_keys=True),
                    text=text,
                    original_reference=title or body[:280],
                    retrieved_at=datetime.now(UTC),
                    published_at=published_at,
                    content_type="application/json",
                    metadata={
                        "author_handle": hit.get("author"),
                        "hn_url": hit.get("url"),
                        "score": hit.get("points"),
                        "query": query,
                    },
                )
            )
        next_cursor = str(max(timestamps + ([int(state["high_water"])] if state["high_water"] else []))) if timestamps or state["high_water"] else None
        state["high_water"] = next_cursor
        pages = payload.get("nbPages")
        complete = state["page"] + 1 >= int(pages) if pages is not None else len(payload.get("hits", [])) < params["hitsPerPage"]
        failures = []
        if complete and pages is not None and int(payload.get("nbHits", 0)) > int(pages) * int(params["hitsPerPage"]):
            failures = [{"source": "hackernews", "error": "provider_result_cap; narrow query/window before checkpoint can advance"}]
        state["page"] += 1
        return CollectionBatch(
            documents, next_cursor, response.request_count, int(response.from_cache), failures,
            complete=complete, continuation_cursor=json.dumps(state),
            coverage_notes=["Search index coverage and late indexing are not guaranteed; timestamp overlap is deduplicated."]
        )
