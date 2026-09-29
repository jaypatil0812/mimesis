"""Small domain service for evidence-backed node and edge creation."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from memesis.domain.schemas import (
    Belief,
    CanonicalNode,
    Company,
    Content,
    EdgeType,
    Event,
    ExtractionMethod,
    GraphEdge,
    Market,
    NodeType,
    Person,
    Product,
    Provenance,
)
from memesis.graph.repository import GraphRepository

NODE_SCHEMAS: dict[NodeType, type[CanonicalNode]] = {
    NodeType.PERSON: Person,
    NodeType.COMPANY: Company,
    NodeType.BELIEF: Belief,
    NodeType.MARKET: Market,
    NodeType.PRODUCT: Product,
    NodeType.CONTENT: Content,
    NodeType.EVENT: Event,
}


class KnowledgeService:
    def __init__(self, graph: GraphRepository):
        self.graph = graph

    def create_node(
        self,
        node_type: NodeType,
        name: str,
        evidence_id: UUID,
        *,
        confidence: float = 1.0,
        extraction_method: ExtractionMethod = ExtractionMethod.SOURCE_EXPLICIT,
        extraction_model: str | None = None,
        attributes: dict[str, object] | None = None,
    ) -> CanonicalNode:
        evidence = self.graph.get_evidence(evidence_id)
        if evidence is None:
            raise ValueError(f"unknown evidence {evidence_id}")
        node_id = uuid4()
        node = NODE_SCHEMAS[node_type](
            id=node_id,
            name=name,
            attributes=attributes or {},
            provenance=Provenance(
                source_url=evidence.source_url,
                source_type=evidence.source_type,
                retrieved_at=evidence.retrieved_at,
                published_at=evidence.published_at,
                original_reference=evidence.original_reference,
                evidence_ids=(evidence.id,),
                confidence=confidence,
                extraction_method=extraction_method,
                extraction_model=extraction_model,
                entity_ids=(node_id,),
            ),
        )
        return self.graph.add_node(node)

    def publish(self, person_id: UUID, content_id: UUID, evidence_id: UUID) -> GraphEdge:
        return self._assert(EdgeType.PUBLISHED, person_id, content_id, evidence_id)

    def express(self, content_id: UUID, belief_id: UUID, evidence_id: UUID) -> GraphEdge:
        return self._assert(EdgeType.EXPRESSES, content_id, belief_id, evidence_id)

    def _assert(
        self, edge_type: EdgeType, from_id: UUID, to_id: UUID, evidence_id: UUID
    ) -> GraphEdge:
        evidence = self.graph.get_evidence(evidence_id)
        if evidence is None:
            raise ValueError(f"unknown evidence {evidence_id}")
        return self.graph.add_edge(
            GraphEdge(
                edge_type=edge_type,
                from_node_id=from_id,
                to_node_id=to_id,
                recorded_at=datetime.now(UTC),
                provenance=Provenance(
                    source_url=evidence.source_url,
                    source_type=evidence.source_type,
                    retrieved_at=evidence.retrieved_at,
                    published_at=evidence.published_at,
                    original_reference=evidence.original_reference,
                    evidence_ids=(evidence.id,),
                    confidence=1.0,
                    extraction_method=ExtractionMethod.SOURCE_EXPLICIT,
                    entity_ids=(from_id, to_id),
                ),
            )
        )
