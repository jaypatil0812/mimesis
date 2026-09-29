"""Deep reasoning gate: routes between zero-model structured retrieval and deep synthesis."""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel

from memesis.reasoning.classifier import IntentType
from memesis.reasoning.decision_engine import DecisionEngine, DecisionType
from memesis.reasoning.planner import QueryPlan


class GateDecision(BaseModel):
    requires_deep_reasoning: bool
    reason: str
    direct_answer_strategy: str | None = None
    confidence: float = 1.0


class DeepReasoningGate:
    """Decides whether a question needs an expensive frontier reasoning model."""

    def __init__(self, decision_engine: DecisionEngine) -> None:
        self.decision_engine = decision_engine

    def evaluate(self, plan: QueryPlan) -> GateDecision:
        query = plan.intent.raw_query.strip()
        lower = query.lower()
        primary = plan.intent.primary_intent()

        # 1. Raw retrieval never requires deep reasoning
        if primary == IntentType.RAW_RETRIEVAL or re.search(r"\b(give me every|list all|every post|all posts)\b", lower):
            return GateDecision(
                requires_deep_reasoning=False,
                reason="Raw retrieval query requesting post/content dump; structured retrieval is sufficient.",
                direct_answer_strategy="raw_retrieval_formatter",
                confidence=1.0,
            )

        # 2. Direct actor lookup (e.g. "Who is driving the small-model narrative?", "Who are the top actors?")
        if primary == IntentType.ACTOR_ANALYSIS and not re.search(r"\b(why|how|should|implications|interpret)\b", lower):
            # Check if it's purely identifying driving actors
            if re.search(r"\b(who is driving|which people|who matters|key actors)\b", lower):
                return GateDecision(
                    requires_deep_reasoning=False,
                    reason="Actor attribution query resolvable directly from actor lead and influence scores.",
                    direct_answer_strategy="actor_ranking_formatter",
                    confidence=0.95,
                )

        # 3. Direct competitor action lookup (e.g. "What are competitors doing about inference cost?")
        if primary == IntentType.COMPETITOR_ANALYSIS and not re.search(r"\b(why|how|should|founder|implications)\b", lower):
            return GateDecision(
                requires_deep_reasoning=False,
                reason="Competitor action query answerable directly from recorded company launches, model releases, and events.",
                direct_answer_strategy="competitor_action_formatter",
                confidence=0.92,
            )

        # 4. Perception / developer pain lookup
        if primary == IntentType.PERCEPTION_ANALYSIS and not re.search(r"\b(why|what should|founder|implications)\b", lower):
            return GateDecision(
                requires_deep_reasoning=False,
                reason="Developer sentiment and friction query answerable directly from customer pain evidence spans.",
                direct_answer_strategy="perception_summary_formatter",
                confidence=0.90,
            )

        # 5. Temporal change query (e.g. "What changed during the last 30 days?")
        if "what changed" in lower and not re.search(r"\b(why|what should|founder)\b", lower):
            return GateDecision(
                requires_deep_reasoning=False,
                reason="Temporal delta query answerable directly by computing window differences on events, scores, and expressions.",
                direct_answer_strategy="temporal_delta_formatter",
                confidence=0.92,
            )

        # 6. Historical actor sequence (e.g. "Which people historically discussed this trend before companies began acting?")
        if "historically discussed" in lower or "before companies began acting" in lower:
            return GateDecision(
                requires_deep_reasoning=False,
                reason="Historical temporal sequence query answerable directly from PRECEDES edges and actor lead records.",
                direct_answer_strategy="historical_actor_sequence_formatter",
                confidence=0.92,
            )

        # 7. Counterevidence query (e.g. "What evidence contradicts the small-model thesis?")
        if "contradict" in lower or "counterevidence" in lower:
            return GateDecision(
                requires_deep_reasoning=False,
                reason="Counterevidence lookup answerable directly from opposing-stance assertions and qualification spans.",
                direct_answer_strategy="counterevidence_formatter",
                confidence=0.95,
            )

        # 8. Check Jev decision layer for consistency
        jev_res = self.decision_engine.evaluate(
            DecisionType.DEEP_REASONING_GATE,
            {"query": query, "intent": primary.value},
        )

        requires = jev_res.decision == "REQUIRES_DEEP_REASONING"
        return GateDecision(
            requires_deep_reasoning=requires,
            reason=f"Jev decision gate: {jev_res.decision} ({jev_res.metadata.get('reason', 'eval')})",
            direct_answer_strategy=None if requires else "direct_structured_formatter",
            confidence=jev_res.probability,
        )
