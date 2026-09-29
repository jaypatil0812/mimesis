"""RSS/Atom collection with one shared normalized output schema."""

from __future__ import annotations

import json
from calendar import timegm
from datetime import UTC, datetime
from uuid import UUID

import feedparser

from memesis.domain.schemas import Source, SourcePolicy
from memesis.ingestion.contracts import CollectedDocument, CollectionBatch
from memesis.ingestion.http import ResilientHttpClient
from memesis.ingestion.normalizer import normalize_text


def _entry_time(entry: object) -> datetime | None:
    for field in ("published_parsed", "updated_parsed"):
        parsed = getattr(entry, "get", lambda _key: None)(field)
        if parsed:
            return datetime.fromtimestamp(timegm(parsed), UTC)
    return None


class RssAdapter:
    def __init__(self, http: ResilientHttpClient, feed_url: str) -> None:
        self._http = http
        self._feed_url = feed_url
        self._source = Source(
            source_key=f"rss:{feed_url}",
            source_type="rss",
            base_url=feed_url,
            metadata={"feed_url": feed_url},
        )

    @property
    def source(self) -> Source:
        return self._source

    def source_policy(self, source_id: UUID) -> SourcePolicy:
        return SourcePolicy(
            source_id=source_id,
            terms_url=self._feed_url,
            reviewed_at=datetime.now(UTC),
            active=True,
            policy={
                "access_method": "public_rss_atom_feed",
                "rate_limit_per_minute": 30,
                "collection": "feed_metadata_and_entry_text_only",
                "llm_collection": False,
            },
        )

    async def collect(self, query: str, *, cursor: str | None, limit: int) -> CollectionBatch:
        response = await self._http.get(self._feed_url, min_interval_seconds=1.0)
        feed = feedparser.parse(response.body)
        documents: list[CollectedDocument] = []
        query_terms = {term for term in query.casefold().split() if len(term) > 2}
        for entry in feed.entries:
            title = str(entry.get("title") or "")
            summary = normalize_text(str(entry.get("summary") or entry.get("description") or ""))
            text = normalize_text(f"{title}\n{summary}")
            if query_terms and not any(term in text.casefold() for term in query_terms):
                continue
            link = str(entry.get("link") or "")
            external_id = str(entry.get("id") or link)
            if not link or not external_id:
                continue
            entry_cursor = str(entry.get("updated") or entry.get("published") or external_id)
            if cursor and entry_cursor <= cursor:
                continue
            documents.append(
                CollectedDocument(
                    external_id=external_id,
                    canonical_url=link,
                    source_url=link,
                    source_type="rss",
                    raw_payload=json.dumps(dict(entry), sort_keys=True, default=str),
                    text=text,
                    original_reference=title or summary[:280],
                    retrieved_at=datetime.now(UTC),
                    published_at=_entry_time(entry),
                    content_type="application/rss+xml",
                    metadata={
                        "feed_url": self._feed_url,
                        "author": entry.get("author"),
                        "query": query,
                        "entry_cursor": entry_cursor,
                    },
                )
            )
        documents.sort(key=lambda item: str(item.metadata["entry_cursor"]))
        return CollectionBatch(
            documents[:limit],
            str(documents[-1].metadata["entry_cursor"]) if documents else cursor,
            response.request_count,
            int(response.from_cache),
        )
