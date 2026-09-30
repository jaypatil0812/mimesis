"""Durable collect → normalize → deduplicate → evidence pipeline."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

from memesis.domain.schemas import (
    Document,
    DocumentVersion,
    Evidence,
    ExtractionMethod,
    NormalizedDocument,
    Provenance,
)
from memesis.graph.repository import GraphRepository
from memesis.ingestion.contracts import CollectedDocument
from memesis.ingestion.normalizer import NORMALIZER_VERSION, normalize_text, sha256_text
from memesis.sources.base import SourceAdapter


@dataclass
class IngestionReport:
    source_key: str
    query: str
    documents_fetched: int = 0
    documents_persisted: int = 0
    normalized_evidence_emitted: int = 0
    duplicates_removed: int = 0
    failures: list[dict[str, str]] = field(default_factory=list)
    external_api_requests: int = 0
    cache_hits: int = 0
    llm_calls: int = 0
    runtime_seconds: float = 0.0
    pages_fetched: int = 0
    pagination_complete: bool = False
    checkpoint_advanced: bool = False
    evidence_ids: list[str] = field(default_factory=list)
    coverage_notes: list[str] = field(default_factory=list)
    namespace: str = ""
    started_at: str = ""

    @property
    def estimated_cost_usd(self) -> float:
        # All included APIs are public/no-key for this bounded Phase 2 run.
        return 0.0

    def as_metrics(self) -> dict[str, object]:
        result = asdict(self)
        result["estimated_cost_usd"] = self.estimated_cost_usd
        return result


class IngestionService:
    """Single deterministic collection boundary. It deliberately has no LLM dependency."""

    def __init__(self, repository: GraphRepository) -> None:
        self._repository = repository

    async def collect(
        self, adapter: SourceAdapter, query: str, *, limit: int = 5,
        max_pages: int = 1, namespace: str = "", initial_cursor: str | None = None,
        lease_owner: str | None = None,
    ) -> IngestionReport:
        started = datetime.now(UTC)
        source = self._repository.add_source(adapter.source)
        policy = (self._repository.get_latest_source_policy(source.id) if hasattr(self._repository, "get_latest_source_policy")
                  else self._repository.get_active_source_policy(source.id))
        if policy is None:
            policy = self._repository.add_source_policy(adapter.source_policy(source.id))
        if not policy.active:
            raise PermissionError(f"collection blocked: no active policy for {source.source_key}")

        report = IngestionReport(source_key=source.source_key, query=query, namespace=namespace, started_at=started.isoformat())
        run_id = self._repository.start_collection_run(source.id, query)
        if limit < 1 or max_pages < 1:
            raise ValueError("collection budgets must be positive")
        boundary_key = (f"watch:{sha256_text(namespace)}:" if namespace else "") + f"query:{sha256_text(query)}"
        cursor = self._repository.get_collection_cursor(source.id, boundary_key) or initial_cursor
        pending_key = boundary_key + ":pending"
        cursor = self._repository.get_collection_cursor(source.id, pending_key) or cursor
        try:
            for _ in range(max_pages):
                batch = await adapter.collect(query, cursor=cursor, limit=limit)
                report.pages_fetched += 1
                report.documents_fetched += len(batch.documents)
                report.external_api_requests += batch.api_requests
                report.cache_hits += batch.cache_hits
                report.failures.extend(batch.failures)
                report.coverage_notes.extend(batch.coverage_notes)
                for collected in batch.documents:
                    outcome = self._persist_document(source.id, collected)
                    if outcome == "emitted":
                        report.documents_persisted += 1
                        report.normalized_evidence_emitted += 1
                    elif outcome == "duplicate":
                        report.duplicates_removed += 1
                    evidence = self._repository.find_evidence_by_hash(sha256_text(normalize_text(collected.text)))
                    if evidence and str(evidence.id) not in report.evidence_ids:
                        report.evidence_ids.append(str(evidence.id))
                # Durable receipt precedes any cursor advance. An interrupted
                # worker can recover extraction IDs without re-fetching a page.
                if hasattr(self._repository, "record_collection_progress"):
                    self._repository.record_collection_progress(run_id, report.as_metrics())
                if batch.failures:
                    break
                if batch.complete:
                    self._repository.save_collection_cursor(source.id, boundary_key, batch.next_cursor,
                        {"query": query, "normalizer_version": NORMALIZER_VERSION}, **({"lease_owner": lease_owner} if lease_owner else {}))
                    self._repository.save_collection_cursor(source.id, pending_key, None, {}, **({"lease_owner": lease_owner} if lease_owner else {}))
                    report.pagination_complete = report.checkpoint_advanced = True
                    break
                if not batch.continuation_cursor or batch.continuation_cursor == cursor:
                    raise ValueError("pagination made no progress")
                cursor = batch.continuation_cursor
                self._repository.save_collection_cursor(source.id, pending_key, cursor,
                    {"query": query, "completed_checkpoint_unchanged": True}, **({"lease_owner": lease_owner} if lease_owner else {}))
            if not report.pagination_complete and not report.failures:
                report.coverage_notes.append("Page budget reached; scan will resume. Completed checkpoint unchanged.")
            report.runtime_seconds = (datetime.now(UTC) - started).total_seconds()
            self._repository.finish_collection_run(
                run_id,
                status="completed" if report.pagination_complete and not report.failures else "partial",
                metrics=report.as_metrics(),
                errors=report.failures,
            )
            return report
        except Exception as error:
            report.failures.append(
                {"source": source.source_key, "error": type(error).__name__}
            )
            report.runtime_seconds = (datetime.now(UTC) - started).total_seconds()
            self._repository.finish_collection_run(
                run_id, status="failed", metrics=report.as_metrics(), errors=report.failures
            )
            return report

    def _persist_document(self, source_id: object, collected: CollectedDocument) -> str:
        raw_hash = sha256_text(collected.raw_payload)
        normalized_text = normalize_text(collected.text)
        if not normalized_text:
            return "duplicate"
        normalized_hash = sha256_text(normalized_text)
        document = self._repository.add_document(
            Document(
                source_id=source_id,  # type: ignore[arg-type]
                external_id=collected.external_id,
                canonical_url=collected.canonical_url,
            )
        )
        existing_version = self._repository.find_document_version_by_hash(raw_hash)
        if existing_version and existing_version.document_id == document.id:
            return "duplicate"
        duplicate_evidence = self._repository.find_evidence_by_hash(normalized_hash)
        metadata: dict[str, Any] = {
            **collected.metadata,
            "content_type": collected.content_type,
            "source_url": collected.source_url,
            "updated_at": collected.updated_at.isoformat() if collected.updated_at else None,
            "normalizer_version": NORMALIZER_VERSION,
        }
        if duplicate_evidence:
            metadata["duplicate_of_evidence_id"] = str(duplicate_evidence.id)
        version = self._repository.add_document_version(
            DocumentVersion(
                document_id=document.id,
                content_hash=raw_hash,
                raw_payload=collected.raw_payload,
                retrieved_at=collected.retrieved_at,
                published_at=collected.published_at,
                source_metadata=metadata,
            )
        )
        if duplicate_evidence:
            return "duplicate"
        evidence = self._repository.add_evidence(
            Evidence(
                source_id=source_id,  # type: ignore[arg-type]
                document_version_id=version.id,
                source_url=collected.source_url,
                source_type=collected.source_type,
                retrieved_at=collected.retrieved_at,
                published_at=collected.published_at,
                original_reference=collected.original_reference,
                raw_text=collected.text,
                normalized_text=normalized_text,
                content_hash=normalized_hash,
                external_id=collected.external_id,
                updated_at=collected.updated_at,
                extraction_method=ExtractionMethod.DETERMINISTIC,
                entity_ids=(),
                metadata=metadata,
            )
        )
        self._repository.add_normalized_document(
            NormalizedDocument(
                document_version_id=version.id,
                normalizer_version=NORMALIZER_VERSION,
                normalized_text=normalized_text,
                content_hash=normalized_hash,
                provenance=Provenance(
                    source_url=collected.source_url,
                    source_type=collected.source_type,
                    retrieved_at=collected.retrieved_at,
                    published_at=collected.published_at,
                    original_reference=collected.original_reference,
                    evidence_ids=(evidence.id,),
                    confidence=1.0,
                    extraction_method=ExtractionMethod.DETERMINISTIC,
                    entity_ids=(),
                ),
            )
        )
        return "emitted"
