"""Describe measured graph indicators without inventing market narratives."""
from __future__ import annotations
from datetime import UTC, datetime
from enum import Enum
from pydantic import BaseModel, Field
from memesis.domain.schemas import EdgeType, ScoreType

class MarketMotionStatus(str, Enum):
    ACCELERATING = "ACCELERATING"
    STABLE = "STABLE"
    DECELERATING = "DECELERATING"
    NASCENT = "NASCENT"
    UNCERTAIN = "UNCERTAIN"

class MarketMotion(BaseModel):
    status: MarketMotionStatus
    velocity_trend: str
    actor_lead_signal: str
    actor_influence_signal: str
    belief_diversity_signal: str
    action_conversion_signal: str
    evidence_confidence_score: float | None
    customer_perception_signal: str
    company_action_acceleration: str
    adjacent_market_signals: list[str] = Field(default_factory=list)
    contradictory_signals: list[str] = Field(default_factory=list)
    evidence_breakdown: list[str] = Field(min_length=1)
    coverage_gaps: list[str] = Field(default_factory=list)
    as_of: datetime = Field(default_factory=lambda: datetime.now(UTC))

class MarketMotionAnalyzer:
    def analyze(self, subgraph, scores=None, as_of=None):
        scores = scores or []
        groups = {kind: [s for s in scores if s.score_type == kind] for kind in ScoreType}
        def metric(kind):
            records = groups[kind]
            if not records:
                return f"Unknown: no {kind.value} measurement in this scope."
            avg = sum(s.value for s in records) / len(records)
            return f"{kind.value}: mean {avg:.1f}/100 across {len(records)} recorded subjects; descriptive score, not causality."
        velocity = groups[ScoreType.BELIEF_VELOCITY]
        # Mixed propositions cannot establish one market-wide direction.
        trends = {"increasing" if s.value >= 60 else "decreasing" if s.value <= 40 else "stable" for s in velocity}
        trend = next(iter(trends)) if len(trends) == 1 else "unknown"
        status = {"increasing": MarketMotionStatus.ACCELERATING, "decreasing": MarketMotionStatus.DECELERATING,
                  "stable": MarketMotionStatus.STABLE}.get(trend, MarketMotionStatus.UNCERTAIN)
        names = {n.id: n.name for n in subgraph.nodes}
        adjacent = [f"Recorded {names.get(e.from_node_id, e.from_node_id)} {e.edge_type.value} {names.get(e.to_node_id, e.to_node_id)}"
                    for e in subgraph.edges if e.edge_type in {EdgeType.ADJACENT_TO, EdgeType.DEPENDS_ON, EdgeType.SERVES}]
        opposed = [f"Opposing stance recorded on relationship {e.id}; inspect its cited passage."
                   for e in subgraph.edges if e.qualifiers.get("stance") == "opposes"]
        customer = [o for o in subgraph.memory_observations if o.get("observation_type") == "customer_experience"]
        actions = [o for o in subgraph.memory_observations if o.get("observation_type") == "company_action"]
        gaps = [f"No {kind.value} measurement in scope." for kind in ScoreType if not groups[kind]]
        if len(trends) > 1:
            gaps.append("Recorded propositions have mixed velocity directions; no aggregate market direction established.")
        gaps.append("Company action acceleration has no comparable event-rate baseline. Belief velocity is discussion activity, not market adoption.")
        confidence = groups[ScoreType.EVIDENCE_CONFIDENCE]
        return MarketMotion(status=status, velocity_trend=trend,
            actor_lead_signal=metric(ScoreType.ACTOR_LEAD), actor_influence_signal=metric(ScoreType.ACTOR_INFLUENCE),
            belief_diversity_signal=metric(ScoreType.BELIEF_DIVERSITY), action_conversion_signal=metric(ScoreType.ACTION_CONVERSION),
            evidence_confidence_score=round(sum(s.value for s in confidence) / len(confidence), 2) if confidence else None,
            customer_perception_signal=f"{len(customer)} customer-experience candidates/records; sentiment and representativeness require review.",
            company_action_acceleration=f"{len(actions)} company-action candidates/records. Acceleration unknown without a baseline.",
            adjacent_market_signals=adjacent, contradictory_signals=opposed, coverage_gaps=gaps,
            evidence_breakdown=[metric(ScoreType.BELIEF_VELOCITY), f"{len(subgraph.evidence)} retained evidence records.",
                                "Motion status describes recorded belief velocity only; no company growth or demand conclusion follows."],
            as_of=as_of or datetime.now(UTC))
