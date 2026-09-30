"""Validated canonical records and ontology contracts."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID, uuid4

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, model_validator


class NodeType(StrEnum):
    PERSON = "Person"
    COMPANY = "Company"
    BELIEF = "Belief"
    MARKET = "Market"
    PRODUCT = "Product"
    CONTENT = "Content"
    EVENT = "Event"


class EdgeType(StrEnum):
    BELIEVES = "BELIEVES"
    PUBLISHED = "PUBLISHED"
    EXPRESSES = "EXPRESSES"
    INFLUENCES = "INFLUENCES"
    FOUNDED = "FOUNDED"
    WORKS_AT = "WORKS_AT"
    INVESTED_IN = "INVESTED_IN"
    ACTS_ON = "ACTS_ON"
    BUILDS = "BUILDS"
    SERVES = "SERVES"
    ADJACENT_TO = "ADJACENT_TO"
    DEPENDS_ON = "DEPENDS_ON"
    PRECEDES = "PRECEDES"
    POSSIBLY_INFLUENCED = "POSSIBLY_INFLUENCED"
    EVIDENCED_INFLUENCE = "EVIDENCED_INFLUENCE"
    AMPLIFIES = "AMPLIFIES"
    PARTICIPATED_IN = "PARTICIPATED_IN"
    PERCEIVES = "PERCEIVES"


class ExtractionMethod(StrEnum):
    SOURCE_EXPLICIT = "source_explicit"
    EXTRACTED = "extracted"
    DETERMINISTIC = "deterministic"
    ANALYST = "analyst"
    DERIVED = "derived"


class ScoreType(StrEnum):
    ACTOR_LEAD = "actor_lead"
    ACTOR_INFLUENCE = "actor_influence"
    BELIEF_VELOCITY = "belief_velocity"
    BELIEF_DIVERSITY = "belief_diversity"
    ACTION_CONVERSION = "action_conversion"
    EVIDENCE_CONFIDENCE = "evidence_confidence"


class Provenance(BaseModel):
    """Required origin and derivation details for every derived record."""

    model_config = ConfigDict(frozen=True)

    source_url: AnyHttpUrl
    source_type: str = Field(min_length=1, max_length=80)
    retrieved_at: datetime
    published_at: datetime | None = None
    original_reference: str = Field(min_length=1)
    evidence_ids: tuple[UUID, ...] = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    extraction_method: ExtractionMethod
    extraction_model: str | None = None
    entity_ids: tuple[UUID, ...] = ()

    @model_validator(mode="after")
    def model_for_extraction(self) -> Provenance:
        if self.extraction_method == ExtractionMethod.EXTRACTED and not self.extraction_model:
            raise ValueError("extracted provenance requires extraction_model")
        return self


class Source(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    source_key: str = Field(min_length=1, max_length=160)
    source_type: str = Field(min_length=1, max_length=80)
    base_url: AnyHttpUrl
    terms_url: AnyHttpUrl | None = None
    metadata: dict[str, object] = Field(default_factory=dict)


class SourcePolicy(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    source_id: UUID
    terms_url: AnyHttpUrl | None = None
    reviewed_at: datetime | None = None
    policy: dict[str, object]
    active: bool = False

    @model_validator(mode="after")
    def active_policy_has_review(self) -> SourcePolicy:
        if self.active and self.reviewed_at is None:
            raise ValueError("an active source policy requires reviewed_at")
        return self


class Document(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    source_id: UUID
    external_id: str = Field(min_length=1, max_length=500)
    canonical_url: AnyHttpUrl


class DocumentVersion(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    document_id: UUID
    content_hash: str = Field(min_length=64, max_length=64)
    raw_payload: str
    retrieved_at: datetime
    published_at: datetime | None = None
    source_metadata: dict[str, object] = Field(default_factory=dict)

    @model_validator(mode="after")
    def raw_payload_hash_matches(self) -> DocumentVersion:
        from hashlib import sha256

        if sha256(self.raw_payload.encode()).hexdigest() != self.content_hash:
            raise ValueError("content_hash must be SHA-256 of raw_payload")
        return self


class NormalizedDocument(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    document_version_id: UUID
    normalizer_version: str = Field(min_length=1, max_length=80)
    normalized_text: str
    content_hash: str = Field(min_length=64, max_length=64)
    provenance: Provenance

    @model_validator(mode="after")
    def normalized_hash_matches(self) -> NormalizedDocument:
        from hashlib import sha256

        if sha256(self.normalized_text.encode()).hexdigest() != self.content_hash:
            raise ValueError("content_hash must be SHA-256 of normalized_text")
        return self


class Evidence(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    source_id: UUID
    document_version_id: UUID | None = None
    source_url: AnyHttpUrl
    source_type: str = Field(min_length=1, max_length=80)
    retrieved_at: datetime
    published_at: datetime | None = None
    original_reference: str = Field(min_length=1)
    raw_text: str = Field(min_length=1)
    normalized_text: str | None = None
    content_hash: str = Field(min_length=64, max_length=64)
    external_id: str | None = Field(default=None, max_length=500)
    updated_at: datetime | None = None
    extraction_method: ExtractionMethod = ExtractionMethod.DETERMINISTIC
    extraction_model: str | None = None
    entity_ids: tuple[UUID, ...] = ()
    metadata: dict[str, object] = Field(default_factory=dict)


class EvidenceSpan(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    normalized_document_id: UUID
    start_offset: int = Field(ge=0)
    end_offset: int = Field(gt=0)
    exact_text: str = Field(min_length=1)
    content_hash: str = Field(min_length=64, max_length=64)
    provenance: Provenance

    @model_validator(mode="after")
    def span_length_matches(self) -> EvidenceSpan:
        from hashlib import sha256

        if self.end_offset <= self.start_offset:
            raise ValueError("end_offset must be greater than start_offset")
        if self.end_offset - self.start_offset != len(self.exact_text):
            raise ValueError("span offsets must match exact_text length")
        if sha256(self.exact_text.encode()).hexdigest() != self.content_hash:
            raise ValueError("content_hash must be SHA-256 of exact_text")
        return self


class CanonicalNode(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    name: str = Field(min_length=1, max_length=500)
    attributes: dict[str, object] = Field(default_factory=dict)
    provenance: Provenance

    @model_validator(mode="after")
    def provenance_mentions_self(self) -> CanonicalNode:
        if self.id not in self.provenance.entity_ids:
            raise ValueError("node provenance.entity_ids must include the node id")
        return self


class Person(CanonicalNode):
    node_type: Literal[NodeType.PERSON] = NodeType.PERSON


class Company(CanonicalNode):
    node_type: Literal[NodeType.COMPANY] = NodeType.COMPANY


class Belief(CanonicalNode):
    node_type: Literal[NodeType.BELIEF] = NodeType.BELIEF


class Market(CanonicalNode):
    node_type: Literal[NodeType.MARKET] = NodeType.MARKET


class Product(CanonicalNode):
    node_type: Literal[NodeType.PRODUCT] = NodeType.PRODUCT


class Content(CanonicalNode):
    node_type: Literal[NodeType.CONTENT] = NodeType.CONTENT


class Event(CanonicalNode):
    node_type: Literal[NodeType.EVENT] = NodeType.EVENT


NodeSchema = Annotated[
    Person | Company | Belief | Market | Product | Content | Event,
    Field(discriminator="node_type"),
]


class GraphEdge(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    edge_type: EdgeType
    from_node_id: UUID
    to_node_id: UUID
    qualifiers: dict[str, object] = Field(default_factory=dict)
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    recorded_at: datetime
    provenance: Provenance

    @model_validator(mode="after")
    def valid_interval(self) -> GraphEdge:
        if self.valid_from and self.valid_to and self.valid_to < self.valid_from:
            raise ValueError("valid_to cannot precede valid_from")
        if not {self.from_node_id, self.to_node_id} <= set(self.provenance.entity_ids):
            raise ValueError("edge provenance.entity_ids must include both endpoints")
        return self


class Assertion(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    subject_id: UUID
    predicate: str = Field(min_length=1, max_length=80)
    object_value: dict[str, object]
    stance: Literal["supports", "opposes", "qualifies", "mentions"] | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_span_ids: tuple[UUID, ...] = Field(min_length=1)
    extraction_method: ExtractionMethod
    extraction_model: str | None = None
    prompt_version: str | None = None
    schema_version: str = "phase3-v1"
    ontology_version: str = Field(min_length=1)
    review_state: Literal["proposed", "accepted", "rejected", "superseded"] = "proposed"
    recorded_at: datetime
    provenance: Provenance

    @model_validator(mode="after")
    def provenance_mentions_subject(self) -> Assertion:
        if self.subject_id not in self.provenance.entity_ids:
            raise ValueError("assertion provenance.entity_ids must include subject_id")
        if self.extraction_method == ExtractionMethod.EXTRACTED:
            if not self.extraction_model or not self.prompt_version:
                raise ValueError(
                    "LLM-extracted assertions require extraction_model and prompt_version"
                )
        return self


class ScoreComponent(BaseModel):
    """One inspectable term in a deterministic score."""

    model_config = ConfigDict(frozen=True)

    name: str = Field(min_length=1, max_length=100)
    value: float = Field(ge=0.0, le=100.0)
    weight: float = Field(ge=0.0, le=1.0)
    contribution: float = Field(ge=0.0, le=100.0)
    numerator: float | None = None
    denominator: float | None = None
    details: dict[str, object] = Field(default_factory=dict)
    evidence_ids: tuple[UUID, ...] = ()

    @model_validator(mode="after")
    def contribution_matches_weighted_value(self) -> ScoreComponent:
        if abs(self.contribution - self.value * self.weight) > 0.011:
            raise ValueError("component contribution must equal value * weight")
        return self


class ScoreRecord(BaseModel):
    """Versioned, replayable result produced without model judgment."""

    model_config = ConfigDict(frozen=True)

    id: UUID = Field(default_factory=uuid4)
    score_type: ScoreType
    subject_id: UUID
    context_id: UUID | None = None
    version: str = Field(min_length=1, max_length=80)
    as_of: datetime
    window_start: datetime | None = None
    window_end: datetime | None = None
    value: float = Field(ge=0.0, le=100.0)
    formula: str = Field(min_length=1)
    components: tuple[ScoreComponent, ...] = Field(min_length=1)
    evidence_ids: tuple[UUID, ...] = ()
    inputs: dict[str, object] = Field(default_factory=dict)
    input_fingerprint: str = Field(min_length=64, max_length=64)
    coverage: dict[str, object] = Field(default_factory=dict)
    computed_at: datetime

    @model_validator(mode="after")
    def components_reconcile(self) -> ScoreRecord:
        if abs(sum(component.weight for component in self.components) - 1.0) > 0.001:
            raise ValueError("score component weights must sum to 1")
        if abs(sum(component.contribution for component in self.components) - self.value) > 0.02:
            raise ValueError("score value must equal the sum of component contributions")
        if self.window_start and self.window_end and self.window_end < self.window_start:
            raise ValueError("score window_end cannot precede window_start")
        return self


class EntityAlias(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    node_id: UUID
    alias: str = Field(min_length=1, max_length=500)
    normalized_alias: str = Field(min_length=1, max_length=500)
    source_scope: str = Field(min_length=1, max_length=80)
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_ids: tuple[UUID, ...] = Field(min_length=1)
    created_at: datetime


class EntityExternalIdentifier(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    node_id: UUID
    identifier_type: str = Field(min_length=1, max_length=100)
    value: str = Field(min_length=1, max_length=500)
    normalized_value: str = Field(min_length=1, max_length=500)
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_ids: tuple[UUID, ...] = Field(min_length=1)
    created_at: datetime


class MergeDecision(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    survivor_id: UUID
    absorbed_id: UUID
    evidence_span_ids: tuple[UUID, ...] = Field(min_length=1)
    decision: Literal["accepted", "rejected", "reversed"]
    decided_by: str = Field(min_length=1)
    decided_at: datetime
    provenance: Provenance

    @model_validator(mode="after")
    def provenance_mentions_both_entities(self) -> MergeDecision:
        if not {self.survivor_id, self.absorbed_id} <= set(self.provenance.entity_ids):
            raise ValueError("merge provenance.entity_ids must include survivor and absorbed ids")
        return self


class PerceptionDimension(StrEnum):
    PAIN = "PAIN"
    PRAISE = "PRAISE"
    FEATURE_REQUEST = "FEATURE_REQUEST"
    SWITCHING_INTENT = "SWITCHING_INTENT"
    PRICE_SENSITIVITY = "PRICE_SENSITIVITY"
    TRUST = "TRUST"
    PERFORMANCE = "PERFORMANCE"
    USABILITY = "USABILITY"
    USE_CASE = "USE_CASE"
    OTHER = "OTHER"


class PerceptionStance(StrEnum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    MIXED = "mixed"
    NEUTRAL = "neutral"


class PerceptionObservation(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    subject_id: UUID  # product, company, or market
    subject_type: NodeType
    dimension: PerceptionDimension
    stance: PerceptionStance
    statement: str = Field(min_length=1)
    evidence_ids: tuple[UUID, ...] = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    actor_id: UUID | None = None
    actor_community: str | None = None
    observed_at: datetime
    provenance: Provenance


# Endpoint rules from ONTOLOGY.md. INFLUENCES is intentionally permissive but
# still constrained to the documented participant and proposition types.
EDGE_ENDPOINTS: dict[EdgeType, set[tuple[NodeType, NodeType]]] = {
    EdgeType.BELIEVES: {(NodeType.PERSON, NodeType.BELIEF)},
    EdgeType.PUBLISHED: {
        (NodeType.PERSON, NodeType.CONTENT),
        (NodeType.COMPANY, NodeType.CONTENT),
    },
    EdgeType.EXPRESSES: {(NodeType.CONTENT, NodeType.BELIEF)},
    EdgeType.INFLUENCES: {
        (a, b)
        for a in (NodeType.PERSON, NodeType.CONTENT, NodeType.BELIEF)
        for b in (NodeType.PERSON, NodeType.BELIEF, NodeType.COMPANY, NodeType.EVENT)
    },
    EdgeType.POSSIBLY_INFLUENCED: {
        (a, b)
        for a in (NodeType.PERSON, NodeType.CONTENT, NodeType.BELIEF)
        for b in (NodeType.PERSON, NodeType.BELIEF, NodeType.COMPANY, NodeType.EVENT)
    },
    EdgeType.EVIDENCED_INFLUENCE: {
        (a, b)
        for a in (NodeType.PERSON, NodeType.CONTENT, NodeType.BELIEF)
        for b in (NodeType.PERSON, NodeType.BELIEF, NodeType.COMPANY, NodeType.EVENT)
    },
    EdgeType.FOUNDED: {(NodeType.PERSON, NodeType.COMPANY)},
    EdgeType.WORKS_AT: {(NodeType.PERSON, NodeType.COMPANY)},
    EdgeType.INVESTED_IN: {
        (NodeType.PERSON, NodeType.COMPANY),
        (NodeType.PERSON, NodeType.PRODUCT),
        (NodeType.COMPANY, NodeType.COMPANY),
        (NodeType.COMPANY, NodeType.PRODUCT),
    },
    EdgeType.ACTS_ON: {(NodeType.COMPANY, NodeType.BELIEF)},
    EdgeType.BUILDS: {(NodeType.COMPANY, NodeType.PRODUCT)},
    EdgeType.SERVES: {
        (NodeType.PRODUCT, NodeType.MARKET),
        (NodeType.COMPANY, NodeType.MARKET),
    },
    EdgeType.ADJACENT_TO: {(NodeType.MARKET, NodeType.MARKET)},
    EdgeType.DEPENDS_ON: {
        (a, b)
        for a in (NodeType.PRODUCT, NodeType.COMPANY, NodeType.MARKET)
        for b in (NodeType.PRODUCT, NodeType.COMPANY, NodeType.MARKET)
    },
    EdgeType.PRECEDES: {
        (a, b)
        for a in (NodeType.BELIEF, NodeType.CONTENT, NodeType.EVENT)
        for b in (NodeType.BELIEF, NodeType.CONTENT, NodeType.EVENT)
    },
    EdgeType.AMPLIFIES: {
        (a, b)
        for a in (NodeType.PERSON, NodeType.COMPANY, NodeType.CONTENT)
        for b in (NodeType.CONTENT, NodeType.BELIEF)
    },
    EdgeType.PARTICIPATED_IN: {
        (a, NodeType.EVENT)
        for a in (NodeType.PERSON, NodeType.COMPANY, NodeType.PRODUCT, NodeType.MARKET)
    },
    EdgeType.PERCEIVES: {
        (a, b)
        for a in (NodeType.PERSON, NodeType.CONTENT)
        for b in (NodeType.PRODUCT, NodeType.COMPANY, NodeType.MARKET)
    },
}


def validate_edge_endpoints(
    edge_type: EdgeType, source_type: NodeType, target_type: NodeType
) -> None:
    if (source_type, target_type) not in EDGE_ENDPOINTS[edge_type]:
        raise ValueError(
            f"{edge_type.value} cannot connect {source_type.value} to {target_type.value}"
        )
