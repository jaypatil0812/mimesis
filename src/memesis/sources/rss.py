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
from memesis.ingestion.http import HttpResult
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
        state = json.loads(cursor) if cursor and cursor.startswith("{") else {}
        response = HttpResult(state["body"], 200, {}, True, 0) if "body" in state else await self._http.get(self._feed_url, min_interval_seconds=1.0)
        retrieved_at = datetime.fromisoformat(state["retrieved_at"]) if "retrieved_at" in state else datetime.now(UTC)
        feed = feedparser.parse(response.body)
        documents: list[CollectedDocument] = []
        query_terms = set() if query.startswith("feed:") else {term for term in query.casefold().split() if len(term) > 2}
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
            # Revisit the finite feed: undated entries, edits and non-ISO dates
            # cannot safely be ordered by a string watermark. Hashes deduplicate.
            documents.append(
                CollectedDocument(
                    external_id=external_id,
                    canonical_url=link,
                    source_url=link,
                    source_type="rss",
                    raw_payload=json.dumps(dict(entry), sort_keys=True, default=str),
                    text=text,
                    original_reference=title or summary[:280],
                    retrieved_at=retrieved_at,
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
        offset = state.get("offset", 0)
        complete = offset + limit >= len(documents)
        return CollectionBatch(
            documents[offset:offset + limit],
            None,
            response.request_count,
            int(response.from_cache),
            [{"source": "rss", "error": "invalid_feed"}] if feed.bozo and not feed.entries else [],
            complete=complete,
            continuation_cursor=json.dumps({"offset": offset + limit, "body": response.body, "retrieved_at": retrieved_at.isoformat()}) if not complete else None,
            coverage_notes=["Finite feed contents only; disappeared historical entries require an archive source."]
        )
