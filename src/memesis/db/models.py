"""Relational system-of-record tables for the first graph foundation."""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class InvestigationRow(Base):
    __tablename__ = "investigation"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    config_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    state_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    revision: Mapped[int] = mapped_column(default=1)
    enabled: Mapped[bool] = mapped_column(default=False, index=True)
    next_due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    running_run_id: Mapped[str | None] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class InvestigationRunRow(Base):
    __tablename__ = "investigation_run"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    investigation_id: Mapped[str] = mapped_column(ForeignKey("investigation.id"), index=True)
    revision: Mapped[int] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    receipt_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class InvestigationSnapshotRow(Base):
    __tablename__ = "investigation_snapshot"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    investigation_id: Mapped[str] = mapped_column(ForeignKey("investigation.id"), index=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("investigation_run.id"))
    fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PatternReviewRow(Base):
    __tablename__ = "pattern_review"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    investigation_id: Mapped[str] = mapped_column(ForeignKey("investigation.id"), index=True)
    pattern_id: Mapped[str] = mapped_column(String(64), index=True)
    state: Mapped[str] = mapped_column(String(20), nullable=False)
    reviewer: Mapped[str] = mapped_column(String(200), nullable=False)
    note: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class WorkerLeaseRow(Base):
    __tablename__ = "worker_lease"
    name: Mapped[str] = mapped_column(String(80), primary_key=True)
    owner: Mapped[str] = mapped_column(String(36), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    heartbeat_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SourceRow(Base):
    __tablename__ = "source"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    source_key: Mapped[str] = mapped_column(String(160), unique=True, nullable=False)
    source_type: Mapped[str] = mapped_column(String(80), nullable=False)
    base_url: Mapped[str] = mapped_column(Text, nullable=False)
    terms_url: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)


class SourcePolicyRow(Base):
    __tablename__ = "source_policy"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("source.id"), nullable=False, index=True)
    terms_url: Mapped[str | None] = mapped_column(Text)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    policy: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    active: Mapped[bool] = mapped_column(default=False, nullable=False)


class DocumentRow(Base):
    __tablename__ = "document"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("source.id"), nullable=False)
    external_id: Mapped[str] = mapped_column(String(500), nullable=False)
    canonical_url: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (UniqueConstraint("source_id", "external_id"),)


class DocumentVersionRow(Base):
    __tablename__ = "document_version"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("document.id"), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    raw_payload: Mapped[str] = mapped_column(Text, nullable=False)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    __table_args__ = (UniqueConstraint("document_id", "content_hash"),)


class NormalizedDocumentRow(Base):
    __tablename__ = "normalized_document"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    document_version_id: Mapped[str] = mapped_column(
        ForeignKey("document_version.id"), nullable=False
    )
    normalizer_version: Mapped[str] = mapped_column(String(80), nullable=False)
    normalized_text: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    provenance: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    __table_args__ = (UniqueConstraint("document_version_id", "normalizer_version"),)


class EvidenceSpanRow(Base):
    __tablename__ = "evidence_span"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    normalized_document_id: Mapped[str] = mapped_column(
        ForeignKey("normalized_document.id"), nullable=False
    )
    start_offset: Mapped[int] = mapped_column(nullable=False)
    end_offset: Mapped[int] = mapped_column(nullable=False)
    exact_text: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    provenance: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class AssertionRow(Base):
    __tablename__ = "assertion"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    subject_id: Mapped[str] = mapped_column(String(36), nullable=False)
    predicate: Mapped[str] = mapped_column(String(80), nullable=False)
    object_value: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    stance: Mapped[str | None] = mapped_column(String(40))
    confidence: Mapped[float] = mapped_column(nullable=False)
    evidence_span_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    extraction_method: Mapped[str] = mapped_column(String(40), nullable=False)
    extraction_model: Mapped[str | None] = mapped_column(String(120))
    prompt_version: Mapped[str | None] = mapped_column(String(120))
    schema_version: Mapped[str] = mapped_column(String(80), nullable=False, default="phase3-v1")
    ontology_version: Mapped[str] = mapped_column(String(80), nullable=False)
    review_state: Mapped[str] = mapped_column(String(40), nullable=False, default="proposed")
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    provenance: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class MergeDecisionRow(Base):
    __tablename__ = "merge_decision"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    survivor_id: Mapped[str] = mapped_column(String(36), nullable=False)
    absorbed_id: Mapped[str] = mapped_column(String(36), nullable=False)
    evidence_span_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    decision: Mapped[str] = mapped_column(String(40), nullable=False)
    decided_by: Mapped[str] = mapped_column(String(160), nullable=False)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    provenance: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class EntityAliasRow(Base):
    __tablename__ = "entity_alias"
    __table_args__ = (UniqueConstraint("node_id", "normalized_alias", "source_scope"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    node_id: Mapped[str] = mapped_column(ForeignKey("graph_node.id"), nullable=False, index=True)
    alias: Mapped[str] = mapped_column(String(500), nullable=False)
    normalized_alias: Mapped[str] = mapped_column(String(500), nullable=False, index=True)
    source_scope: Mapped[str] = mapped_column(String(80), nullable=False)
    confidence: Mapped[float] = mapped_column(nullable=False)
    evidence_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class EntityExternalIdentifierRow(Base):
    __tablename__ = "entity_external_identifier"
    __table_args__ = (UniqueConstraint("identifier_type", "normalized_value"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    node_id: Mapped[str] = mapped_column(ForeignKey("graph_node.id"), nullable=False, index=True)
    identifier_type: Mapped[str] = mapped_column(String(100), nullable=False)
    value: Mapped[str] = mapped_column(String(500), nullable=False)
    normalized_value: Mapped[str] = mapped_column(String(500), nullable=False, index=True)
    confidence: Mapped[float] = mapped_column(nullable=False)
    evidence_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ExtractionCacheRow(Base):
    __tablename__ = "extraction_cache"

    cache_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    evidence_id: Mapped[str] = mapped_column(ForeignKey("evidence.id"), nullable=False, index=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    extractor_version: Mapped[str] = mapped_column(String(80), nullable=False)
    prompt_version: Mapped[str | None] = mapped_column(String(120))
    schema_version: Mapped[str] = mapped_column(String(80), nullable=False)
    model: Mapped[str | None] = mapped_column(String(120))
    result_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    input_tokens: Mapped[int] = mapped_column(nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(nullable=False, default=0)
    llm_calls: Mapped[int] = mapped_column(nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class EvidenceGraphProjectionRow(Base):
    __tablename__ = "evidence_graph_projection"
    __table_args__ = (UniqueConstraint("evidence_id", "cache_key"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    evidence_id: Mapped[str] = mapped_column(ForeignKey("evidence.id"), nullable=False, index=True)
    cache_key: Mapped[str] = mapped_column(
        ForeignKey("extraction_cache.cache_key"), nullable=False, index=True
    )
    projected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class TombstoneRow(Base):
    __tablename__ = "tombstone"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    record_type: Mapped[str] = mapped_column(String(40), nullable=False)
    record_id: Mapped[str] = mapped_column(String(36), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class EvidenceRow(Base):
    __tablename__ = "evidence"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("source.id"), nullable=False)
    document_version_id: Mapped[str | None] = mapped_column(ForeignKey("document_version.id"))
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    source_type: Mapped[str] = mapped_column(String(80), nullable=False)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    original_reference: Mapped[str] = mapped_column(Text, nullable=False)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_text: Mapped[str | None] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    external_id: Mapped[str | None] = mapped_column(String(500))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    extraction_method: Mapped[str] = mapped_column(
        String(40), nullable=False, default="deterministic"
    )
    extraction_model: Mapped[str | None] = mapped_column(String(120))
    entity_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    metadata_json: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)


class CollectionRunRow(Base):
    __tablename__ = "collection_run"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("source.id"), nullable=False, index=True)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    errors: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)


class CollectionCursorRow(Base):
    __tablename__ = "collection_cursor"
    __table_args__ = (UniqueConstraint("source_id", "boundary_key"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("source.id"), nullable=False)
    boundary_key: Mapped[str] = mapped_column(String(512), nullable=False)
    cursor: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON, nullable=False, default=dict
    )


class FetchCacheRow(Base):
    __tablename__ = "fetch_cache"

    cache_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    status_code: Mapped[int] = mapped_column(nullable=False)
    response_body: Mapped[str] = mapped_column(Text, nullable=False)
    response_headers: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class GraphNodeRow(Base):
    __tablename__ = "graph_node"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    node_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    attributes: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    provenance: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    active: Mapped[bool] = mapped_column(default=True, nullable=False)


class GraphEdgeRow(Base):
    __tablename__ = "graph_edge"
    __table_args__ = (
        UniqueConstraint("edge_type", "from_node_id", "to_node_id", "provenance_key"),
        Index("ix_graph_edge_from", "from_node_id"),
        Index("ix_graph_edge_to", "to_node_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    edge_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    from_node_id: Mapped[str] = mapped_column(ForeignKey("graph_node.id"), nullable=False)
    to_node_id: Mapped[str] = mapped_column(ForeignKey("graph_node.id"), nullable=False)
    qualifiers: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    provenance: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    provenance_key: Mapped[str] = mapped_column(String(64), nullable=False)
    active: Mapped[bool] = mapped_column(default=True, nullable=False)


class GraphRevisionRow(Base):
    __tablename__ = "graph_revision"
    __table_args__ = (UniqueConstraint("record_type", "record_id", "revision"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    record_type: Mapped[str] = mapped_column(String(20), nullable=False)
    record_id: Mapped[str] = mapped_column(String(36), nullable=False)
    revision: Mapped[int] = mapped_column(nullable=False)
    record: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ScoreRecordRow(Base):
    __tablename__ = "score_record"
    __table_args__ = (
        UniqueConstraint("input_fingerprint"),
        Index("ix_score_subject_type", "subject_id", "score_type"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    score_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    subject_id: Mapped[str] = mapped_column(ForeignKey("graph_node.id"), nullable=False)
    context_id: Mapped[str | None] = mapped_column(ForeignKey("graph_node.id"))
    version: Mapped[str] = mapped_column(String(80), nullable=False)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    window_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    value: Mapped[float] = mapped_column(nullable=False)
    formula: Mapped[str] = mapped_column(Text, nullable=False)
    components: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    evidence_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    inputs: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    input_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    coverage: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class DecisionCacheRow(Base):
    __tablename__ = "decision_cache"

    cache_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    decision_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    context_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    version: Mapped[str] = mapped_column(String(80), nullable=False)
    decision: Mapped[str] = mapped_column(String(80), nullable=False)
    probability: Mapped[float] = mapped_column(nullable=False)
    result_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ReasoningRunRow(Base):
    __tablename__ = "reasoning_run"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    intent_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    packet_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    deep_reasoning_required: Mapped[bool] = mapped_column(nullable=False, default=False)
    model: Mapped[str | None] = mapped_column(String(120))
    answer_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    metrics_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PerceptionObservationRow(Base):
    __tablename__ = "perception_observation"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    subject_id: Mapped[str] = mapped_column(ForeignKey("graph_node.id"), nullable=False, index=True)
    subject_type: Mapped[str] = mapped_column(String(32), nullable=False)
    dimension: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    stance: Mapped[str] = mapped_column(String(20), nullable=False)
    actor_id: Mapped[str | None] = mapped_column(ForeignKey("graph_node.id"))
    actor_community: Mapped[str | None] = mapped_column(String(100))
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    confidence: Mapped[float] = mapped_column(nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    provenance: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


