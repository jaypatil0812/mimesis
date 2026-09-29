"""Replaceable, narrow source adapter boundary for Phase 2."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from memesis.domain.schemas import Source, SourcePolicy
from memesis.ingestion.contracts import CollectionBatch


class SourceAdapter(Protocol):
    @property
    def source(self) -> Source: ...

    def source_policy(self, source_id: UUID) -> SourcePolicy: ...

    async def collect(self, query: str, *, cursor: str | None, limit: int) -> CollectionBatch: ...


def active_api_policy(source_id: UUID, terms_url: str, *, rate_limit: int) -> SourcePolicy:
    return SourcePolicy(
        source_id=source_id,
        terms_url=terms_url,
        reviewed_at=datetime.now(UTC),
        active=True,
        policy={
            "access_method": "official_public_api",
            "rate_limit_per_minute": rate_limit,
            "collection": "metadata_and_public_text_only",
            "llm_collection": False,
        },
    )
