"""Question-scoped graph retrieval; ranking and evidence packets are later phases."""

from uuid import UUID

from memesis.graph.repository import GraphRepository


class RetrievalService:
    def __init__(self, graph: GraphRepository):
        self.graph = graph

    def subgraph(self, seed_ids: list[UUID], *, hops: int = 2) -> dict[str, object]:
        return self.graph.retrieve_subgraph(seed_ids, max_hops=hops)
