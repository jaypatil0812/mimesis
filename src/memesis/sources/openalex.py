"""Small, field-limited OpenAlex API adapter; the full dataset is not replicated."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from memesis.config import Settings
from memesis.domain.schemas import Source, SourcePolicy
from memesis.ingestion.contracts import CollectedDocument, CollectionBatch
from memesis.ingestion.http import ResilientHttpClient
from memesis.ingestion.normalizer import normalize_text
from memesis.sources.base import active_api_policy

RESOURCE_TYPES = ("authors", "works", "topics", "institutions")

# Retain only the material needed for source citation and later deterministic
# resolution. Large relationship payloads are not evidence in Phase 2.
SELECT_FIELDS = {
    "authors": "id,display_name,ids,updated_date,works_count,cited_by_count",
    "works": (
        "id,title,display_name,doi,publication_date,updated_date,"
        "abstract_inverted_index,authorships,topics,cited_by_count,ids"
    ),
    "topics": "id,display_name,description,works_count,cited_by_count,updated_date,ids",
    "institutions": "id,display_name,homepage_url,works_count,cited_by_count,updated_date,ids",
}


def _abstract(inverted_index: object) -> str:
    if not isinstance(inverted_index, dict):
        return ""
    positions: list[tuple[int, str]] = []
    for word, offsets in inverted_index.items():
        if isinstance(offsets, list):
            positions.extend((int(offset), str(word)) for offset in offsets)
    return " ".join(word for _, word in sorted(positions))


def _updated_day(value: str) -> str:
    """OpenAlex's `from_updated_date` filter accepts a calendar date only."""
    return value[:10]


class OpenAlexAdapter:
    def __init__(self, http: ResilientHttpClient, settings: Settings) -> None:
        self._http = http
        self._settings = settings
        self._source = Source(
            source_key="openalex:api",
            source_type="openalex",
            base_url="https://api.openalex.org",
            terms_url="https://docs.openalex.org/how-to-use-the-api/get-lists-of-entities/paging",
            metadata={"mode": "api", "field_selection": "memesis_phase2"},
        )

    @property
    def source(self) -> Source:
        return self._source

    def source_policy(self, source_id: UUID) -> SourcePolicy:
        return active_api_policy(
            source_id,
            "https://docs.openalex.org/how-to-use-the-api/get-lists-of-entities/paging",
            rate_limit=60,
        )

    async def collect(self, query: str, *, cursor: str | None, limit: int) -> CollectionBatch:
        saved_boundaries = json.loads(cursor) if cursor else {}
        next_boundaries: dict[str, str | None] = {}
        documents: list[CollectedDocument] = []
        requests = cache_hits = 0
        failures: list[dict[str, str]] = []
        for resource in RESOURCE_TYPES:
            params: dict[str, Any] = {
                "search": query,
                "per-page": min(limit, 25),
                "select": SELECT_FIELDS[resource],
            }
            # An inclusive daily high-water mark avoids revisiting historical
            # search results while hashes safely absorb same-day overlap.
            if boundary := saved_boundaries.get(resource):
                params["filter"] = f"from_updated_date:{boundary}"
            if self._settings.openalex_api_key:
                params["api_key"] = self._settings.openalex_api_key
            try:
                response = await self._http.get(
                    f"https://api.openalex.org/{resource}", params=params, min_interval_seconds=1.0
                )
                requests += response.request_count
                cache_hits += int(response.from_cache)
                payload = json.loads(response.body)
                updated_dates: list[str] = []
                for item in payload.get("results", []):
                    if isinstance(item.get("updated_date"), str):
                        updated_dates.append(_updated_day(item["updated_date"]))
                    document = self._record(resource, item, query)
                    if document:
                        documents.append(document)
                next_boundaries[resource] = max(
                    updated_dates, default=saved_boundaries.get(resource)
                )
            except (
                Exception
            ) as error:  # source-isolated: other OpenAlex resource types still complete
                failures.append({"resource": resource, "error": type(error).__name__})
                next_boundaries[resource] = saved_boundaries.get(resource)
        return CollectionBatch(
            documents, json.dumps(next_boundaries, sort_keys=True), requests, cache_hits, failures
        )

    @staticmethod
    def _record(resource: str, item: dict[str, Any], query: str) -> CollectedDocument | None:
        identifier = str(item.get("id") or "")
        if not identifier.startswith("https://openalex.org/"):
            return None
        display_name = str(item.get("display_name") or item.get("title") or "").strip()
        abstract = _abstract(item.get("abstract_inverted_index")) if resource == "works" else ""
        description = str(item.get("description") or item.get("homepage_url") or "")
        text = normalize_text(
            "\n".join(part for part in (display_name, abstract, description) if part)
        )
        if not text:
            return None
        publication_date = item.get("publication_date")
        published_at = None
        if isinstance(publication_date, str):
            try:
                published_at = datetime.fromisoformat(publication_date).replace(tzinfo=UTC)
            except ValueError:
                pass
        return CollectedDocument(
            external_id=identifier,
            canonical_url=str(item.get("doi") or identifier),
            source_url=identifier,
            source_type="openalex",
            raw_payload=json.dumps(item, sort_keys=True),
            text=text,
            original_reference=display_name or text[:280],
            retrieved_at=datetime.now(UTC),
            published_at=published_at,
            updated_at=(
                datetime.fromisoformat(item["updated_date"]).replace(tzinfo=UTC)
                if isinstance(item.get("updated_date"), str)
                else None
            ),
            content_type="application/json",
            metadata={
                "openalex_id": identifier,
                "openalex_resource": resource,
                "external_ids": item.get("ids", {}),
                "cited_by_count": item.get("cited_by_count"),
                "query": query,
            },
        )
