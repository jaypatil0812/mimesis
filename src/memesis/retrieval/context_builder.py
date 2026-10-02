"""ContextBuilder: builds the minimum sufficient evidence-backed subgraph."""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from memesis.domain.schemas import CanonicalNode, EdgeType, Evidence, GraphEdge, NodeType, ScoreRecord
from memesis.graph.repository import GraphRepository
from memesis.reasoning.decision_engine import DecisionEngine, DecisionType
from memesis.reasoning.planner import QueryPlan
from memesis.retrieval.scope import QueryScope, ScopedGraphRepository, utc
from memesis.retrieval.relevance import overlap


class MinimumSufficientSubgraph(BaseModel):
    nodes: list[CanonicalNode]
    edges: list[GraphEdge]
    evidence: list[Evidence]
    nodes_considered: int
    nodes_retained: int
    evidence_considered: int
    evidence_retained: int
    ranking_breakdown: dict[str, float] = Field(default_factory=dict)
    limits_applied: dict[str, int] = Field(default_factory=dict)
    query_scope: dict[str, Any] = Field(default_factory=dict)
    coverage: dict[str, Any] = Field(default_factory=dict)
    evidence_membership: dict[str, str] = Field(default_factory=dict)
    memory_observations: list[dict[str, Any]] = Field(default_factory=list)
    perception_observations: list[dict[str, Any]] = Field(default_factory=list)

    def node_ids(self) -> set[UUID]:
        return {node.id for node in self.nodes}

    def edge_ids(self) -> set[UUID]:
        return {edge.id for edge in self.edges}

    def evidence_ids(self) -> set[UUID]:
        return {ev.id for ev in self.evidence}


class ContextBuilder:
    """Retrieves and ranks the smallest evidence-backed subgraph sufficient for a question."""

    def __init__(self, repository: GraphRepository, decision_engine: DecisionEngine) -> None:
        self.repository = repository
        self.decision_engine = decision_engine

    def build_context(
        self,
        plan: QueryPlan,
        scores: list[ScoreRecord] | None = None,
        as_of: datetime | None = None,
    ) -> MinimumSufficientSubgraph:
        as_of = utc(as_of or datetime.now(UTC))
        scores = scores or []
        cutoff_time = as_of - timedelta(days=plan.time_filter_days) if plan.time_filter_days else None
        view = self.repository if isinstance(self.repository, ScopedGraphRepository) else ScopedGraphRepository(
            self.repository, QueryScope(as_of=as_of, start_at=cutoff_time)
        )
        all_nodes = view.list_nodes()
        all_edges = view.list_edges()
        all_evidence = view.list_evidence()
        scoped_node_ids = {node.id for node in all_nodes}
        scoped_evidence_ids = {ev.id for ev in all_evidence}
        scores_by_subject: dict[UUID, list[ScoreRecord]] = defaultdict(list)
        for score in scores:
            if (score.subject_id in scoped_node_ids and utc(score.as_of) <= as_of
                    and set(score.evidence_ids) <= scoped_evidence_ids):
                scores_by_subject[score.subject_id].append(score)
        # Step 2: Seed nodes matching query entities and keywords
        query_text = plan.intent.raw_query.lower()
        seed_nodes: list[CanonicalNode] = []
        investigation = plan.retrieval_strategy == "investigation_graph"
        for node in all_nodes:
            name_lower = node.name.lower()
            if investigation or any(e.lower() in name_lower for e in plan.intent.entities):
                seed_nodes.append(node)
            elif overlap(query_text, name_lower) > 0:
                seed_nodes.append(node)

        # If no seeds found, use all nodes matching target node types
        if not seed_nodes:
            target_types = {t.value for t in plan.target_node_types}
            seed_nodes = [n for n in all_nodes if n.node_type.value in target_types]

        # Step 3: Expand subgraph according to plan
        seed_ids = {n.id for n in seed_nodes}
        allowed_edge_types = {e.value for e in plan.target_edge_types}

        candidate_nodes: dict[UUID, CanonicalNode] = {n.id: n for n in seed_nodes}
        candidate_edges: dict[UUID, GraphEdge] = {}

        current_hop_ids = set(seed_ids)
        for hop in range(plan.max_hops):
            next_hop_ids: set[UUID] = set()
            for edge in all_edges:
                if edge.edge_type.value not in allowed_edge_types:
                    continue
                if edge.from_node_id in current_hop_ids or edge.to_node_id in current_hop_ids:
                    candidate_edges[edge.id] = edge
                    next_hop_ids.add(edge.from_node_id)
                    next_hop_ids.add(edge.to_node_id)
            for node in all_nodes:
                if node.id in next_hop_ids and node.id not in candidate_nodes:
                    candidate_nodes[node.id] = node
            current_hop_ids = next_hop_ids

        nodes_considered = len(candidate_nodes)

        # The market boundary already selected a bounded web of supported paths.
        # Keep bridging relations and connected hypotheses, even without lexical matches.
        if view.scope.market_id is not None:
            candidate_nodes = {node.id: node for node in all_nodes}
            candidate_edges = {edge.id: edge for edge in all_edges}
            seed_ids.add(view.scope.market_id)
            nodes_considered = len(candidate_nodes)

        # Step 4: Apply Jev-style cheap relevance filtering
        filtered_nodes: dict[UUID, CanonicalNode] = {}
        for nid, node in candidate_nodes.items():
            if investigation:
                # Scope and typed paths already select these nodes. Semantic
                # relevance calls cannot prune investigation seeds and would
                # add one provider request per node without changing selection.
                filtered_nodes[nid] = node
                continue
            # Check relevance
            ctx = {
                "id": str(nid),
                "query": query_text,
                "node_name": node.name,
                "node_type": node.node_type.value,
                "text": node.name,
                "references": [str(nid)],
            }
            rel_dec = self.decision_engine.evaluate(DecisionType.RELEVANCE, ctx)
            if rel_dec.decision in {"RELEVANT", "UNCERTAIN"} or node.id in seed_ids or view.scope.market_id is not None:
                filtered_nodes[nid] = node

        # Step 5: Rank nodes within their type
        node_degrees = Counter()
        for edge in candidate_edges.values():
            node_degrees[edge.from_node_id] += 1
            node_degrees[edge.to_node_id] += 1

        node_scores: dict[UUID, float] = {}
        for nid, node in filtered_nodes.items():
            score = 0.0
            if investigation:
                timestamp = node.provenance.published_at or node.provenance.retrieved_at
                age_days = max((as_of - utc(timestamp)).total_seconds() / 86400, 0)
                score += 30 / (1 + age_days)
                if set(node.provenance.evidence_ids) & set(view.scope.evidence_seeds or ()):
                    score += 30
            # Relevance boost
            if any(e.lower() in node.name.lower() for e in plan.intent.entities):
                score += 40.0
            elif not investigation:
                score += 25.0 * overlap(query_text, node.name)

            # Degree / connectivity boost
            score += min(node_degrees[nid] * 5.0, 30.0)

            # Memesis score boost if available
            sub_scores = scores_by_subject.get(nid, [])
            if sub_scores:
                avg_val = sum(s.value for s in sub_scores) / len(sub_scores)
                score += min(avg_val * 0.3, 30.0)

            node_scores[nid] = score

        # Step 6: Apply per-type hard limits
        nodes_by_type: dict[str, list[CanonicalNode]] = defaultdict(list)
        for nid, node in filtered_nodes.items():
            nodes_by_type[node.node_type.value].append(node)

        retained_nodes: list[CanonicalNode] = []
        limits_applied: dict[str, int] = {}
        for ntype, type_nodes in nodes_by_type.items():
            limit = plan.max_nodes_per_type.get(ntype, 15)
            limits_applied[ntype] = limit
            sorted_nodes = sorted(type_nodes, key=lambda n: node_scores.get(n.id, 0.0), reverse=True)
            retained_nodes.extend(sorted_nodes[:limit])

        retained_node_ids = {n.id for n in retained_nodes}

        # Step 7: Filter edges to those connecting retained nodes
        retained_edges: list[GraphEdge] = []
        for edge in candidate_edges.values():
            if edge.from_node_id in retained_node_ids and edge.to_node_id in retained_node_ids:
                retained_edges.append(edge)

        # Step 8: Collect incident evidence and filter/rank
        candidate_evidence_ids: set[UUID] = set()
        for node in retained_nodes:
            candidate_evidence_ids.update(node.provenance.evidence_ids)
        for edge in retained_edges:
            candidate_evidence_ids.update(edge.provenance.evidence_ids)
        candidate_evidence_ids.update(
            ev.id for ev in all_evidence if set(ev.entity_ids) & retained_node_ids
        )

        evidence_considered = len(candidate_evidence_ids)
        evidence_by_id = {ev.id: ev for ev in all_evidence}
        retained_evidence_objs: list[Evidence] = [
            evidence_by_id[eid] for eid in candidate_evidence_ids if eid in evidence_by_id
        ]

        # Rank evidence by relevance to query & directness
        def _ev_rank(ev: Evidence) -> float:
            score = 10.0
            if investigation:
                timestamp = ev.published_at or ev.retrieved_at
                age_days = max((as_of - utc(timestamp)).total_seconds() / 86400, 0)
                score += 30 / (1 + age_days)
                if ev.id in (view.scope.evidence_seeds or ()):
                    score += 60
            txt = (ev.raw_text or "").lower()
            if not investigation:
                score += 30.0 * overlap(query_text, txt)
            # Keep counterevidence competitive within finite context budgets.
            if any(edge.qualifiers.get("stance") in {"opposes", "qualifies"}
                   and ev.id in edge.provenance.evidence_ids for edge in retained_edges):
                score += 30.0
            if ev.extraction_method.value in {"source_explicit", "deterministic"}:
                score += 20.0
            return score

        retained_evidence_objs.sort(key=_ev_rank, reverse=True)
        retained_evidence_objs = retained_evidence_objs[: plan.max_evidence_spans]

        return MinimumSufficientSubgraph(
            nodes=retained_nodes,
            edges=retained_edges,
            evidence=retained_evidence_objs,
            nodes_considered=nodes_considered,
            nodes_retained=len(retained_nodes),
            evidence_considered=evidence_considered,
            evidence_retained=len(retained_evidence_objs),
            ranking_breakdown={str(nid): round(node_scores.get(nid, 0.0), 2) for nid in retained_node_ids},
            limits_applied=limits_applied,
            query_scope=view.scope_metadata(),
            coverage={
                **view.coverage,
                "retained_nodes": len(retained_nodes),
                "retained_edges": len(retained_edges),
                "retained_evidence": len(retained_evidence_objs),
                "retrieval_limits_applied": limits_applied,
            },
            evidence_membership=view.evidence_membership,
            memory_observations=view.memory_observations({ev.id for ev in retained_evidence_objs}),
            perception_observations=view.scoped_perceptions({ev.id for ev in retained_evidence_objs}),
        )
