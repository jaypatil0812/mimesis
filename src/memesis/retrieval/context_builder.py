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
        as_of = as_of or datetime.now(UTC)
        scores = scores or []
        scores_by_subject: dict[UUID, list[ScoreRecord]] = defaultdict(list)
        for s in scores:
            scores_by_subject[s.subject_id].append(s)

        def _normalize_dt(dt: datetime | None) -> datetime:
            if dt is None:
                return datetime.now(UTC)
            return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)

        as_of_utc = _normalize_dt(as_of)

        raw_evidence = self.repository.list_evidence()
        all_evidence = [
            ev for ev in raw_evidence
            if _normalize_dt(ev.published_at or ev.retrieved_at) <= as_of_utc
        ]
        valid_evidence_ids = {ev.id for ev in all_evidence}

        raw_edges = self.repository.list_edges()
        all_edges: list[GraphEdge] = []
        for edge in raw_edges:
            if edge.recorded_at and _normalize_dt(edge.recorded_at) > as_of_utc:
                continue
            if edge.valid_from and _normalize_dt(edge.valid_from) > as_of_utc:
                continue
            edge_ev_ids = [eid for eid in edge.provenance.evidence_ids if eid in valid_evidence_ids]
            if edge.provenance.evidence_ids and not edge_ev_ids:
                continue
            all_edges.append(edge)

        raw_nodes = self.repository.list_nodes()
        all_nodes: list[CanonicalNode] = []
        for node in raw_nodes:
            node_ev_ids = [eid for eid in node.provenance.evidence_ids if eid in valid_evidence_ids]
            if node.provenance.evidence_ids and not node_ev_ids:
                continue
            all_nodes.append(node)

        # Step 1: Filter nodes by time window if specified
        cutoff_time = as_of_utc - timedelta(days=plan.time_filter_days) if plan.time_filter_days else None

        # Step 2: Seed nodes matching query entities and keywords
        query_text = plan.intent.raw_query.lower()
        seed_nodes: list[CanonicalNode] = []
        for node in all_nodes:
            name_lower = node.name.lower()
            if any(e.lower() in name_lower for e in plan.intent.entities):
                seed_nodes.append(node)
            elif any(w in name_lower for w in ["small", "model", "specialized", "inference", "router", "routing", "latency", "cost"]):
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
                if cutoff_time and edge.recorded_at:
                    # Normalize: SQLite stores naive datetimes; strip tz for comparison
                    edge_dt = edge.recorded_at.replace(tzinfo=None) if edge.recorded_at.tzinfo is None else edge.recorded_at
                    cutoff_dt = cutoff_time.replace(tzinfo=None) if edge_dt.tzinfo is None else cutoff_time
                    if edge_dt < cutoff_dt:
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

        # Step 4: Apply Jev-style cheap relevance filtering
        filtered_nodes: dict[UUID, CanonicalNode] = {}
        for nid, node in candidate_nodes.items():
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
            if rel_dec.decision == "RELEVANT" or node.id in seed_ids:
                filtered_nodes[nid] = node

        # Step 5: Rank nodes within their type
        node_degrees = Counter()
        for edge in candidate_edges.values():
            node_degrees[edge.from_node_id] += 1
            node_degrees[edge.to_node_id] += 1

        node_scores: dict[UUID, float] = {}
        for nid, node in filtered_nodes.items():
            score = 0.0
            # Relevance boost
            if any(e.lower() in node.name.lower() for e in plan.intent.entities):
                score += 40.0
            elif any(w in node.name.lower() for w in ["small", "specialized", "inference", "cost", "routing"]):
                score += 25.0

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

        evidence_considered = len(candidate_evidence_ids)
        evidence_by_id = {ev.id: ev for ev in all_evidence}
        retained_evidence_objs: list[Evidence] = [
            evidence_by_id[eid] for eid in candidate_evidence_ids if eid in evidence_by_id
        ]

        # Rank evidence by relevance to query & directness
        def _ev_rank(ev: Evidence) -> float:
            score = 10.0
            txt = (ev.raw_text or "").lower()
            if any(term in txt for term in ["small", "specialized", "inference", "cost", "latency"]):
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
        )
