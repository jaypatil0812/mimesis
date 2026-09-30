"""Shared market/time boundaries for workspace, retrieval and scoring reads."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from memesis.domain.schemas import EdgeType, NodeType, ScoreType
from memesis.graph.repository import GraphRepository


def utc(value: datetime) -> datetime:
    # SQLite records can be naive; the application's stored timestamps are UTC.
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class ScopeOptions(BaseModel):
    start_at: datetime | None = None
    as_of: datetime = Field(default_factory=lambda: datetime.now(UTC))
    time_basis: Literal["published_at", "known_at"] = "published_at"
    graph_hops: int = Field(default=3, ge=1, le=6)
    include_adjacent_markets: bool = True

    @model_validator(mode="after")
    def normalize_window(self) -> ScopeOptions:
        self.as_of = utc(self.as_of)
        if self.start_at is not None:
            self.start_at = utc(self.start_at)
            if self.start_at > self.as_of:
                raise ValueError("start_at must not be after as_of")
        return self


class QueryScope(ScopeOptions):
    market_id: UUID | None = None


class ScopedGraphRepository:
    """A read snapshot; writes and run/cache persistence stay on the real repository.

    Membership follows evidence-backed graph paths, not keyword matching. Explicit
    market tags constrain source ownership; untagged sources need a traversed edge
    or an anchor's provenance. Sharing an actor alone never imports all their posts.
    """

    def __init__(self, repository: GraphRepository, scope: QueryScope) -> None:
        self._repository = repository
        self.scope = scope
        all_nodes = {node.id: node for node in repository.list_nodes()}
        all_edges = repository.list_edges()
        all_evidence = repository.list_evidence()
        market = all_nodes.get(scope.market_id)
        if scope.market_id and (market is None or market.node_type != NodeType.MARKET):
            raise ValueError(f"Market {scope.market_id} not found")

        def known_by_cutoff(ev) -> bool:
            return utc(ev.retrieved_at) <= scope.as_of and (
                ev.updated_at is None or utc(ev.updated_at) <= scope.as_of
            )

        def in_window(ev) -> bool:
            timestamp = utc(ev.published_at or ev.retrieved_at)
            return (
                timestamp <= scope.as_of
                and (scope.start_at is None or timestamp >= scope.start_at)
                and (scope.time_basis != "known_at" or known_by_cutoff(ev))
            )

        dated_evidence = {ev.id: ev for ev in all_evidence if in_window(ev)}
        date_matching_count = len(dated_evidence)
        evidence_ids = set(dated_evidence)
        available_nodes = {}
        upper_evidence_ids = {
            ev.id for ev in all_evidence
            if utc(ev.published_at or ev.retrieved_at) <= scope.as_of
            and (scope.time_basis != "known_at" or known_by_cutoff(ev))
        }
        for node in all_nodes.values():
            if set(node.provenance.evidence_ids) & upper_evidence_ids:
                available_nodes[node.id] = node

        eligible_edges = []
        for edge in all_edges:
            citations = tuple(eid for eid in edge.provenance.evidence_ids if eid in evidence_ids)
            if not citations:
                continue
            if edge.valid_from and utc(edge.valid_from) > scope.as_of:
                continue
            if edge.provenance.published_at and utc(edge.provenance.published_at) > scope.as_of:
                continue
            if scope.start_at and edge.valid_to and utc(edge.valid_to) < scope.start_at:
                continue
            if scope.time_basis == "known_at" and utc(edge.recorded_at) > scope.as_of:
                continue
            if edge.from_node_id not in available_nodes or edge.to_node_id not in available_nodes:
                continue
            eligible_edges.append(edge.model_copy(update={
                "provenance": edge.provenance.model_copy(update={"evidence_ids": citations}),
            }))

        self.node_distances: dict[UUID, int] = {}
        adjacent_ids: set[UUID] = set()
        if scope.market_id:
            if scope.include_adjacent_markets:
                for edge in eligible_edges:
                    if edge.edge_type == EdgeType.ADJACENT_TO:
                        if edge.from_node_id == scope.market_id:
                            adjacent_ids.add(edge.to_node_id)
                        if edge.to_node_id == scope.market_id:
                            adjacent_ids.add(edge.from_node_id)
            adjacent_ids = {
                nid for nid in adjacent_ids
                if available_nodes[nid].node_type == NodeType.MARKET
            }
            allowed_markets = {scope.market_id} | adjacent_ids
            foreign_markets = {
                nid for nid, node in all_nodes.items()
                if node.node_type == NodeType.MARKET and nid not in allowed_markets
            }
            # A foreign market's explicitly tagged records cannot enter via a shared actor.
            dated_evidence = {
                eid: ev for eid, ev in dated_evidence.items()
                if not (set(ev.entity_ids) & foreign_markets)
                or bool(set(ev.entity_ids) & allowed_markets)
            }
            evidence_ids = set(dated_evidence)
            market_edges = []
            for edge in eligible_edges:
                citations = tuple(eid for eid in edge.provenance.evidence_ids if eid in evidence_ids)
                if citations and not ({edge.from_node_id, edge.to_node_id} & foreign_markets):
                    market_edges.append(edge.model_copy(update={
                        "provenance": edge.provenance.model_copy(update={"evidence_ids": citations}),
                    }))

            distances = {scope.market_id: 0}
            # Explicit market mentions are direct membership even before graph projection.
            direct_evidence_ids = {
                eid for eid, ev in dated_evidence.items() if scope.market_id in ev.entity_ids
            }
            for eid in direct_evidence_ids:
                for nid in dated_evidence[eid].entity_ids:
                    if nid in available_nodes and nid not in foreign_markets and nid != scope.market_id:
                        distances[nid] = 1
            for hop in range(scope.graph_hops):
                frontier = {nid for nid, distance in distances.items() if distance == hop}
                for eid, ev in dated_evidence.items():
                    if set(ev.entity_ids) & frontier & allowed_markets:
                        direct_evidence_ids.add(eid)
                        for nid in ev.entity_ids:
                            if nid in available_nodes and nid not in foreign_markets:
                                distances.setdefault(nid, hop + 1)
                for edge in market_edges:
                    if edge.from_node_id in frontier:
                        distances.setdefault(edge.to_node_id, hop + 1)
                    if edge.to_node_id in frontier:
                        distances.setdefault(edge.from_node_id, hop + 1)
            self.node_distances = distances
            direct_evidence_ids.update(
                eid for eid, ev in dated_evidence.items()
                if set(ev.entity_ids) & allowed_markets & set(distances)
            )
            selected_edges = [
                edge for edge in market_edges
                if edge.from_node_id in distances and edge.to_node_id in distances
            ]
            selected_evidence_ids = direct_evidence_ids | {
                eid for edge in selected_edges for eid in edge.provenance.evidence_ids
            }
            # Preserve anchor definition evidence, but never import an actor's entire history.
            selected_evidence_ids.update(
                eid for eid in market.provenance.evidence_ids if eid in evidence_ids
            )
            selected_nodes = [
                node for nid, node in available_nodes.items() if nid in distances
            ]
            if market.id not in {node.id for node in selected_nodes}:
                selected_nodes.append(market)  # an identity anchor, not an in-window observation
        else:
            observed_node_ids = {
                node.id for node in available_nodes.values()
                if set(node.provenance.evidence_ids) & evidence_ids
            } | {nid for edge in eligible_edges for nid in (edge.from_node_id, edge.to_node_id)}
            selected_nodes = [node for nid, node in available_nodes.items() if nid in observed_node_ids]
            selected_edges = eligible_edges
            selected_evidence_ids = evidence_ids

        self.nodes = selected_nodes
        self.edges = selected_edges
        self.evidence = [
            ev for eid, ev in dated_evidence.items() if eid in selected_evidence_ids
        ]
        self._nodes_by_id = {node.id: node for node in self.nodes}
        self._evidence_by_id = {ev.id: ev for ev in self.evidence}
        self.evidence_membership = {
            str(ev.id): (
                "selected_market" if scope.market_id in ev.entity_ids
                else "adjacent_market" if set(ev.entity_ids) & adjacent_ids
                else "graph_connection" if scope.market_id else "unscoped_market"
            )
            for ev in self.evidence
        }
        dates = [utc(ev.published_at or ev.retrieved_at) for ev in self.evidence]
        self.coverage = {
            "database_nodes": len(all_nodes),
            "database_edges": len(all_edges),
            "database_evidence": len(all_evidence),
            "evidence_matching_dates": date_matching_count,
            "scoped_nodes": len(self.nodes),
            "scoped_edges": len(self.edges),
            "scoped_evidence": len(self.evidence),
            "earliest_evidence_at": min(dates).isoformat() if dates else None,
            "latest_evidence_at": max(dates).isoformat() if dates else None,
            "publication_date_missing": sum(ev.published_at is None for ev in self.evidence),
            "included_adjacent_market_ids": sorted(str(nid) for nid in adjacent_ids if nid in self.node_distances),
            "limits": [
                "Coverage is only the stored, linked corpus; absence is not evidence of no market activity.",
                "Canonical entity metadata is not versioned; this is not a complete historical database replay.",
            ],
        }

    def scope_metadata(self) -> dict:
        return {
            **self.scope.model_dump(mode="json"),
            "date_bounds": "inclusive",
            "timestamp_basis": "published_at with retrieved_at fallback",
            "knowledge_cutoff_enforced": self.scope.time_basis == "known_at",
            "membership_basis": "explicit market references or evidence-backed graph paths",
        }

    def compute_scores(self):
        from memesis.analysis.scoring import DeterministicScoringService

        # Velocity compares two consecutive windows. Fit both inside the scope
        # instead of treating an excluded previous period as zero activity.
        window_days = max(1, (self.scope.as_of - self.scope.start_at).days // 2) if self.scope.start_at else 30
        run = DeterministicScoringService(self).compute_all(
            as_of=self.scope.as_of, window_days=window_days, persist=False,
        )
        unavailable = []
        scores = []
        for score in run.scores:
            if (score.score_type == ScoreType.BELIEF_VELOCITY and self.scope.start_at
                    and score.window_start and score.window_start < self.scope.start_at):
                unavailable.append(score.score_type.value)
                continue
            scores.append(score)
        self.coverage.update({
            "scores_recomputed_from_scope": True,
            "score_comparison_window_days": window_days,
            "unavailable_score_types": sorted(set(unavailable)),
        })
        if unavailable:
            self.coverage["limits"].append("Velocity comparison needs two complete daily windows inside the scope.")
        return scores

    def list_nodes(self):
        return list(self.nodes)

    def list_edges(self):
        return list(self.edges)

    def list_evidence(self, limit: int | None = None):
        return list(self.evidence if limit is None else self.evidence[:limit])

    def get_node(self, node_id: UUID):
        return self._nodes_by_id.get(node_id)

    def get_evidence(self, evidence_id: UUID):
        return self._evidence_by_id.get(evidence_id)

    def list_scores(self, score_type=None, subject_id=None):
        # Global cached scores have no market boundary and must be recomputed in this view.
        return []

    def get_assertion(self, assertion_id: UUID):
        assertion = self._repository.get_assertion(assertion_id)
        if assertion is not None and set(assertion.provenance.evidence_ids) <= self._evidence_by_id.keys():
            return assertion
        return None

    def get_evidence_span(self, span_id: UUID):
        span = self._repository.get_evidence_span(span_id)
        if span is not None and set(span.provenance.evidence_ids) <= self._evidence_by_id.keys():
            return span
        return None
