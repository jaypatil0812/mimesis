"""Typed graph implementation backed by ordinary relational adjacency tables."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID, uuid4, uuid5

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, sessionmaker

from memesis.db.models import (
    AssertionRow,
    CollectionCursorRow,
    CollectionRunRow,
    DecisionCacheRow,
    DocumentRow,
    DocumentVersionRow,
    EntityAliasRow,
    EntityExternalIdentifierRow,
    EvidenceGraphProjectionRow,
    EvidenceRow,
    EvidenceSpanRow,
    ExtractionCacheRow,
    FetchCacheRow,
    GraphEdgeRow,
    GraphNodeRow,
    GraphRevisionRow,
    MergeDecisionRow,
    NormalizedDocumentRow,
    PerceptionObservationRow,
    ReasoningRunRow,
    ScoreRecordRow,
    SourcePolicyRow,
    SourceRow,
    TombstoneRow,
)
from memesis.domain.schemas import (
    Assertion,
    Belief,
    CanonicalNode,
    Company,
    Content,
    Document,
    DocumentVersion,
    EdgeType,
    EntityAlias,
    EntityExternalIdentifier,
    Event,
    Evidence,
    EvidenceSpan,
    GraphEdge,
    Market,
    MergeDecision,
    NodeType,
    NormalizedDocument,
    PerceptionDimension,
    PerceptionObservation,
    PerceptionStance,
    Person,
    Product,
    Provenance,
    ScoreRecord,
    Source,
    SourcePolicy,
    validate_edge_endpoints,
)

NODE_SCHEMAS: dict[NodeType, type[CanonicalNode]] = {
    NodeType.PERSON: Person,
    NodeType.COMPANY: Company,
    NodeType.BELIEF: Belief,
    NodeType.MARKET: Market,
    NodeType.PRODUCT: Product,
    NodeType.CONTENT: Content,
    NodeType.EVENT: Event,
}


class SqlGraphRepository:
    """Graph adapter; SQLAlchemy permits PostgreSQL production and SQLite tests."""

    def __init__(self, sessions: sessionmaker[Session]):
        self._sessions = sessions

    def add_source(self, source: Source) -> Source:
        with self._sessions.begin() as session:
            existing = session.scalar(
                select(SourceRow).where(SourceRow.source_key == source.source_key)
            )
            if existing:
                return self._source_from_row(existing)
            row = SourceRow(
                id=str(source.id),
                source_key=source.source_key,
                source_type=source.source_type,
                base_url=str(source.base_url),
                terms_url=str(source.terms_url) if source.terms_url else None,
                metadata_json=source.metadata,
            )
            session.add(row)
            session.flush()
            return self._source_from_row(row)

    def add_source_policy(self, policy: SourcePolicy) -> SourcePolicy:
        with self._sessions.begin() as session:
            if not session.get(SourceRow, str(policy.source_id)):
                raise ValueError(f"unknown source {policy.source_id}")
            if policy.active:
                active_rows = session.scalars(
                    select(SourcePolicyRow).where(
                        SourcePolicyRow.source_id == str(policy.source_id),
                        SourcePolicyRow.active.is_(True),
                    )
                ).all()
                for old in active_rows:
                    if old.policy == policy.policy and old.terms_url == (
                        str(policy.terms_url) if policy.terms_url else None
                    ):
                        return self._policy_from_row(old)
                    old.active = False
            row = SourcePolicyRow(
                id=str(policy.id),
                source_id=str(policy.source_id),
                terms_url=str(policy.terms_url) if policy.terms_url else None,
                reviewed_at=policy.reviewed_at,
                policy=policy.policy,
                active=policy.active,
            )
            session.add(row)
            session.flush()
            return self._policy_from_row(row)

    def add_document(self, document: Document) -> Document:
        with self._sessions.begin() as session:
            if not session.get(SourceRow, str(document.source_id)):
                raise ValueError(f"unknown source {document.source_id}")
            existing = session.scalar(
                select(DocumentRow).where(
                    DocumentRow.source_id == str(document.source_id),
                    DocumentRow.external_id == document.external_id,
                )
            )
            if existing:
                if existing.canonical_url != str(document.canonical_url):
                    raise ValueError("document identity collision: canonical URL differs")
                return self._document_from_row(existing)
            row = DocumentRow(
                id=str(document.id),
                source_id=str(document.source_id),
                external_id=document.external_id,
                canonical_url=str(document.canonical_url),
                created_at=datetime.now(UTC),
            )
            session.add(row)
            session.flush()
            return self._document_from_row(row)

    def add_document_version(self, version: DocumentVersion) -> DocumentVersion:
        with self._sessions.begin() as session:
            if not session.get(DocumentRow, str(version.document_id)):
                raise ValueError(f"unknown document {version.document_id}")
            existing = session.scalar(
                select(DocumentVersionRow).where(
                    DocumentVersionRow.document_id == str(version.document_id),
                    DocumentVersionRow.content_hash == version.content_hash,
                )
            )
            if existing:
                return self._version_from_row(existing)
            row = DocumentVersionRow(
                id=str(version.id),
                document_id=str(version.document_id),
                content_hash=version.content_hash,
                raw_payload=version.raw_payload,
                retrieved_at=version.retrieved_at,
                published_at=version.published_at,
                source_metadata=version.source_metadata,
            )
            session.add(row)
            session.flush()
            return self._version_from_row(row)

    def add_evidence(self, evidence: Evidence) -> Evidence:
        # Guard: reject evidence dated more than 1 day in the future — protects scoring windows
        if evidence.published_at is not None:
            from datetime import timedelta
            now_utc = datetime.now(UTC)
            pub = evidence.published_at
            if pub.tzinfo is None:
                pub = pub.replace(tzinfo=UTC)
            if pub > now_utc + timedelta(days=1):
                raise ValueError(
                    f"evidence published_at {pub.isoformat()} is more than 1 day in the future; "
                    "suspected data error or adversarial input"
                )
        with self._sessions.begin() as session:
            if not session.get(SourceRow, str(evidence.source_id)):
                raise ValueError(f"unknown source {evidence.source_id}")
            if evidence.document_version_id:
                version = session.get(DocumentVersionRow, str(evidence.document_version_id))
                if version is None:
                    raise ValueError(f"unknown document version {evidence.document_version_id}")
                document = session.get(DocumentRow, version.document_id)
                if document is None or document.source_id != str(evidence.source_id):
                    raise ValueError("evidence and document version must belong to the same source")
            existing = session.get(EvidenceRow, str(evidence.id))
            if existing:
                return self._evidence_from_row(existing)
            row = EvidenceRow(
                id=str(evidence.id),
                source_id=str(evidence.source_id),
                document_version_id=(
                    str(evidence.document_version_id) if evidence.document_version_id else None
                ),
                source_url=str(evidence.source_url),
                source_type=evidence.source_type,
                retrieved_at=evidence.retrieved_at,
                published_at=evidence.published_at,
                original_reference=evidence.original_reference,
                raw_text=evidence.raw_text,
                normalized_text=evidence.normalized_text,
                content_hash=evidence.content_hash,
                external_id=evidence.external_id,
                updated_at=evidence.updated_at,
                extraction_method=evidence.extraction_method.value,
                extraction_model=evidence.extraction_model,
                entity_ids=[str(entity_id) for entity_id in evidence.entity_ids],
                metadata_json=evidence.metadata,
            )
            session.add(row)
            session.flush()
            return self._evidence_from_row(row)

    def get_evidence(self, evidence_id: UUID) -> Evidence | None:
        with self._sessions() as session:
            row = session.get(EvidenceRow, str(evidence_id))
            return self._evidence_from_row(row) if row else None

    def list_evidence(self, limit: int | None = None) -> list[Evidence]:
        with self._sessions() as session:
            statement = select(EvidenceRow).order_by(EvidenceRow.retrieved_at, EvidenceRow.id)
            if limit is not None:
                statement = statement.limit(limit)
            return [self._evidence_from_row(row) for row in session.scalars(statement).all()]

    def get_normalized_document_for_version(
        self, document_version_id: UUID
    ) -> NormalizedDocument | None:
        with self._sessions() as session:
            row = session.scalar(
                select(NormalizedDocumentRow).where(
                    NormalizedDocumentRow.document_version_id == str(document_version_id)
                )
            )
            return self._normalized_from_row(row) if row else None

    def get_active_source_policy(self, source_id: UUID) -> SourcePolicy | None:
        with self._sessions() as session:
            row = session.scalar(
                select(SourcePolicyRow).where(
                    SourcePolicyRow.source_id == str(source_id),
                    SourcePolicyRow.active.is_(True),
                )
            )
            return self._policy_from_row(row) if row else None

    def find_document_version_by_hash(self, content_hash: str) -> DocumentVersion | None:
        """Find exact prior material across sources for deterministic deduplication."""
        with self._sessions() as session:
            row = session.scalar(
                select(DocumentVersionRow).where(DocumentVersionRow.content_hash == content_hash)
            )
            return self._version_from_row(row) if row else None

    def find_evidence_by_hash(self, content_hash: str) -> Evidence | None:
        with self._sessions() as session:
            row = session.scalar(
                select(EvidenceRow).where(EvidenceRow.content_hash == content_hash)
            )
            return self._evidence_from_row(row) if row else None

    def get_collection_cursor(self, source_id: UUID, boundary_key: str) -> str | None:
        with self._sessions() as session:
            row = session.scalar(
                select(CollectionCursorRow).where(
                    CollectionCursorRow.source_id == str(source_id),
                    CollectionCursorRow.boundary_key == boundary_key,
                )
            )
            return row.cursor if row else None

    def save_collection_cursor(
        self, source_id: UUID, boundary_key: str, cursor: str | None, metadata: dict[str, object]
    ) -> None:
        with self._sessions.begin() as session:
            row = session.scalar(
                select(CollectionCursorRow).where(
                    CollectionCursorRow.source_id == str(source_id),
                    CollectionCursorRow.boundary_key == boundary_key,
                )
            )
            if row is None:
                row = CollectionCursorRow(
                    id=str(uuid4()),
                    source_id=str(source_id),
                    boundary_key=boundary_key,
                    cursor=cursor,
                    updated_at=datetime.now(UTC),
                    metadata_json=metadata,
                )
                session.add(row)
            else:
                row.cursor = cursor
                row.updated_at = datetime.now(UTC)
                row.metadata_json = metadata

    def get_fetch_cache(self, cache_key: str) -> dict[str, object] | None:
        with self._sessions() as session:
            row = session.get(FetchCacheRow, cache_key)
            if row is None:
                return None
            return {
                "status_code": row.status_code,
                "body": row.response_body,
                "headers": row.response_headers or {},
                "fetched_at": row.fetched_at,
                "expires_at": row.expires_at,
            }

    def save_fetch_cache(
        self,
        cache_key: str,
        *,
        status_code: int,
        body: str,
        headers: dict[str, object],
        fetched_at: datetime,
        expires_at: datetime,
    ) -> None:
        with self._sessions.begin() as session:
            row = session.get(FetchCacheRow, cache_key)
            if row is None:
                session.add(
                    FetchCacheRow(
                        cache_key=cache_key,
                        status_code=status_code,
                        response_body=body,
                        response_headers=headers,
                        fetched_at=fetched_at,
                        expires_at=expires_at,
                    )
                )
            else:
                row.status_code = status_code
                row.response_body = body
                row.response_headers = headers
                row.fetched_at = fetched_at
                row.expires_at = expires_at

    def start_collection_run(self, source_id: UUID, query: str) -> UUID:
        run_id = uuid4()
        with self._sessions.begin() as session:
            session.add(
                CollectionRunRow(
                    id=str(run_id),
                    source_id=str(source_id),
                    query=query,
                    started_at=datetime.now(UTC),
                    status="running",
                    metrics={},
                    errors=[],
                )
            )
        return run_id

    def finish_collection_run(
        self,
        run_id: UUID,
        *,
        status: str,
        metrics: dict[str, object],
        errors: list[dict[str, object]],
    ) -> None:
        with self._sessions.begin() as session:
            row = session.get(CollectionRunRow, str(run_id))
            if row is None:
                raise ValueError(f"unknown collection run {run_id}")
            row.status = status
            row.completed_at = datetime.now(UTC)
            row.metrics = metrics
            row.errors = errors

    def storage_metrics(self) -> dict[str, int]:
        """Compact ledger counts for a bounded collection receipt."""
        with self._sessions() as session:
            return {
                "documents": int(
                    session.scalar(select(func.count()).select_from(DocumentRow)) or 0
                ),
                "document_versions": int(
                    session.scalar(select(func.count()).select_from(DocumentVersionRow)) or 0
                ),
                "normalized_documents": int(
                    session.scalar(select(func.count()).select_from(NormalizedDocumentRow)) or 0
                ),
                "evidence": int(session.scalar(select(func.count()).select_from(EvidenceRow)) or 0),
                "cached_responses": int(
                    session.scalar(select(func.count()).select_from(FetchCacheRow)) or 0
                ),
                "graph_nodes": int(
                    session.scalar(select(func.count()).select_from(GraphNodeRow)) or 0
                ),
                "graph_edges": int(
                    session.scalar(select(func.count()).select_from(GraphEdgeRow)) or 0
                ),
                "entity_aliases": int(
                    session.scalar(select(func.count()).select_from(EntityAliasRow)) or 0
                ),
                "external_identifiers": int(
                    session.scalar(select(func.count()).select_from(EntityExternalIdentifierRow))
                    or 0
                ),
                "evidence_graph_projections": int(
                    session.scalar(select(func.count()).select_from(EvidenceGraphProjectionRow))
                    or 0
                ),
                "deterministic_scores": int(
                    session.scalar(select(func.count()).select_from(ScoreRecordRow)) or 0
                ),
                "decision_cache": int(
                    session.scalar(select(func.count()).select_from(DecisionCacheRow)) or 0
                ),
                "reasoning_runs": int(
                    session.scalar(select(func.count()).select_from(ReasoningRunRow)) or 0
                ),
            }

    def get_decision_cache(self, cache_key: str) -> dict[str, object] | None:
        with self._sessions() as session:
            row = session.get(DecisionCacheRow, cache_key)
            if row is None:
                return None
            return {
                "cache_key": row.cache_key,
                "decision_type": row.decision_type,
                "context_hash": row.context_hash,
                "model": row.model,
                "version": row.version,
                "decision": row.decision,
                "probability": row.probability,
                "result": row.result_json,
                "created_at": row.created_at.isoformat(),
            }

    def save_decision_cache(self, cache_key: str, record: dict[str, object]) -> None:
        with self._sessions.begin() as session:
            if session.get(DecisionCacheRow, cache_key):
                return
            session.add(
                DecisionCacheRow(
                    cache_key=cache_key,
                    decision_type=str(record["decision_type"]),
                    context_hash=str(record["context_hash"]),
                    model=str(record["model"]),
                    version=str(record["version"]),
                    decision=str(record["decision"]),
                    probability=float(record["probability"]),
                    result_json=dict(record["result"]),
                    created_at=datetime.now(UTC),
                )
            )

    def save_reasoning_run(self, run_id: UUID, record: dict[str, object]) -> None:
        with self._sessions.begin() as session:
            if session.get(ReasoningRunRow, str(run_id)):
                return
            session.add(
                ReasoningRunRow(
                    id=str(run_id),
                    question=str(record["question"]),
                    intent_json=dict(record["intent"]),
                    packet_hash=str(record["packet_hash"]) if record.get("packet_hash") else None,
                    deep_reasoning_required=bool(record.get("deep_reasoning_required", False)),
                    model=str(record["model"]) if record.get("model") else None,
                    answer_json=dict(record["answer"]),
                    metrics_json=dict(record["metrics"]),
                    created_at=datetime.now(UTC),
                )
            )

    def get_reasoning_run(self, run_id: UUID) -> dict[str, object] | None:
        with self._sessions() as session:
            row = session.get(ReasoningRunRow, str(run_id))
            if row is None:
                return None
            return {
                "id": row.id,
                "question": row.question,
                "intent": row.intent_json,
                "packet_hash": row.packet_hash,
                "deep_reasoning_required": row.deep_reasoning_required,
                "model": row.model,
                "answer": row.answer_json,
                "metrics": row.metrics_json,
                "created_at": row.created_at.isoformat(),
            }

    def list_reasoning_runs(self, limit: int | None = None) -> list[dict[str, object]]:
        with self._sessions() as session:
            stmt = select(ReasoningRunRow).order_by(ReasoningRunRow.created_at.desc())
            if limit:
                stmt = stmt.limit(limit)
            rows = session.scalars(stmt).all()
            return [
                {
                    "id": row.id,
                    "question": row.question,
                    "intent": row.intent_json,
                    "packet_hash": row.packet_hash,
                    "deep_reasoning_required": row.deep_reasoning_required,
                    "model": row.model,
                    "answer": row.answer_json,
                    "metrics": row.metrics_json,
                    "created_at": row.created_at.isoformat(),
                }
                for row in rows
            ]


    def get_extraction_cache(self, cache_key: str) -> dict[str, object] | None:
        with self._sessions() as session:
            row = session.get(ExtractionCacheRow, cache_key)
            if row is None:
                return None
            return {
                "evidence_id": row.evidence_id,
                "content_hash": row.content_hash,
                "extractor_version": row.extractor_version,
                "prompt_version": row.prompt_version,
                "schema_version": row.schema_version,
                "model": row.model,
                "result": row.result_json,
                "input_tokens": row.input_tokens,
                "output_tokens": row.output_tokens,
                "llm_calls": row.llm_calls,
            }

    def save_extraction_cache(self, cache_key: str, record: dict[str, object]) -> None:
        with self._sessions.begin() as session:
            if session.get(ExtractionCacheRow, cache_key):
                return
            session.add(
                ExtractionCacheRow(
                    cache_key=cache_key,
                    evidence_id=str(record["evidence_id"]),
                    content_hash=str(record["content_hash"]),
                    extractor_version=str(record["extractor_version"]),
                    prompt_version=(
                        str(record["prompt_version"]) if record.get("prompt_version") else None
                    ),
                    schema_version=str(record["schema_version"]),
                    model=str(record["model"]) if record.get("model") else None,
                    result_json=dict(record["result"]),
                    input_tokens=int(record.get("input_tokens", 0)),
                    output_tokens=int(record.get("output_tokens", 0)),
                    llm_calls=int(record.get("llm_calls", 0)),
                    created_at=datetime.now(UTC),
                )
            )

    def has_evidence_projection(self, evidence_id: UUID, cache_key: str) -> bool:
        with self._sessions() as session:
            row = session.scalar(
                select(EvidenceGraphProjectionRow).where(
                    EvidenceGraphProjectionRow.evidence_id == str(evidence_id),
                    EvidenceGraphProjectionRow.cache_key == cache_key,
                )
            )
            return row is not None

    def save_evidence_projection(self, evidence_id: UUID, cache_key: str) -> None:
        with self._sessions.begin() as session:
            existing = session.scalar(
                select(EvidenceGraphProjectionRow).where(
                    EvidenceGraphProjectionRow.evidence_id == str(evidence_id),
                    EvidenceGraphProjectionRow.cache_key == cache_key,
                )
            )
            if existing:
                return
            session.add(
                EvidenceGraphProjectionRow(
                    id=str(uuid4()),
                    evidence_id=str(evidence_id),
                    cache_key=cache_key,
                    projected_at=datetime.now(UTC),
                )
            )

    def add_entity_alias(self, alias: EntityAlias) -> EntityAlias:
        with self._sessions.begin() as session:
            if not session.get(GraphNodeRow, str(alias.node_id)):
                raise ValueError(f"unknown graph node {alias.node_id}")
            existing = session.scalar(
                select(EntityAliasRow).where(
                    EntityAliasRow.node_id == str(alias.node_id),
                    EntityAliasRow.normalized_alias == alias.normalized_alias,
                    EntityAliasRow.source_scope == alias.source_scope,
                )
            )
            if existing:
                return self._alias_from_row(existing)
            row = EntityAliasRow(
                id=str(alias.id),
                node_id=str(alias.node_id),
                alias=alias.alias,
                normalized_alias=alias.normalized_alias,
                source_scope=alias.source_scope,
                confidence=alias.confidence,
                evidence_ids=[str(value) for value in alias.evidence_ids],
                created_at=alias.created_at,
            )
            session.add(row)
            session.flush()
            return self._alias_from_row(row)

    def add_external_identifier(
        self, identifier: EntityExternalIdentifier
    ) -> EntityExternalIdentifier:
        with self._sessions.begin() as session:
            if not session.get(GraphNodeRow, str(identifier.node_id)):
                raise ValueError(f"unknown graph node {identifier.node_id}")
            existing = session.scalar(
                select(EntityExternalIdentifierRow).where(
                    EntityExternalIdentifierRow.identifier_type == identifier.identifier_type,
                    EntityExternalIdentifierRow.normalized_value == identifier.normalized_value,
                )
            )
            if existing:
                if existing.node_id != str(identifier.node_id):
                    raise ValueError("external identifier is already assigned to another entity")
                return self._external_identifier_from_row(existing)
            row = EntityExternalIdentifierRow(
                id=str(identifier.id),
                node_id=str(identifier.node_id),
                identifier_type=identifier.identifier_type,
                value=identifier.value,
                normalized_value=identifier.normalized_value,
                confidence=identifier.confidence,
                evidence_ids=[str(value) for value in identifier.evidence_ids],
                created_at=identifier.created_at,
            )
            session.add(row)
            session.flush()
            return self._external_identifier_from_row(row)

    def find_node_by_external_identifier(
        self, identifier_type: str, normalized_value: str
    ) -> CanonicalNode | None:
        with self._sessions() as session:
            identifier = session.scalar(
                select(EntityExternalIdentifierRow).where(
                    EntityExternalIdentifierRow.identifier_type == identifier_type,
                    EntityExternalIdentifierRow.normalized_value == normalized_value,
                )
            )
            if identifier is None:
                return None
            row = session.get(GraphNodeRow, identifier.node_id)
            return self._node_from_row(row) if row and row.active else None

    def find_node_by_identifier_value(self, identifier_type: str, value: str) -> CanonicalNode | None:
        """Exact lookup also reads legacy identifier rows without lossy normalization."""
        with self._sessions() as session:
            rows = session.scalars(select(EntityExternalIdentifierRow).where(
                EntityExternalIdentifierRow.identifier_type == identifier_type,
                EntityExternalIdentifierRow.value == value,
            )).all()
            owners = {row.node_id for row in rows}
            if len(owners) > 1:
                raise ValueError("stable identifier has conflicting owners")
            row = session.get(GraphNodeRow, next(iter(owners))) if owners else None
            return self._node_from_row(row) if row and row.active else None

    def find_nodes_by_alias(
        self, normalized_alias: str, node_type: str | None = None
    ) -> list[CanonicalNode]:
        with self._sessions() as session:
            statement = (
                select(GraphNodeRow)
                .join(EntityAliasRow, EntityAliasRow.node_id == GraphNodeRow.id)
                .where(
                    EntityAliasRow.normalized_alias == normalized_alias,
                    GraphNodeRow.active.is_(True),
                )
            )
            if node_type:
                statement = statement.where(GraphNodeRow.node_type == node_type)
            return [self._node_from_row(row) for row in session.scalars(statement).all()]

    def list_nodes(self) -> list[CanonicalNode]:
        with self._sessions() as session:
            rows = session.scalars(
                select(GraphNodeRow).where(GraphNodeRow.active.is_(True)).order_by(GraphNodeRow.id)
            ).all()
            return [self._node_from_row(row) for row in rows]

    def list_edges(self) -> list[GraphEdge]:
        with self._sessions() as session:
            rows = session.scalars(
                select(GraphEdgeRow).where(GraphEdgeRow.active.is_(True)).order_by(GraphEdgeRow.id)
            ).all()
            return [self._edge_from_row(row) for row in rows]

    def get_evidence_span(self, span_id: UUID) -> EvidenceSpan | None:
        with self._sessions() as session:
            row = session.get(EvidenceSpanRow, str(span_id))
            return self._span_from_row(row) if row else None

    def get_assertion(self, assertion_id: UUID) -> Assertion | None:
        with self._sessions() as session:
            row = session.get(AssertionRow, str(assertion_id))
            return self._assertion_from_row(row) if row else None

    def add_score(self, score: ScoreRecord) -> ScoreRecord:
        with self._sessions.begin() as session:
            if not session.get(GraphNodeRow, str(score.subject_id)):
                raise ValueError(f"unknown score subject {score.subject_id}")
            if score.context_id and not session.get(GraphNodeRow, str(score.context_id)):
                raise ValueError(f"unknown score context {score.context_id}")
            for evidence_id in score.evidence_ids:
                if not session.get(EvidenceRow, str(evidence_id)):
                    raise ValueError(f"unknown score evidence {evidence_id}")
            existing = session.scalar(
                select(ScoreRecordRow).where(
                    ScoreRecordRow.input_fingerprint == score.input_fingerprint
                )
            )
            if existing:
                return self._score_from_row(existing)
            row = ScoreRecordRow(
                id=str(score.id),
                score_type=score.score_type.value,
                subject_id=str(score.subject_id),
                context_id=str(score.context_id) if score.context_id else None,
                version=score.version,
                as_of=score.as_of,
                window_start=score.window_start,
                window_end=score.window_end,
                value=score.value,
                formula=score.formula,
                components=[component.model_dump(mode="json") for component in score.components],
                evidence_ids=[str(value) for value in score.evidence_ids],
                inputs=score.inputs,
                input_fingerprint=score.input_fingerprint,
                coverage=score.coverage,
                computed_at=score.computed_at,
            )
            session.add(row)
            session.flush()
            return self._score_from_row(row)

    def get_score(self, score_id: UUID) -> ScoreRecord | None:
        with self._sessions() as session:
            row = session.get(ScoreRecordRow, str(score_id))
            return self._score_from_row(row) if row else None

    def list_scores(
        self, score_type: str | None = None, subject_id: UUID | None = None
    ) -> list[ScoreRecord]:
        with self._sessions() as session:
            statement = select(ScoreRecordRow)
            if score_type is not None:
                statement = statement.where(ScoreRecordRow.score_type == score_type)
            if subject_id is not None:
                statement = statement.where(ScoreRecordRow.subject_id == str(subject_id))
            statement = statement.order_by(ScoreRecordRow.as_of, ScoreRecordRow.id)
            return [self._score_from_row(row) for row in session.scalars(statement).all()]

    def add_normalized_document(self, document: NormalizedDocument) -> NormalizedDocument:
        with self._sessions.begin() as session:
            self._validate_provenance(session, document.provenance)
            if not session.get(DocumentVersionRow, str(document.document_version_id)):
                raise ValueError(f"unknown document version {document.document_version_id}")
            existing = session.scalar(
                select(NormalizedDocumentRow).where(
                    NormalizedDocumentRow.document_version_id == str(document.document_version_id),
                    NormalizedDocumentRow.normalizer_version == document.normalizer_version,
                )
            )
            if existing:
                if existing.content_hash != document.content_hash:
                    raise ValueError("normalized document is immutable for this normalizer version")
                return self._normalized_from_row(existing)
            row = NormalizedDocumentRow(
                id=str(document.id),
                document_version_id=str(document.document_version_id),
                normalizer_version=document.normalizer_version,
                normalized_text=document.normalized_text,
                content_hash=document.content_hash,
                provenance=document.provenance.model_dump(mode="json"),
            )
            session.add(row)
            session.flush()
            return self._normalized_from_row(row)

    def add_evidence_span(self, span: EvidenceSpan) -> EvidenceSpan:
        with self._sessions.begin() as session:
            self._validate_provenance(session, span.provenance)
            normalized = session.get(NormalizedDocumentRow, str(span.normalized_document_id))
            if normalized is None:
                raise ValueError(f"unknown normalized document {span.normalized_document_id}")
            if normalized.normalized_text[span.start_offset : span.end_offset] != span.exact_text:
                raise ValueError("evidence span does not match exact normalized text offsets")
            existing = session.get(EvidenceSpanRow, str(span.id))
            if existing:
                return self._span_from_row(existing)
            row = EvidenceSpanRow(
                id=str(span.id),
                normalized_document_id=str(span.normalized_document_id),
                start_offset=span.start_offset,
                end_offset=span.end_offset,
                exact_text=span.exact_text,
                content_hash=span.content_hash,
                provenance=span.provenance.model_dump(mode="json"),
            )
            session.add(row)
            session.flush()
            return self._span_from_row(row)

    def add_assertion(self, assertion: Assertion) -> Assertion:
        with self._sessions.begin() as session:
            self._validate_provenance(session, assertion.provenance)
            for span_id in assertion.evidence_span_ids:
                if not session.get(EvidenceSpanRow, str(span_id)):
                    raise ValueError(f"unknown evidence span {span_id}")
            existing = session.get(AssertionRow, str(assertion.id))
            if existing:
                return self._assertion_from_row(existing)
            row = AssertionRow(
                id=str(assertion.id),
                subject_id=str(assertion.subject_id),
                predicate=assertion.predicate,
                object_value=assertion.object_value,
                stance=assertion.stance,
                confidence=assertion.confidence,
                evidence_span_ids=[str(span_id) for span_id in assertion.evidence_span_ids],
                extraction_method=assertion.extraction_method.value,
                extraction_model=assertion.extraction_model,
                prompt_version=assertion.prompt_version,
                schema_version=assertion.schema_version,
                ontology_version=assertion.ontology_version,
                review_state=assertion.review_state,
                recorded_at=assertion.recorded_at,
                provenance=assertion.provenance.model_dump(mode="json"),
            )
            session.add(row)
            session.flush()
            return self._assertion_from_row(row)

    def review_assertion(self, assertion_id: UUID, review_state: str) -> Assertion:
        allowed = {"proposed", "accepted", "rejected", "superseded"}
        if review_state not in allowed:
            raise ValueError(f"review_state must be one of {sorted(allowed)}")
        with self._sessions.begin() as session:
            row = session.get(AssertionRow, str(assertion_id))
            if row is None:
                raise ValueError(f"unknown assertion {assertion_id}")
            if row.review_state == review_state:
                return self._assertion_from_row(row)
            self._archive_revision(
                session,
                "assertion",
                row.id,
                {
                    "id": row.id,
                    "subject_id": row.subject_id,
                    "predicate": row.predicate,
                    "object_value": row.object_value,
                    "stance": row.stance,
                    "confidence": row.confidence,
                    "evidence_span_ids": row.evidence_span_ids,
                    "extraction_method": row.extraction_method,
                    "extraction_model": row.extraction_model,
                    "prompt_version": row.prompt_version,
                    "schema_version": row.schema_version,
                    "ontology_version": row.ontology_version,
                    "review_state": row.review_state,
                    "recorded_at": row.recorded_at.isoformat(),
                    "provenance": row.provenance,
                },
            )
            row.review_state = review_state
            row.recorded_at = datetime.now(UTC)
            session.flush()
            return self._assertion_from_row(row)

    def list_active_assertions(self, subject_id: UUID | None = None) -> list[Assertion]:
        with self._sessions() as session:
            statement = select(AssertionRow).where(AssertionRow.review_state == "accepted")
            if subject_id is not None:
                statement = statement.where(AssertionRow.subject_id == str(subject_id))
            return [self._assertion_from_row(row) for row in session.scalars(statement).all()]

    def list_memory_assertions(self, review_state: str | None = None) -> list[Assertion]:
        with self._sessions() as session:
            statement = select(AssertionRow).where(AssertionRow.predicate == "MEMORY_OBSERVATION")
            if review_state is not None:
                statement = statement.where(AssertionRow.review_state == review_state)
            return [self._assertion_from_row(row) for row in session.scalars(statement.order_by(AssertionRow.id)).all()]

    def review_memory_assertion(self, assertion_id: UUID, state: str, reviewer: str, note: str) -> Assertion:
        """Review and graph promotion/retraction are one transaction."""
        if state not in {"accepted", "rejected", "proposed", "superseded"}:
            raise ValueError("invalid review state")
        if not reviewer.strip() or not note.strip():
            raise ValueError("reviewer and supporting review note are required")
        with self._sessions.begin() as session:
            row = session.get(AssertionRow, str(assertion_id))
            if row is None or row.predicate != "MEMORY_OBSERVATION":
                raise ValueError("unknown memory observation")
            payload = dict(row.object_value)
            context = dict(payload.get("context", {}))
            kind = payload["observation_type"]
            edge_id = str(payload.get("projected_edge_id") or uuid5(assertion_id, "reviewed-memory-edge"))
            edge = session.get(GraphEdgeRow, edge_id)
            if state == "accepted" and kind in {"relationship", "identity_link", "belief_equivalence"}:
                source = session.get(GraphNodeRow, row.subject_id)
                target = session.get(GraphNodeRow, str(payload.get("target_id")))
                if not source or not target or not source.active or not target.active:
                    raise ValueError("connection endpoints must exist and be active")
                edge_type = (EdgeType.SAME_ENTITY if kind == "identity_link" else
                             EdgeType.EQUIVALENT_TO if kind == "belief_equivalence" else EdgeType(context.get("edge_type")))
                validate_edge_endpoints(edge_type, NodeType(source.node_type), NodeType(target.node_type))
                provenance = Provenance.model_validate(row.provenance)
                if not {UUID(source.id), UUID(target.id)} <= set(provenance.entity_ids):
                    raise ValueError("connection evidence must include both endpoints")
                if edge is None:
                    # Reuse a pre-existing projection of this same source relation;
                    # human review must not double-count one observation.
                    for candidate in session.scalars(select(GraphEdgeRow).where(
                        GraphEdgeRow.edge_type == edge_type.value,
                        GraphEdgeRow.from_node_id == source.id,
                        GraphEdgeRow.to_node_id == target.id,
                    )):
                        proposed_qualifiers = dict(context.get("qualifiers", {}))
                        same_meaning = all(candidate.qualifiers.get(key) == proposed_qualifiers.get(key)
                                           for key in ("stance", "modality", "use_case"))
                        if same_meaning and set(candidate.provenance.get("evidence_ids", [])) == set(row.provenance.get("evidence_ids", [])):
                            owner = candidate.qualifiers.get("memory_assertion_id")
                            if owner and owner != row.id:
                                raise ValueError("this connection already has a memory review; review its owning observation")
                            edge = candidate
                            break
                # Promotion is explicit human review, never model confidence alone.
                if edge is None:
                    provenance_json = provenance.model_dump(mode="json")
                    edge = GraphEdgeRow(
                        id=edge_id, edge_type=edge_type.value, from_node_id=source.id, to_node_id=target.id,
                        qualifiers={**dict(context.get("qualifiers", {})), "memory_assertion_id": row.id,
                                    "source_family": payload["source_family"]["id"], "reviewed_by": reviewer},
                        valid_from=provenance.published_at, recorded_at=datetime.now(UTC),
                        provenance=provenance_json,
                        provenance_key=hashlib.sha256((json.dumps(provenance_json, sort_keys=True) + row.id).encode()).hexdigest(),
                        active=True,
                    )
                    session.add(edge)
                else:
                    edge.active = True
                    edge.recorded_at = datetime.now(UTC)
                    edge.qualifiers = {**edge.qualifiers, "memory_assertion_id": row.id, "reviewed_by": reviewer}
                payload["projected_edge_id"] = edge.id
            elif edge is not None:
                edge.active = False
            if edge is not None and edge.qualifiers.get("assertion_id"):
                projection = session.get(AssertionRow, str(edge.qualifiers["assertion_id"]))
                if projection is not None:
                    projection.review_state = state
                    projection.recorded_at = datetime.now(UTC)
            if state == "accepted" and kind in {"identity_link", "belief_equivalence"}:
                source = session.get(GraphNodeRow, row.subject_id)
                target = session.get(GraphNodeRow, str(payload.get("target_id")))
                if not source or not target or source.node_type != target.node_type or source.id == target.id:
                    raise ValueError("identity/equivalence needs distinct nodes of the same type")
                if kind == "belief_equivalence" and source.node_type != NodeType.BELIEF.value:
                    raise ValueError("belief equivalence requires two beliefs")
                if kind == "identity_link":
                    # Detect cycles before approving a redirect for future resolution.
                    redirects = {a.subject_id: str(a.object_value.get("target_id")) for a in session.scalars(
                        select(AssertionRow).where(AssertionRow.predicate == "MEMORY_OBSERVATION", AssertionRow.review_state == "accepted")
                    ) if a.object_value.get("observation_type") == "identity_link" and a.id != row.id}
                    if source.id in redirects and redirects[source.id] != target.id:
                        raise ValueError("identity already has a different reviewed canonical target")
                    cursor = target.id
                    visited = {source.id}
                    while cursor in redirects:
                        if cursor in visited:
                            raise ValueError("identity link would create a cycle")
                        visited.add(cursor)
                        cursor = redirects[cursor]
                    if cursor in visited:
                        raise ValueError("identity link would create a cycle")
            history = list(payload.get("reviews", []))
            history.append({"state": state, "reviewer": reviewer, "note": note,
                            "reviewed_at": datetime.now(UTC).isoformat()})
            payload["reviews"] = history
            row.object_value = payload
            row.review_state = state
            row.recorded_at = datetime.now(UTC)
            session.flush()
            return self._assertion_from_row(row)

    def add_merge_decision(self, decision: MergeDecision) -> MergeDecision:
        with self._sessions.begin() as session:
            self._validate_provenance(session, decision.provenance)
            for span_id in decision.evidence_span_ids:
                if not session.get(EvidenceSpanRow, str(span_id)):
                    raise ValueError(f"unknown evidence span {span_id}")
            row = MergeDecisionRow(
                id=str(decision.id),
                survivor_id=str(decision.survivor_id),
                absorbed_id=str(decision.absorbed_id),
                evidence_span_ids=[str(span_id) for span_id in decision.evidence_span_ids],
                decision=decision.decision,
                decided_by=decision.decided_by,
                decided_at=decision.decided_at,
                provenance=decision.provenance.model_dump(mode="json"),
            )
            session.add(row)
            session.flush()
            return decision

    def add_tombstone(self, record_type: str, record_id: UUID, reason: str) -> None:
        with self._sessions.begin() as session:
            session.add(
                TombstoneRow(
                    id=str(uuid4()),
                    record_type=record_type,
                    record_id=str(record_id),
                    reason=reason,
                    recorded_at=datetime.now(UTC),
                )
            )

    def add_node(self, node: CanonicalNode) -> CanonicalNode:
        with self._sessions.begin() as session:
            self._validate_provenance(session, node.provenance)
            existing = session.get(GraphNodeRow, str(node.id))
            if existing:
                if not existing.active:
                    raise ValueError("tombstoned node ids cannot be reused")
                return self._node_from_row(existing)
            row = GraphNodeRow(
                id=str(node.id),
                node_type=node.node_type.value,
                name=node.name,
                attributes=node.attributes,
                provenance=node.provenance.model_dump(mode="json"),
                created_at=datetime.now(UTC),
            )
            session.add(row)
            session.flush()
            return self._node_from_row(row)

    def get_node(self, node_id: UUID) -> CanonicalNode | None:
        with self._sessions() as session:
            row = session.get(GraphNodeRow, str(node_id))
            return self._node_from_row(row) if row and row.active else None

    def update_node(self, node: CanonicalNode) -> CanonicalNode:
        with self._sessions.begin() as session:
            self._validate_provenance(session, node.provenance)
            row = session.get(GraphNodeRow, str(node.id))
            if row is None or not row.active:
                raise ValueError(f"active graph node not found: {node.id}")
            if row.node_type != node.node_type.value:
                raise ValueError(
                    "node type is immutable; create a new node and tombstone the old one"
                )
            self._archive_revision(
                session,
                "node",
                row.id,
                {
                    "id": row.id,
                    "node_type": row.node_type,
                    "name": row.name,
                    "attributes": row.attributes,
                    "provenance": row.provenance,
                    "active": row.active,
                },
            )
            row.name = node.name
            row.attributes = node.attributes
            row.provenance = node.provenance.model_dump(mode="json")
            session.flush()
            return self._node_from_row(row)

    def add_edge(self, edge: GraphEdge) -> GraphEdge:
        edge = self._canonicalize_edge(edge)
        with self._sessions.begin() as session:
            self._validate_provenance(session, edge.provenance)
            source = session.get(GraphNodeRow, str(edge.from_node_id))
            target = session.get(GraphNodeRow, str(edge.to_node_id))
            if not source or not target or not source.active or not target.active:
                raise ValueError("edge endpoints must exist")
            validate_edge_endpoints(
                edge.edge_type, NodeType(source.node_type), NodeType(target.node_type)
            )
            provenance_key = hashlib.sha256(
                json.dumps(edge.provenance.model_dump(mode="json"), sort_keys=True).encode()
            ).hexdigest()
            row = session.scalar(
                select(GraphEdgeRow).where(
                    GraphEdgeRow.edge_type == edge.edge_type.value,
                    GraphEdgeRow.from_node_id == str(edge.from_node_id),
                    GraphEdgeRow.to_node_id == str(edge.to_node_id),
                    GraphEdgeRow.provenance_key == provenance_key,
                )
            )
            if row:
                if not row.active:
                    raise ValueError(
                        "tombstoned edge cannot be reactivated with the same provenance"
                    )
                return self._edge_from_row(row)
            row = GraphEdgeRow(
                id=str(edge.id),
                edge_type=edge.edge_type.value,
                from_node_id=str(edge.from_node_id),
                to_node_id=str(edge.to_node_id),
                qualifiers=edge.qualifiers,
                valid_from=edge.valid_from,
                valid_to=edge.valid_to,
                recorded_at=edge.recorded_at,
                provenance=edge.provenance.model_dump(mode="json"),
                provenance_key=provenance_key,
            )
            session.add(row)
            session.flush()
            return self._edge_from_row(row)

    def get_edge(self, edge_id: UUID) -> GraphEdge | None:
        with self._sessions() as session:
            row = session.get(GraphEdgeRow, str(edge_id))
            return self._edge_from_row(row) if row and row.active else None

    def update_edge(self, edge: GraphEdge) -> GraphEdge:
        edge = self._canonicalize_edge(edge)
        with self._sessions.begin() as session:
            self._validate_provenance(session, edge.provenance)
            row = session.get(GraphEdgeRow, str(edge.id))
            if row is None or not row.active:
                raise ValueError(f"active graph edge not found: {edge.id}")
            source = session.get(GraphNodeRow, str(edge.from_node_id))
            target = session.get(GraphNodeRow, str(edge.to_node_id))
            if not source or not target or not source.active or not target.active:
                raise ValueError("edge endpoints must exist")
            validate_edge_endpoints(
                edge.edge_type, NodeType(source.node_type), NodeType(target.node_type)
            )
            self._archive_revision(
                session,
                "edge",
                row.id,
                {
                    "id": row.id,
                    "edge_type": row.edge_type,
                    "from_node_id": row.from_node_id,
                    "to_node_id": row.to_node_id,
                    "qualifiers": row.qualifiers,
                    "valid_from": row.valid_from.isoformat() if row.valid_from else None,
                    "valid_to": row.valid_to.isoformat() if row.valid_to else None,
                    "recorded_at": row.recorded_at.isoformat(),
                    "provenance": row.provenance,
                    "provenance_key": row.provenance_key,
                    "active": row.active,
                },
            )
            row.edge_type = edge.edge_type.value
            row.from_node_id = str(edge.from_node_id)
            row.to_node_id = str(edge.to_node_id)
            row.qualifiers = edge.qualifiers
            row.valid_from = edge.valid_from
            row.valid_to = edge.valid_to
            row.recorded_at = edge.recorded_at
            row.provenance = edge.provenance.model_dump(mode="json")
            row.provenance_key = hashlib.sha256(
                json.dumps(edge.provenance.model_dump(mode="json"), sort_keys=True).encode()
            ).hexdigest()
            session.flush()
            return self._edge_from_row(row)

    def delete_edge(self, edge_id: UUID) -> bool:
        with self._sessions.begin() as session:
            row = session.get(GraphEdgeRow, str(edge_id))
            if row is None:
                return False
            if not row.active:
                return False
            row.active = False
            session.add(
                TombstoneRow(
                    id=str(uuid4()),
                    record_type="graph_edge",
                    record_id=row.id,
                    reason="deleted through graph repository",
                    recorded_at=datetime.now(UTC),
                )
            )
            return True

    def delete_node(self, node_id: UUID) -> bool:
        with self._sessions.begin() as session:
            row = session.get(GraphNodeRow, str(node_id))
            if row is None or not row.active:
                return False
            edges = session.scalars(
                select(GraphEdgeRow).where(
                    (GraphEdgeRow.from_node_id == str(node_id))
                    | (GraphEdgeRow.to_node_id == str(node_id)),
                    GraphEdgeRow.active.is_(True),
                )
            ).all()
            for edge in edges:
                edge.active = False
                session.add(
                    TombstoneRow(
                        id=str(uuid4()),
                        record_type="graph_edge",
                        record_id=edge.id,
                        reason=f"incident to deleted node {node_id}",
                        recorded_at=datetime.now(UTC),
                    )
                )
            row.active = False
            session.add(
                TombstoneRow(
                    id=str(uuid4()),
                    record_type="graph_node",
                    record_id=row.id,
                    reason="deleted through graph repository",
                    recorded_at=datetime.now(UTC),
                )
            )
            return True

    def retrieve_subgraph(self, seed_ids: list[UUID], max_hops: int = 2) -> dict[str, object]:
        if not seed_ids:
            return {"nodes": [], "edges": [], "evidence": []}
        if not 0 <= max_hops <= 8:
            raise ValueError("max_hops must be between 0 and 8")
        params: dict[str, object] = {"max_hops": max_hops}
        seed_selects = []
        for index, node_id in enumerate(seed_ids):
            params[f"seed_{index}"] = str(node_id)
            seed_selects.append(f"SELECT CAST(:seed_{index} AS VARCHAR(36)) AS node_id")
        query = text(
            "WITH RECURSIVE seeds(node_id) AS ("
            + " UNION ALL ".join(seed_selects)
            + "), walk(node_id, depth) AS ("
            " SELECT node_id, 0 FROM seeds"
            " UNION"
            " SELECT CASE WHEN e.from_node_id = w.node_id"
            " THEN e.to_node_id ELSE e.from_node_id END, w.depth + 1"
            " FROM walk w JOIN graph_edge e"
            " ON e.from_node_id = w.node_id OR e.to_node_id = w.node_id"
            " WHERE w.depth < :max_hops"
            ") SELECT DISTINCT node_id, depth FROM walk"
        )
        with self._sessions() as session:
            reachable = session.execute(query, params).all()
            nodes = {row.node_id for row in reachable}
            active_ids = {row.node_id for row in reachable if row.depth < max_hops}
            if max_hops == 0:
                active_ids = set()
            edges_by_id: dict[str, GraphEdgeRow] = {}
            if active_ids:
                rows = session.scalars(
                    select(GraphEdgeRow).where(
                        (GraphEdgeRow.from_node_id.in_(active_ids))
                        | (GraphEdgeRow.to_node_id.in_(active_ids)),
                        GraphEdgeRow.active.is_(True),
                    )
                ).all()
                edges_by_id = {row.id: row for row in rows}
            node_rows = session.scalars(
                select(GraphNodeRow).where(
                    GraphNodeRow.id.in_(nodes), GraphNodeRow.active.is_(True)
                )
            ).all()
            evidence_ids = {
                evidence_id
                for row in [*node_rows, *edges_by_id.values()]
                for evidence_id in row.provenance.get("evidence_ids", [])
            }
            evidence_rows = (
                session.scalars(select(EvidenceRow).where(EvidenceRow.id.in_(evidence_ids))).all()
                if evidence_ids
                else []
            )
            return {
                "nodes": [self._node_from_row(row) for row in node_rows],
                "edges": [self._edge_from_row(row) for row in edges_by_id.values()],
                "evidence": [self._evidence_from_row(row) for row in evidence_rows],
            }

    def health(self) -> dict[str, object]:
        with self._sessions() as session:
            session.execute(text("SELECT 1"))
        return {"status": "ok", "store": "sql", "checked_at": datetime.now(UTC).isoformat()}

    @staticmethod
    def _archive_revision(
        session: Session, record_type: str, record_id: str, record: dict[str, object]
    ) -> None:
        revision = (
            session.scalar(
                select(func.max(GraphRevisionRow.revision)).where(
                    GraphRevisionRow.record_type == record_type,
                    GraphRevisionRow.record_id == record_id,
                )
            )
            or 0
        )
        session.add(
            GraphRevisionRow(
                id=str(uuid4()),
                record_type=record_type,
                record_id=record_id,
                revision=revision + 1,
                record=record,
                recorded_at=datetime.now(UTC),
            )
        )

    @staticmethod
    def _canonicalize_edge(edge: GraphEdge) -> GraphEdge:
        if edge.edge_type == EdgeType.ADJACENT_TO and str(edge.to_node_id) < str(edge.from_node_id):
            return edge.model_copy(
                update={"from_node_id": edge.to_node_id, "to_node_id": edge.from_node_id}
            )
        return edge

    @staticmethod
    def _validate_provenance(session: Session, provenance: Provenance) -> None:
        for evidence_id in provenance.evidence_ids:
            if not session.get(EvidenceRow, str(evidence_id)):
                raise ValueError(f"unknown evidence {evidence_id}")

    @staticmethod
    def _source_from_row(row: SourceRow) -> Source:
        return Source(
            id=row.id,
            source_key=row.source_key,
            source_type=row.source_type,
            base_url=row.base_url,
            terms_url=row.terms_url,
            metadata=row.metadata_json or {},
        )

    @staticmethod
    def _policy_from_row(row: SourcePolicyRow) -> SourcePolicy:
        return SourcePolicy(
            id=row.id,
            source_id=row.source_id,
            terms_url=row.terms_url,
            reviewed_at=row.reviewed_at,
            policy=row.policy,
            active=row.active,
        )

    @staticmethod
    def _document_from_row(row: DocumentRow) -> Document:
        return Document(
            id=row.id,
            source_id=row.source_id,
            external_id=row.external_id,
            canonical_url=row.canonical_url,
        )

    @staticmethod
    def _version_from_row(row: DocumentVersionRow) -> DocumentVersion:
        return DocumentVersion(
            id=row.id,
            document_id=row.document_id,
            content_hash=row.content_hash,
            raw_payload=row.raw_payload,
            retrieved_at=row.retrieved_at,
            published_at=row.published_at,
            source_metadata=row.source_metadata or {},
        )

    @staticmethod
    def _normalized_from_row(row: NormalizedDocumentRow) -> NormalizedDocument:
        return NormalizedDocument(
            id=row.id,
            document_version_id=row.document_version_id,
            normalizer_version=row.normalizer_version,
            normalized_text=row.normalized_text,
            content_hash=row.content_hash,
            provenance=row.provenance,
        )

    @staticmethod
    def _span_from_row(row: EvidenceSpanRow) -> EvidenceSpan:
        return EvidenceSpan(
            id=row.id,
            normalized_document_id=row.normalized_document_id,
            start_offset=row.start_offset,
            end_offset=row.end_offset,
            exact_text=row.exact_text,
            content_hash=row.content_hash,
            provenance=row.provenance,
        )

    @staticmethod
    def _assertion_from_row(row: AssertionRow) -> Assertion:
        return Assertion(
            id=row.id,
            subject_id=row.subject_id,
            predicate=row.predicate,
            object_value=row.object_value,
            stance=row.stance,
            confidence=row.confidence,
            evidence_span_ids=tuple(row.evidence_span_ids),
            extraction_method=row.extraction_method,
            extraction_model=row.extraction_model,
            prompt_version=row.prompt_version,
            schema_version=row.schema_version,
            ontology_version=row.ontology_version,
            review_state=row.review_state,
            recorded_at=row.recorded_at,
            provenance=row.provenance,
        )

    @staticmethod
    def _alias_from_row(row: EntityAliasRow) -> EntityAlias:
        return EntityAlias(
            id=row.id,
            node_id=row.node_id,
            alias=row.alias,
            normalized_alias=row.normalized_alias,
            source_scope=row.source_scope,
            confidence=row.confidence,
            evidence_ids=tuple(row.evidence_ids),
            created_at=row.created_at,
        )

    @staticmethod
    def _external_identifier_from_row(
        row: EntityExternalIdentifierRow,
    ) -> EntityExternalIdentifier:
        return EntityExternalIdentifier(
            id=row.id,
            node_id=row.node_id,
            identifier_type=row.identifier_type,
            value=row.value,
            normalized_value=row.normalized_value,
            confidence=row.confidence,
            evidence_ids=tuple(row.evidence_ids),
            created_at=row.created_at,
        )

    @staticmethod
    def _score_from_row(row: ScoreRecordRow) -> ScoreRecord:
        return ScoreRecord(
            id=row.id,
            score_type=row.score_type,
            subject_id=row.subject_id,
            context_id=row.context_id,
            version=row.version,
            as_of=row.as_of,
            window_start=row.window_start,
            window_end=row.window_end,
            value=row.value,
            formula=row.formula,
            components=tuple(row.components),
            evidence_ids=tuple(row.evidence_ids),
            inputs=row.inputs,
            input_fingerprint=row.input_fingerprint,
            coverage=row.coverage,
            computed_at=row.computed_at,
        )

    @staticmethod
    def _evidence_from_row(row: EvidenceRow) -> Evidence:
        return Evidence(
            id=row.id,
            source_id=row.source_id,
            document_version_id=row.document_version_id,
            source_url=row.source_url,
            source_type=row.source_type,
            retrieved_at=row.retrieved_at,
            published_at=row.published_at,
            original_reference=row.original_reference,
            raw_text=row.raw_text,
            normalized_text=row.normalized_text,
            content_hash=row.content_hash,
            external_id=row.external_id,
            updated_at=row.updated_at,
            extraction_method=row.extraction_method,
            extraction_model=row.extraction_model,
            entity_ids=tuple(row.entity_ids or []),
            metadata=row.metadata_json or {},
        )

    def add_perception(self, observation: PerceptionObservation) -> PerceptionObservation:
        with self._sessions.begin() as session:
            existing = session.get(PerceptionObservationRow, str(observation.id))
            if existing:
                return self._perception_from_row(existing)
            row = PerceptionObservationRow(
                id=str(observation.id),
                subject_id=str(observation.subject_id),
                subject_type=observation.subject_type.value,
                dimension=observation.dimension.value,
                stance=observation.stance.value,
                actor_id=str(observation.actor_id) if observation.actor_id else None,
                actor_community=observation.actor_community,
                statement=observation.statement,
                evidence_ids=[str(eid) for eid in observation.evidence_ids],
                confidence=observation.confidence,
                observed_at=observation.observed_at,
                provenance=observation.provenance.model_dump(mode="json"),
                created_at=datetime.now(UTC),
            )
            session.add(row)
            session.flush()
            return self._perception_from_row(row)

    def list_perceptions(
        self,
        subject_id: UUID | None = None,
        dimension: PerceptionDimension | None = None,
        limit: int = 500,
    ) -> list[PerceptionObservation]:
        with self._sessions() as session:
            stmt = select(PerceptionObservationRow)
            if subject_id:
                stmt = stmt.where(PerceptionObservationRow.subject_id == str(subject_id))
            if dimension:
                stmt = stmt.where(PerceptionObservationRow.dimension == dimension.value)
            stmt = stmt.order_by(PerceptionObservationRow.observed_at.desc()).limit(limit)
            rows = session.scalars(stmt).all()
            return [self._perception_from_row(r) for r in rows]

    @staticmethod
    def _perception_from_row(row: PerceptionObservationRow) -> PerceptionObservation:
        return PerceptionObservation(
            id=UUID(row.id),
            subject_id=UUID(row.subject_id),
            subject_type=NodeType(row.subject_type),
            dimension=PerceptionDimension(row.dimension),
            stance=PerceptionStance(row.stance),
            statement=row.statement,
            evidence_ids=tuple(UUID(eid) for eid in row.evidence_ids),
            confidence=row.confidence,
            actor_id=UUID(row.actor_id) if row.actor_id else None,
            actor_community=row.actor_community,
            observed_at=row.observed_at,
            provenance=Provenance.model_validate(row.provenance),
        )

    @staticmethod
    def _node_from_row(row: GraphNodeRow) -> CanonicalNode:
        schema = NODE_SCHEMAS[NodeType(row.node_type)]
        return schema(
            id=row.id,
            node_type=row.node_type,
            name=row.name,
            attributes=row.attributes or {},
            provenance=row.provenance,
        )

    @staticmethod
    def _edge_from_row(row: GraphEdgeRow) -> GraphEdge:
        return GraphEdge(
            id=row.id,
            edge_type=row.edge_type,
            from_node_id=row.from_node_id,
            to_node_id=row.to_node_id,
            qualifiers=row.qualifiers or {},
            valid_from=row.valid_from,
            valid_to=row.valid_to,
            recorded_at=row.recorded_at,
            provenance=row.provenance,
        )

