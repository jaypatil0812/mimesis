"""Transparent v0 scores derived only from graph structure and historical time.

This module intentionally has no model client or extraction imports. It treats graph
relations as observations, not proof of causality, and preserves the exact inputs for
every result so the calculation can be replayed and challenged.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse
from uuid import UUID

from memesis.domain.schemas import (
    CanonicalNode,
    EdgeType,
    ExtractionMethod,
    GraphEdge,
    NodeType,
    ScoreComponent,
    ScoreRecord,
    ScoreType,
)
from memesis.graph.repository import GraphRepository

SCORE_VERSION = "deterministic-v0.1"
COMMERCIAL_EVENT_TYPES = {
    "acquisition",
    "deployment",
    "investment",
    "observed_outcome",
    "partnership",
    "pricing_change",
}


@dataclass(frozen=True)
class _Expression:
    actor_id: UUID
    belief_id: UUID
    content_id: UUID | None
    occurred_at: datetime
    time_basis: str
    group_id: str
    source_family: str
    stance: str | None
    edge_ids: tuple[UUID, ...]
    evidence_ids: tuple[UUID, ...]


@dataclass(frozen=True)
class ScoringRun:
    as_of: datetime
    window_days: int
    scores: tuple[ScoreRecord, ...]
    persisted: int

    def as_metrics(self) -> dict[str, object]:
        counts = Counter(score.score_type.value for score in self.scores)
        return {
            "as_of": self.as_of.isoformat(),
            "window_days": self.window_days,
            "scores_computed": len(self.scores),
            "scores_persisted": self.persisted,
            "by_type": dict(sorted(counts.items())),
            "llm_calls": 0,
            "score_version": SCORE_VERSION,
        }


class DeterministicScoringService:
    """Compute historical, decomposable v0 scores without invoking an LLM."""

    def __init__(self, repository: GraphRepository):
        self.repository = repository
        self.nodes: dict[UUID, CanonicalNode] = {}
        self.edges: list[GraphEdge] = []
        self.edges_by_type: dict[EdgeType, list[GraphEdge]] = defaultdict(list)
        self.expressions: list[_Expression] = []

    def compute_all(
        self, *, as_of: datetime | None = None, window_days: int = 30, persist: bool = True
    ) -> ScoringRun:
        if window_days < 1:
            raise ValueError("window_days must be positive")
        as_of = _utc(as_of or datetime.now(UTC))
        self._load(as_of)

        records: list[ScoreRecord] = []
        actor_beliefs = sorted(
            {(item.actor_id, item.belief_id) for item in self.expressions},
            key=lambda pair: (str(pair[0]), str(pair[1])),
        )
        for actor_id, belief_id in actor_beliefs:
            records.append(self._actor_lead(actor_id, belief_id, as_of))
            records.append(self._actor_influence(actor_id, belief_id, as_of))

        belief_ids = sorted(
            (node.id for node in self.nodes.values() if node.node_type == NodeType.BELIEF),
            key=str,
        )
        for belief_id in belief_ids:
            records.extend(
                (
                    self._belief_velocity(belief_id, as_of, window_days),
                    self._belief_diversity(belief_id, as_of),
                    self._action_conversion(belief_id, as_of),
                    self._evidence_confidence(belief_id, as_of),
                )
            )

        persisted = 0
        if persist:
            before = {score.input_fingerprint for score in self.repository.list_scores()}
            stored_records = []
            for record in records:
                stored_records.append(self.repository.add_score(record))
                if record.input_fingerprint not in before:
                    persisted += 1
            records = stored_records
        return ScoringRun(
            as_of=as_of,
            window_days=window_days,
            scores=tuple(records),
            persisted=persisted,
        )

    def explain(self, score_id: UUID) -> dict[str, object]:
        score = self.repository.get_score(score_id)
        if score is None:
            raise ValueError(f"unknown score {score_id}")
        return {
            "score": score.model_dump(mode="json"),
            "why": [
                {
                    "component": component.name,
                    "value": component.value,
                    "weight": component.weight,
                    "points": component.contribution,
                    "calculation": component.details,
                    "evidence_ids": [str(value) for value in component.evidence_ids],
                }
                for component in score.components
            ],
            "reconciliation": {
                "component_points": round(
                    sum(component.contribution for component in score.components), 4
                ),
                "score": score.value,
            },
            "warning": (
                "This is a deterministic graph statistic, not a causal conclusion or an "
                "LLM confidence judgment."
            ),
        }

    def _load(self, as_of: datetime) -> None:
        self.nodes = {node.id: node for node in self.repository.list_nodes()}
        self.edges = [
            edge for edge in self.repository.list_edges() if self._edge_time(edge)[0] <= as_of
        ]
        self.edges_by_type = defaultdict(list)
        for edge in self.edges:
            self.edges_by_type[edge.edge_type].append(edge)
        self.expressions = self._build_expressions()

    def _build_expressions(self) -> list[_Expression]:
        published_by_content: dict[UUID, list[GraphEdge]] = defaultdict(list)
        for edge in self.edges_by_type[EdgeType.PUBLISHED]:
            published_by_content[edge.to_node_id].append(edge)

        expressions: list[_Expression] = []
        content_evidence: dict[tuple[UUID, UUID], set[UUID]] = defaultdict(set)
        for expresses in self.edges_by_type[EdgeType.EXPRESSES]:
            for published in published_by_content[expresses.from_node_id]:
                actor = self.nodes.get(published.from_node_id)
                if actor is None or actor.node_type not in {NodeType.PERSON, NodeType.COMPANY}:
                    continue
                occurred_at, time_basis = max(
                    (self._edge_time(published), self._edge_time(expresses)),
                    key=lambda item: item[0],
                )
                evidence_ids = _uuid_union(
                    published.provenance.evidence_ids, expresses.provenance.evidence_ids
                )
                content_evidence[(actor.id, expresses.to_node_id)].update(evidence_ids)
                expressions.append(
                    _Expression(
                        actor_id=actor.id,
                        belief_id=expresses.to_node_id,
                        content_id=expresses.from_node_id,
                        occurred_at=occurred_at,
                        time_basis=time_basis,
                        group_id=self._independence_group(actor.id, occurred_at),
                        source_family=self._source_family(expresses),
                        stance=_stance(expresses),
                        edge_ids=(published.id, expresses.id),
                        evidence_ids=evidence_ids,
                    )
                )

        for believes in self.edges_by_type[EdgeType.BELIEVES]:
            key = (believes.from_node_id, believes.to_node_id)
            if set(believes.provenance.evidence_ids) & content_evidence[key]:
                continue
            occurred_at, time_basis = self._edge_time(believes)
            expressions.append(
                _Expression(
                    actor_id=believes.from_node_id,
                    belief_id=believes.to_node_id,
                    content_id=None,
                    occurred_at=occurred_at,
                    time_basis=time_basis,
                    group_id=self._independence_group(believes.from_node_id, occurred_at),
                    source_family=self._source_family(believes),
                    stance=_stance(believes),
                    edge_ids=(believes.id,),
                    evidence_ids=believes.provenance.evidence_ids,
                )
            )
        return sorted(
            expressions,
            key=lambda item: (item.occurred_at, str(item.actor_id), str(item.belief_id)),
        )

    def _actor_lead(self, actor_id: UUID, belief_id: UUID, as_of: datetime) -> ScoreRecord:
        own = self._actor_expressions(actor_id, belief_id)
        first = min(item.occurred_at for item in own)
        other_first = self._other_group_first_times(actor_id, belief_id)
        later = [time for time in other_first.values() if time > first]
        later_groups = {
            item.group_id
            for item in self._belief_expressions(belief_id)
            if item.actor_id != actor_id
            and item.group_id != self._independence_group(actor_id, first)
            and item.occurred_at > first
        }
        actions = self._actions_after(belief_id, first)
        commercial = self._commercial_events_after_actions(belief_id, actions)

        components = (
            self._component(
                "expression_frequency",
                _saturate(len(own), 5),
                0.25,
                len(own),
                5,
                {"unique_expressions": len(own), "saturation_target": 5},
                _expression_evidence(own),
            ),
            self._component(
                "temporal_lead",
                100 * len(later) / len(other_first) if other_first else 0,
                0.25,
                len(later),
                len(other_first),
                {
                    "actor_first_expression": first.isoformat(),
                    "later_independent_groups": len(later),
                    "comparison_groups": len(other_first),
                },
                _expression_evidence(own),
            ),
            self._component(
                "downstream_independent_adoption",
                _saturate(len(later_groups), 5),
                0.25,
                len(later_groups),
                5,
                {
                    "later_independent_groups": sorted(later_groups),
                    "saturation_target": 5,
                    "actor_quality_weighting": (
                        "equal; no reviewed historical actor-quality series is available"
                    ),
                },
                self._belief_evidence_after(belief_id, first),
            ),
            self._component(
                "downstream_company_action",
                _saturate(len({edge.from_node_id for edge in actions}), 3),
                0.15,
                len({edge.from_node_id for edge in actions}),
                3,
                {
                    "companies_acting_later": len({edge.from_node_id for edge in actions}),
                    "saturation_target": 3,
                },
                _edge_evidence(actions),
            ),
            self._component(
                "commercial_followthrough",
                _saturate(len(commercial), 2),
                0.10,
                len(commercial),
                2,
                {
                    "qualifying_commercial_events": len(commercial),
                    "allowed_event_subtypes": sorted(COMMERCIAL_EVENT_TYPES),
                    "saturation_target": 2,
                },
                _edge_evidence(commercial),
            ),
        )
        gaps = []
        if not other_first:
            gaps.append("no independent actor group available for temporal comparison")
        if not actions:
            gaps.append("no later explicit company ACTS_ON edge")
        return self._record(
            ScoreType.ACTOR_LEAD,
            actor_id,
            belief_id,
            as_of,
            components,
            (
                "0.25*expression_frequency + 0.25*temporal_lead + "
                "0.25*downstream_independent_adoption + "
                "0.15*downstream_company_action + 0.10*commercial_followthrough"
            ),
            {"actor_first_expression": first.isoformat()},
            gaps,
        )

    def _actor_influence(self, actor_id: UUID, belief_id: UUID, as_of: datetime) -> ScoreRecord:
        own = self._actor_expressions(actor_id, belief_id)
        first = min(item.occurred_at for item in own)
        other_first = self._other_group_first_times(actor_id, belief_id)
        later = [time for time in other_first.values() if time > first]
        own_group = self._independence_group(actor_id, first)
        adopters = {
            item.group_id
            for item in self._belief_expressions(belief_id)
            if item.group_id != own_group and item.occurred_at > first
        }
        actions = self._actions_after(belief_id, first)
        explicit = [
            edge
            for edge in self._explicit_propagation_edges(actor_id, belief_id)
            if self._edge_time(edge)[0] >= first
        ]

        # Principled Influence formulation:
        # Influence cannot be derived from popularity or correlation alone.
        # It requires evidence of the causal chain:
        # Actor expresses belief -> propagation occurs (explicit INFLUENCES/AMPLIFIES edges)
        # -> independent actors adopt -> downstream commercial actions follow.
        #
        # If there is ZERO explicit propagation connecting this actor's expression to others,
        # general market adoption and company actions cannot be credited as this actor's influence.
        # An unpropagated actor is at most an early observer (captured by ActorLead), not an influencer.
        has_propagation = len(explicit) > 0
        propagation_multiplier = 1.0 if has_propagation else 0.0

        # Check bot/amplifier authenticity: amplifier edges where the amplifying actor has zero
        # published content or expressions carry discounted weight (0.2 vs 1.0).
        effective_explicit_count = 0.0
        for edge in explicit:
            amplifier_id = edge.from_node_id
            has_expressions = any(item.actor_id == amplifier_id for item in self.expressions)
            effective_explicit_count += 1.0 if has_expressions else 0.2

        raw_downstream_adoption = _saturate(len(adopters), 5)
        raw_downstream_action = _saturate(len({edge.from_node_id for edge in actions}), 3)

        # Gated by propagation evidence:
        downstream_adoption_val = raw_downstream_adoption * propagation_multiplier
        downstream_action_val = raw_downstream_action * propagation_multiplier

        components = (
            self._component(
                "temporal_lead",
                100 * len(later) / len(other_first) if other_first else 0,
                0.20,
                len(later),
                len(other_first),
                {"later_groups": len(later), "comparison_groups": len(other_first)},
                _expression_evidence(own),
            ),
            self._component(
                "explicit_propagation",
                _saturate(int(effective_explicit_count), 3),
                0.35,
                int(effective_explicit_count),
                3,
                {
                    "explicit_INFLUENCES_or_AMPLIFIES_edges": len(explicit),
                    "effective_verified_propagation": effective_explicit_count,
                    "saturation_target": 3,
                },
                _edge_evidence(explicit),
            ),
            self._component(
                "independent_downstream_adoption",
                downstream_adoption_val,
                0.25,
                len(adopters) if has_propagation else 0,
                5,
                {
                    "later_independent_groups": sorted(adopters),
                    "propagation_verified": has_propagation,
                    "saturation_target": 5,
                },
                self._belief_evidence_after(belief_id, first) if has_propagation else (),
            ),
            self._component(
                "downstream_action",
                downstream_action_val,
                0.15,
                len({edge.from_node_id for edge in actions}) if has_propagation else 0,
                3,
                {
                    "later_acting_companies": len({edge.from_node_id for edge in actions}),
                    "propagation_verified": has_propagation,
                },
                _edge_evidence(actions) if has_propagation else (),
            ),
            self._component(
                "repeatability",
                _saturate(len(own), 3),
                0.05,
                len(own),
                3,
                {"unique_expressions": len(own), "saturation_target": 3},
                _expression_evidence(own),
            ),
        )
        gaps = []
        if not explicit:
            gaps.append("no explicit INFLUENCES or AMPLIFIES edge; popularity is not substituted")
        if not other_first:
            gaps.append("no independent actor group available for temporal comparison")
        return self._record(
            ScoreType.ACTOR_INFLUENCE,
            actor_id,
            belief_id,
            as_of,
            components,
            (
                "0.20*temporal_lead + 0.35*explicit_propagation + "
                "0.25*independent_downstream_adoption + 0.15*downstream_action + "
                "0.05*repeatability"
            ),
            {"actor_first_expression": first.isoformat()},
            gaps,
        )

    def _belief_velocity(self, belief_id: UUID, as_of: datetime, window_days: int) -> ScoreRecord:
        current_start = as_of - timedelta(days=window_days)
        previous_start = current_start - timedelta(days=window_days)
        expressions = self._belief_expressions(belief_id)
        actions = self._belief_actions(belief_id)
        current_expressions = [
            item for item in expressions if current_start < item.occurred_at <= as_of
        ]
        previous_expressions = [
            item for item in expressions if previous_start < item.occurred_at <= current_start
        ]
        current_actions = [
            edge for edge in actions if current_start < self._edge_time(edge)[0] <= as_of
        ]
        previous_actions = [
            edge for edge in actions if previous_start < self._edge_time(edge)[0] <= current_start
        ]
        curr_adopters = len({item.group_id for item in current_expressions})
        prev_adopters = len({item.group_id for item in previous_expressions})
        curr_action_companies = len({edge.from_node_id for edge in current_actions})
        prev_action_companies = len({edge.from_node_id for edge in previous_actions})
        latest = max((item.occurred_at for item in expressions), default=None)
        recency = (
            max(0.0, 100 * (1 - (as_of - latest).total_seconds() / (window_days * 86400)))
            if latest
            else 0.0
        )
        components = (
            self._component(
                "adopter_momentum",
                _momentum(curr_adopters, prev_adopters),
                0.40,
                curr_adopters,
                prev_adopters,
                {"current_independent_adopters": curr_adopters, "previous": prev_adopters},
                _expression_evidence(current_expressions + previous_expressions),
            ),
            self._component(
                "expression_momentum",
                _momentum(len(current_expressions), len(previous_expressions)),
                0.25,
                len(current_expressions),
                len(previous_expressions),
                {
                    "current_expressions": len(current_expressions),
                    "previous": len(previous_expressions),
                },
                _expression_evidence(current_expressions + previous_expressions),
            ),
            self._component(
                "action_momentum",
                _momentum(curr_action_companies, prev_action_companies),
                0.20,
                curr_action_companies,
                prev_action_companies,
                {
                    "current_acting_companies": curr_action_companies,
                    "previous": prev_action_companies,
                },
                _edge_evidence(current_actions + previous_actions),
            ),
            self._component(
                "recency",
                recency,
                0.15,
                None,
                window_days,
                {
                    "latest_expression": latest.isoformat() if latest else None,
                    "window_days": window_days,
                },
                _expression_evidence(current_expressions),
            ),
        )
        direction_delta = (curr_adopters + curr_action_companies) - (
            prev_adopters + prev_action_companies
        )
        return self._record(
            ScoreType.BELIEF_VELOCITY,
            belief_id,
            None,
            as_of,
            components,
            (
                "0.40*adopter_momentum + 0.25*expression_momentum + "
                "0.20*action_momentum + 0.15*recency; momentum=50+50*(current-previous)/"
                "(current+previous), or 0 when both are zero"
            ),
            {
                "direction": "accelerating"
                if direction_delta > 0
                else "decelerating"
                if direction_delta < 0
                else "stable",
                "current_window_start": current_start.isoformat(),
                "previous_window_start": previous_start.isoformat(),
            },
            ["no expression observations in either window"]
            if not current_expressions and not previous_expressions
            else [],
            window_start=previous_start,
            window_end=as_of,
        )

    def _belief_diversity(self, belief_id: UUID, as_of: datetime) -> ScoreRecord:
        expressions = self._belief_expressions(belief_id)
        sources = Counter(item.source_family for item in expressions)
        groups = Counter(item.group_id for item in expressions)
        organizations = {
            item.group_id for item in expressions if item.group_id.startswith("company:")
        }
        stances = {item.stance for item in expressions if item.stance}
        source_entropy = 100 * _normalized_entropy(sources)
        raw_actor_entropy = 100 * _normalized_entropy(groups)

        # Principled diversity: A single source family (e.g. 50 accounts on one platform)
        # cannot exhibit high independent actor diversity. Genuine diversity requires
        # cross-domain corroboration. When source entropy is near 0, effective actor entropy
        # is constrained to prevent echo chambers and bot swarms from manufacturing consensus.
        source_diversity_factor = min(1.0, 0.20 + 0.80 * (source_entropy / 100.0))
        effective_actor_entropy = raw_actor_entropy * source_diversity_factor

        components = (
            self._component(
                "source_family_entropy",
                source_entropy,
                0.35,
                len(sources),
                len(expressions),
                {"distribution": dict(sorted(sources.items()))},
                _expression_evidence(expressions),
            ),
            self._component(
                "independent_actor_entropy",
                effective_actor_entropy,
                0.35,
                len(groups),
                len(expressions),
                {
                    "raw_actor_entropy": raw_actor_entropy,
                    "source_diversity_factor": source_diversity_factor,
                    "distribution": dict(sorted(groups.items())),
                },
                _expression_evidence(expressions),
            ),
            self._component(
                "organization_breadth",
                _saturate(len(organizations), 5),
                0.20,
                len(organizations),
                5,
                {"organizations": sorted(organizations), "saturation_target": 5},
                _expression_evidence(expressions),
            ),
            self._component(
                "stance_breadth",
                _saturate(len(stances), 3),
                0.10,
                len(stances),
                3,
                {"stances": sorted(stances), "saturation_target": 3},
                _expression_evidence(expressions),
            ),
        )
        gaps = []
        if len(sources) <= 1:
            gaps.append("one source family dominates or is the only observed source")
        if len(groups) <= 1:
            gaps.append("one independent actor group dominates or is the only observed group")
        return self._record(
            ScoreType.BELIEF_DIVERSITY,
            belief_id,
            None,
            as_of,
            components,
            (
                "0.35*source_family_entropy + 0.35*independent_actor_entropy + "
                "0.20*organization_breadth + 0.10*stance_breadth"
            ),
            {"expression_count": len(expressions)},
            gaps,
        )

    def _action_conversion(self, belief_id: UUID, as_of: datetime) -> ScoreRecord:
        company_expressions = [
            item
            for item in self._belief_expressions(belief_id)
            if self.nodes[item.actor_id].node_type == NodeType.COMPANY
            and item.content_id is not None
        ]
        first_exposure: dict[UUID, datetime] = {}
        for item in company_expressions:
            first_exposure[item.actor_id] = min(
                first_exposure.get(item.actor_id, item.occurred_at), item.occurred_at
            )
        actions = [
            edge
            for edge in self._belief_actions(belief_id)
            if edge.from_node_id in first_exposure
            and self._edge_time(edge)[0] > first_exposure[edge.from_node_id]
        ]
        first_action: dict[UUID, GraphEdge] = {}
        for edge in actions:
            current = first_action.get(edge.from_node_id)
            if current is None or self._edge_time(edge)[0] < self._edge_time(current)[0]:
                first_action[edge.from_node_id] = edge
        converters = set(first_action)
        commercial = self._commercial_events_after_actions(belief_id, list(first_action.values()))
        lags = [
            (self._edge_time(edge)[0] - first_exposure[company_id]).total_seconds() / 86400
            for company_id, edge in first_action.items()
        ]
        lag_speed = 100 * sum(max(0.0, 1 - lag / 180) for lag in lags) / len(lags) if lags else 0
        provenance_groups = {self._source_family(edge) for edge in [*actions, *commercial]}
        exposure_count = len(first_exposure)
        components = (
            self._component(
                "conversion_rate",
                100 * len(converters) / exposure_count if exposure_count else 0,
                0.40,
                len(converters),
                exposure_count,
                {
                    "converting_companies": len(converters),
                    "explicitly_exposed_companies": exposure_count,
                },
                _edge_evidence(actions),
            ),
            self._component(
                "action_breadth",
                _saturate(len(converters), 3),
                0.20,
                len(converters),
                3,
                {"converting_companies": len(converters), "saturation_target": 3},
                _edge_evidence(actions),
            ),
            self._component(
                "commercial_event_depth",
                _saturate(len(commercial), 5),
                0.20,
                len(commercial),
                5,
                {"qualifying_commercial_events": len(commercial), "saturation_target": 5},
                _edge_evidence(commercial),
            ),
            self._component(
                "conversion_lag_speed",
                lag_speed,
                0.10,
                None,
                180,
                {"lag_days": [round(value, 3) for value in sorted(lags)], "zero_point_days": 180},
                _edge_evidence(actions),
            ),
            self._component(
                "independent_action_evidence",
                _saturate(len(provenance_groups), 5),
                0.10,
                len(provenance_groups),
                5,
                {"source_families": sorted(provenance_groups), "saturation_target": 5},
                _edge_evidence([*actions, *commercial]),
            ),
        )
        gaps = []
        if not first_exposure:
            gaps.append(
                "no company PUBLISHED→Content→EXPRESSES path; action conversion is "
                "undefined and scored 0"
            )
        if first_exposure and not converters:
            gaps.append("no later explicit company ACTS_ON edge")
        return self._record(
            ScoreType.ACTION_CONVERSION,
            belief_id,
            None,
            as_of,
            components,
            (
                "0.40*conversion_rate + 0.20*action_breadth + "
                "0.20*commercial_event_depth + 0.10*conversion_lag_speed + "
                "0.10*independent_action_evidence"
            ),
            {"company_exposures": len(first_exposure), "converters": len(converters)},
            gaps,
        )

    def _evidence_confidence(self, belief_id: UUID, as_of: datetime) -> ScoreRecord:
        expressions = self._belief_expressions(belief_id)
        relevant_ids = {edge_id for item in expressions for edge_id in item.edge_ids}
        relevant = [
            edge
            for edge in self.edges
            if edge.id in relevant_ids
            or (edge.edge_type == EdgeType.ACTS_ON and edge.to_node_id == belief_id)
        ]
        completeness_values = []
        span_values = []
        time_values = []
        audit_values = []
        for edge in relevant:
            evidence_exists = all(
                self.repository.get_evidence(value) is not None
                for value in edge.provenance.evidence_ids
            )
            completeness_values.append(
                sum(
                    (
                        bool(edge.provenance.source_url),
                        bool(edge.provenance.source_type),
                        bool(edge.provenance.retrieved_at),
                        bool(edge.provenance.original_reference),
                        bool(edge.provenance.evidence_ids),
                        evidence_exists,
                    )
                )
                / 6
            )
            assertion = self._edge_assertion(edge)
            exact_spans = bool(assertion) and all(
                self.repository.get_evidence_span(span_id) is not None
                for span_id in assertion.evidence_span_ids
            )
            span_values.append(1.0 if exact_spans else 0.0)
            time_values.append(1.0 if edge.valid_from or edge.provenance.published_at else 0.0)
            audit_values.append(self._auditability(edge, assertion, exact_spans))

        provenance_completeness = 100 * _mean(completeness_values)
        groups = {item.group_id for item in expressions} | {
            f"company:{edge.from_node_id}"
            for edge in relevant
            if edge.edge_type == EdgeType.ACTS_ON
        }
        components = (
            self._component(
                "provenance_completeness",
                provenance_completeness,
                0.25,
                sum(completeness_values),
                len(completeness_values),
                {"relations_audited": len(relevant), "required_fields_per_relation": 6},
                _edge_evidence(relevant),
            ),
            self._component(
                "independent_corroboration",
                _saturate(len(groups), 3),
                0.25,
                len(groups),
                3,
                {"independent_groups": sorted(groups), "saturation_target": 3},
                _edge_evidence(relevant),
            ),
            self._component(
                "exact_span_coverage",
                100 * _mean(span_values),
                0.20,
                sum(span_values),
                len(span_values),
                {
                    "relations_with_retrievable_assertion_spans": int(sum(span_values)),
                    "relations": len(relevant),
                },
                _edge_evidence(relevant),
            ),
            self._component(
                "temporal_precision",
                100 * _mean(time_values),
                0.15,
                sum(time_values),
                len(time_values),
                {"published_or_valid_from": int(sum(time_values)), "relations": len(relevant)},
                _edge_evidence(relevant),
            ),
            self._component(
                "extraction_auditability",
                100 * _mean(audit_values),
                0.15,
                sum(audit_values),
                len(audit_values),
                {
                    "rubric": {
                        "source_explicit": 100,
                        "deterministic": 100,
                        "analyst": 80,
                        "derived": 60,
                        "extracted_with_model_prompt_and_span": 70,
                        "extracted_without_complete_lineage": 40,
                    },
                    "relations": len(relevant),
                },
                _edge_evidence(relevant),
            ),
        )
        gaps = []
        if not relevant:
            gaps.append("no graph relations support this belief")
        if relevant and not any(span_values):
            gaps.append("no relation has a retrievable exact evidence span")
        return self._record(
            ScoreType.EVIDENCE_CONFIDENCE,
            belief_id,
            None,
            as_of,
            components,
            (
                "0.25*provenance_completeness + 0.25*independent_corroboration + "
                "0.20*exact_span_coverage + 0.15*temporal_precision + "
                "0.15*extraction_auditability; stored model/assertion confidence is never an input"
            ),
            {"relations_audited": len(relevant), "declared_confidence_values_used": False},
            gaps,
        )

    def _record(
        self,
        score_type: ScoreType,
        subject_id: UUID,
        context_id: UUID | None,
        as_of: datetime,
        components: tuple[ScoreComponent, ...],
        formula: str,
        inputs: dict[str, object],
        gaps: list[str],
        *,
        window_start: datetime | None = None,
        window_end: datetime | None = None,
    ) -> ScoreRecord:
        evidence_ids = _uuid_union(*(component.evidence_ids for component in components))
        edge_ids = sorted(
            {
                str(edge.id)
                for edge in self.edges
                if set(edge.provenance.evidence_ids) & set(evidence_ids)
            }
        )
        component_inputs = [
            {
                "name": component.name,
                "value": component.value,
                "weight": component.weight,
                "numerator": component.numerator,
                "denominator": component.denominator,
                "details": component.details,
            }
            for component in components
        ]
        fingerprint_payload = {
            "score_type": score_type.value,
            "subject_id": str(subject_id),
            "context_id": str(context_id) if context_id else None,
            "version": SCORE_VERSION,
            "as_of": as_of.isoformat(),
            "window_start": window_start.isoformat() if window_start else None,
            "window_end": window_end.isoformat() if window_end else None,
            "edge_ids": edge_ids,
            "evidence_ids": [str(value) for value in evidence_ids],
            "components": component_inputs,
        }
        fingerprint = hashlib.sha256(
            json.dumps(fingerprint_payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        value = round(sum(component.contribution for component in components), 4)
        return ScoreRecord(
            score_type=score_type,
            subject_id=subject_id,
            context_id=context_id,
            version=SCORE_VERSION,
            as_of=as_of,
            window_start=window_start,
            window_end=window_end,
            value=value,
            formula=formula,
            components=components,
            evidence_ids=evidence_ids,
            inputs={**inputs, "edge_ids": edge_ids},
            input_fingerprint=fingerprint,
            coverage={
                "evidence_count": len(evidence_ids),
                "edge_count": len(edge_ids),
                "gaps": gaps,
            },
            computed_at=datetime.now(UTC),
        )

    @staticmethod
    def _component(
        name: str,
        value: float,
        weight: float,
        numerator: float | None,
        denominator: float | None,
        details: dict[str, object],
        evidence_ids: tuple[UUID, ...],
    ) -> ScoreComponent:
        value = round(max(0.0, min(100.0, value)), 4)
        return ScoreComponent(
            name=name,
            value=value,
            weight=weight,
            contribution=round(value * weight, 4),
            numerator=numerator,
            denominator=denominator,
            details=details,
            evidence_ids=evidence_ids,
        )

    def _actor_expressions(self, actor_id: UUID, belief_id: UUID) -> list[_Expression]:
        return [
            item
            for item in self.expressions
            if item.actor_id == actor_id and item.belief_id == belief_id
        ]

    def _belief_expressions(self, belief_id: UUID) -> list[_Expression]:
        return [item for item in self.expressions if item.belief_id == belief_id]

    def _belief_actions(self, belief_id: UUID) -> list[GraphEdge]:
        return [
            edge for edge in self.edges_by_type[EdgeType.ACTS_ON] if edge.to_node_id == belief_id
        ]

    def _actions_after(self, belief_id: UUID, after: datetime) -> list[GraphEdge]:
        return [
            edge for edge in self._belief_actions(belief_id) if self._edge_time(edge)[0] > after
        ]

    def _other_group_first_times(self, actor_id: UUID, belief_id: UUID) -> dict[str, datetime]:
        own = self._actor_expressions(actor_id, belief_id)
        own_group = self._independence_group(actor_id, min(item.occurred_at for item in own))
        result: dict[str, datetime] = {}
        for item in self._belief_expressions(belief_id):
            if item.group_id == own_group:
                continue
            result[item.group_id] = min(
                result.get(item.group_id, item.occurred_at), item.occurred_at
            )
        return result

    def _belief_evidence_after(self, belief_id: UUID, after: datetime) -> tuple[UUID, ...]:
        return _expression_evidence(
            [item for item in self._belief_expressions(belief_id) if item.occurred_at > after]
        )

    def _explicit_propagation_edges(self, actor_id: UUID, belief_id: UUID) -> list[GraphEdge]:
        actor_content = {
            item.content_id
            for item in self._actor_expressions(actor_id, belief_id)
            if item.content_id is not None
        }
        belief_content = {
            item.content_id
            for item in self._belief_expressions(belief_id)
            if item.content_id is not None
        }
        return [
            edge
            for edge in [
                *self.edges_by_type[EdgeType.INFLUENCES],
                *self.edges_by_type[EdgeType.AMPLIFIES],
            ]
            if edge.from_node_id in {actor_id, *actor_content}
            and edge.to_node_id in {belief_id, *belief_content}
        ]

    def _commercial_events_after_actions(
        self, belief_id: UUID, actions: list[GraphEdge]
    ) -> list[GraphEdge]:
        del belief_id  # the action list already scopes the belief
        action_time = {
            edge.from_node_id: min(
                self._edge_time(candidate)[0]
                for candidate in actions
                if candidate.from_node_id == edge.from_node_id
            )
            for edge in actions
        }
        result = []
        for edge in self.edges_by_type[EdgeType.PARTICIPATED_IN]:
            if edge.from_node_id not in action_time:
                continue
            event = self.nodes.get(edge.to_node_id)
            subtype = str(event.attributes.get("subtype", "")) if event else ""
            if (
                event
                and event.node_type == NodeType.EVENT
                and subtype in COMMERCIAL_EVENT_TYPES
                and self._edge_time(edge)[0] > action_time[edge.from_node_id]
            ):
                result.append(edge)
        return result

    def _independence_group(self, actor_id: UUID, at: datetime) -> str:
        node = self.nodes.get(actor_id)
        if node and node.node_type == NodeType.COMPANY:
            return f"company:{actor_id}"
        affiliations = [
            edge
            for edge in self.edges_by_type[EdgeType.WORKS_AT]
            if edge.from_node_id == actor_id
            and self._edge_time(edge)[0] <= at
            and (edge.valid_to is None or _utc(edge.valid_to) >= at)
        ]
        if affiliations:
            latest = max(affiliations, key=lambda edge: self._edge_time(edge)[0])
            return f"company:{latest.to_node_id}"
        return f"actor:{actor_id}"

    def _edge_time(self, edge: GraphEdge) -> tuple[datetime, str]:
        if edge.valid_from:
            return _utc(edge.valid_from), "valid_from"
        if edge.provenance.published_at:
            return _utc(edge.provenance.published_at), "published_at"
        return _utc(edge.provenance.retrieved_at), "retrieved_at_fallback"

    @staticmethod
    def _source_family(edge: GraphEdge) -> str:
        if edge.qualifiers.get("source_family"):
            return str(edge.qualifiers["source_family"])
        host = urlparse(str(edge.provenance.source_url)).hostname or "unknown-host"
        return f"{edge.provenance.source_type}:{host.lower()}"

    def _edge_assertion(self, edge: GraphEdge):
        raw = edge.qualifiers.get("assertion_id")
        if not raw:
            return None
        try:
            return self.repository.get_assertion(UUID(str(raw)))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _auditability(edge: GraphEdge, assertion, exact_spans: bool) -> float:
        method = edge.provenance.extraction_method
        if method in {ExtractionMethod.SOURCE_EXPLICIT, ExtractionMethod.DETERMINISTIC}:
            return 1.0
        if method == ExtractionMethod.ANALYST:
            return 0.8
        if method == ExtractionMethod.DERIVED:
            return 0.6
        complete = bool(
            edge.provenance.extraction_model
            and assertion
            and assertion.prompt_version
            and exact_spans
        )
        return 0.7 if complete else 0.4


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _saturate(count: int, target: int) -> float:
    return 100 * min(count / target, 1.0) if target else 0.0


def _momentum(current: int, previous: int) -> float:
    total = current + previous
    return max(0.0, min(100.0, 50 + 50 * (current - previous) / total)) if total else 0.0


def _normalized_entropy(counts: Counter[str]) -> float:
    if len(counts) <= 1:
        return 0.0
    total = sum(counts.values())
    entropy = -sum((count / total) * math.log(count / total) for count in counts.values())
    return entropy / math.log(len(counts))


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _stance(edge: GraphEdge) -> str | None:
    value = edge.qualifiers.get("stance")
    return str(value) if value else None


def _uuid_union(*values: tuple[UUID, ...] | set[UUID]) -> tuple[UUID, ...]:
    return tuple(sorted({item for group in values for item in group}, key=str))


def _edge_evidence(edges: list[GraphEdge]) -> tuple[UUID, ...]:
    return _uuid_union(*(edge.provenance.evidence_ids for edge in edges))


def _expression_evidence(expressions: list[_Expression]) -> tuple[UUID, ...]:
    return _uuid_union(*(item.evidence_ids for item in expressions))
