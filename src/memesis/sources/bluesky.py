"""Bluesky historical seeding and Jetstream-event normalization.

Historical search uses the public AppView endpoint. Jetstream itself is a
forward-only stream, so it is represented by the deterministic event parser
below and is intentionally not opened by the bounded developer collection run.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import UUID

from memesis.domain.schemas import Source, SourcePolicy
from memesis.ingestion.contracts import CollectedDocument, CollectionBatch
from memesis.ingestion.http import ResilientHttpClient
from memesis.sources.base import active_api_policy


def _time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


class BlueskyAdapter:
    def __init__(self, http: ResilientHttpClient) -> None:
        self._http = http
        self._source = Source(
            source_key="bluesky:appview-jetstream",
            source_type="bluesky",
            base_url="https://api.bsky.app",
            terms_url="https://bsky.social/about/support/tos",
            metadata={"historical": "appview", "forward": "jetstream"},
        )

    @property
    def source(self) -> Source:
        return self._source

    def source_policy(self, source_id: UUID) -> SourcePolicy:
        return active_api_policy(source_id, "https://bsky.social/about/support/tos", rate_limit=60)

    async def collect(self, query: str, *, cursor: str | None, limit: int) -> CollectionBatch:
        params: dict[str, object] = {"q": query, "limit": min(limit, 100), "sort": "latest"}
        # An opaque pagination cursor walks older results on future runs.
        # AppView's timestamp boundary keeps scheduled collection forward-only.
        if cursor:
            params["since"] = cursor
        response = await self._http.get(
            "https://api.bsky.app/xrpc/app.bsky.feed.searchPosts",
            params=params,
            min_interval_seconds=1.0,
        )
        payload = json.loads(response.body)
        documents = [self._from_post(post, query) for post in payload.get("posts", [])]
        indexed_at = [
            value
            for post in payload.get("posts", [])
            if isinstance(post, dict)
            for value in (_time(str(post.get("indexedAt") or "")),)
            if value is not None
        ]
        return CollectionBatch(
            [item for item in documents if item is not None],
            max(indexed_at).isoformat() if indexed_at else cursor,
            response.request_count,
            int(response.from_cache),
        )

    @staticmethod
    def _from_post(post: dict[str, object], query: str) -> CollectedDocument | None:
        author = post.get("author") if isinstance(post.get("author"), dict) else {}
        record = post.get("record") if isinstance(post.get("record"), dict) else {}
        uri = str(post.get("uri") or "")
        handle = str(author.get("handle") or "")
        rkey = uri.rsplit("/", 1)[-1] if uri else ""
        text = str(record.get("text") or "").strip()
        if not uri or not handle or not text:
            return None
        return CollectedDocument(
            external_id=uri,
            canonical_url=f"https://bsky.app/profile/{handle}/post/{rkey}",
            source_url=f"https://bsky.app/profile/{handle}/post/{rkey}",
            source_type="bluesky",
            raw_payload=json.dumps(post, sort_keys=True),
            text=text,
            original_reference=text[:280],
            retrieved_at=datetime.now(UTC),
            published_at=_time(str(record.get("createdAt") or post.get("indexedAt") or "")),
            updated_at=_time(str(post.get("indexedAt") or "")),
            content_type="application/json",
            metadata={
                "author_handle": handle,
                "did": author.get("did"),
                "query": query,
                "ingestion_path": "appview",
            },
        )


class JetstreamEventNormalizer:
    """Turns a single public Jetstream post commit into the same common envelope."""

    @staticmethod
    def normalize(event: dict[str, object]) -> CollectedDocument | None:
        commit = event.get("commit") if isinstance(event.get("commit"), dict) else {}
        record = commit.get("record") if isinstance(commit.get("record"), dict) else {}
        did, rkey = str(event.get("did") or ""), str(commit.get("rkey") or "")
        text = str(record.get("text") or "").strip()
        if not did or not rkey or not text or commit.get("operation") == "delete":
            return None
        uri = f"at://{did}/app.bsky.feed.post/{rkey}"
        return CollectedDocument(
            external_id=uri,
            canonical_url=f"https://bsky.app/profile/{did}/post/{rkey}",
            source_url=f"https://bsky.app/profile/{did}/post/{rkey}",
            source_type="bluesky",
            raw_payload=json.dumps(event, sort_keys=True),
            text=text,
            original_reference=text[:280],
            retrieved_at=datetime.now(UTC),
            published_at=_time(str(record.get("createdAt") or "")),
            content_type="application/json",
            metadata={"did": did, "ingestion_path": "jetstream", "time_us": event.get("time_us")},
        )
