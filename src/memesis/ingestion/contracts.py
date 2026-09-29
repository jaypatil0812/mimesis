"""Common source-to-ledger envelope used by every Phase 2 connector."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class CollectedDocument:
    """Raw source result before deterministic normalization and persistence."""

    external_id: str
    canonical_url: str
    source_url: str
    source_type: str
    raw_payload: str
    text: str
    original_reference: str
    retrieved_at: datetime
    published_at: datetime | None = None
    updated_at: datetime | None = None
    content_type: str = "text/plain"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CollectionBatch:
    documents: list[CollectedDocument]
    next_cursor: str | None
    api_requests: int = 0
    cache_hits: int = 0
    failures: list[dict[str, str]] = field(default_factory=list)
