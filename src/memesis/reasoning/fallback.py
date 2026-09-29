"""Fallback behaviors: handles empty, conflicting, unknown, and static scenarios."""

from __future__ import annotations

from typing import Any

from memesis.reasoning.contracts import (
    ClaimStatement,
    ConfidenceBreakdown,
    EpistemicStatus,
    IntelligencePacket,
    ReasoningOutput,
)
from memesis.retrieval.context_builder import MinimumSufficientSubgraph


class FallbackDetector:
    """Evaluates whether an investigation must gracefully return an explicit fallback status."""

    @staticmethod
    def check_fallback(
        packet: IntelligencePacket,
        subgraph: MinimumSufficientSubgraph,
        confidence: ConfidenceBreakdown,
    ) -> ReasoningOutput | None:
        query_lower = packet.question.lower()

        # 1. Unknown entity check
        for entity_name in packet.query_intent.entities:
            if not any(entity_name.lower() in n.name.lower() for n in subgraph.nodes):
                return ReasoningOutput(
                    summary=f"UNKNOWN: Entity '{entity_name}' does not exist in the Memesis graph or evidence ledger.",
                    what_is_happening=[],
                    who_matters=[],
                    what_they_believe=[],
                    company_actions=[],
                    perception=[],
                    what_changed=[],
                    historical_analogues=[],
                    adjacent_markets=[],
                    possible_implications=[],
                    contradictory_evidence=[],
                    unknown_or_missing=[f"Entity '{entity_name}' has no recorded nodes or observations."],
                    confidence=ConfidenceBreakdown(
                        overall_confidence=0.0,
                        evidence_quantity=0.0,
                        evidence_quality=0.0,
                        source_diversity=0.0,
                        source_independence=0.0,
                        entity_resolution_confidence=0.0,
                        temporal_consistency=1.0,
                        contradictory_evidence_balance=1.0,
                        graph_coverage=0.0,
                    ),
                    evidence_references=[],
                    fallback_status="UNKNOWN",
                )

        # 2. Insufficient Evidence check
        if len(subgraph.nodes) == 0 or len(subgraph.evidence) == 0:
            return ReasoningOutput(
                summary="INSUFFICIENT EVIDENCE: The evidence ledger contains insufficient recorded spans to answer this question.",
                what_is_happening=[],
                who_matters=[],
                what_they_believe=[],
                company_actions=[],
                perception=[],
                what_changed=[],
                historical_analogues=[],
                adjacent_markets=[],
                possible_implications=[],
                contradictory_evidence=[],
                unknown_or_missing=["No candidate nodes or evidence spans satisfied relevance filters."],
                confidence=ConfidenceBreakdown(
                    overall_confidence=0.0,
                    evidence_quantity=0.0,
                    evidence_quality=0.0,
                    source_diversity=0.0,
                    source_independence=0.0,
                    entity_resolution_confidence=0.0,
                    temporal_consistency=1.0,
                    contradictory_evidence_balance=1.0,
                    graph_coverage=0.0,
                ),
                evidence_references=[],
                fallback_status="INSUFFICIENT EVIDENCE",
            )

        # 3. No Meaningful Change Detected check
        if ("what changed" in query_lower or "last 30 days" in query_lower) and len(packet.recent_changes) == 0:
            return ReasoningOutput(
                summary="NO MEANINGFUL CHANGE DETECTED: No new company events, releases, or belief expressions were recorded in the specified observation window.",
                what_is_happening=[
                    ClaimStatement(
                        text="No delta observed across monitored sources in the requested time interval.",
                        epistemic_status=EpistemicStatus.OBSERVED,
                        evidence_ids=[],
                    )
                ],
                who_matters=[],
                what_they_believe=[],
                company_actions=[],
                perception=[],
                what_changed=[],
                historical_analogues=[],
                adjacent_markets=[],
                possible_implications=[],
                contradictory_evidence=[],
                unknown_or_missing=["No events registered in this timeframe."],
                confidence=confidence,
                evidence_references=[],
                fallback_status="NO MEANINGFUL CHANGE DETECTED",
            )

        return None
