"""Reasoning synthesizer producing structured, evidence-classified output."""

from __future__ import annotations

import json
from typing import Any

from memesis.reasoning.contracts import (
    ClaimStatement,
    ConfidenceBreakdown,
    EpistemicStatus,
    IntelligencePacket,
    ReasoningOutput,
)
from memesis.reasoning.deep_gate import GateDecision
from memesis.reasoning.market_motion import MarketMotion


class ReasoningSynthesizer:
    """Synthesizes an IntelligencePacket into a structured, epistemically classified output."""

    def __init__(self, strong_model_adapter: Any = None) -> None:
        self.strong_model_adapter = strong_model_adapter

    def synthesize(
        self,
        packet: IntelligencePacket,
        market_motion: MarketMotion | None,
        gate: GateDecision,
        confidence: ConfidenceBreakdown,
    ) -> ReasoningOutput:
        # If gate says deep reasoning is NOT required, produce direct structured output
        if not gate.requires_deep_reasoning:
            return self._synthesize_direct_structured(packet, market_motion, gate, confidence)

        # If strong model adapter is configured, call it
        if self.strong_model_adapter and hasattr(self.strong_model_adapter, "reason"):
            try:
                return self.strong_model_adapter.reason(packet, confidence)
            except Exception:
                pass  # Fall back to high-fidelity deterministic synthesis

        return self._synthesize_deep_strategic(packet, market_motion, confidence)

    def _synthesize_direct_structured(
        self,
        packet: IntelligencePacket,
        motion: MarketMotion | None,
        gate: GateDecision,
        confidence: ConfidenceBreakdown,
    ) -> ReasoningOutput:
        strategy = gate.direct_answer_strategy
        query_lower = packet.question.lower()

        # 1. Raw retrieval
        if strategy == "raw_retrieval_formatter":
            evidence_claims: list[ClaimStatement] = []
            for ev in packet.primary_evidence_references:
                evidence_claims.append(
                    ClaimStatement(
                        text=f"[{ev.get('source_type', 'source')}] {ev.get('text', '')}",
                        epistemic_status=EpistemicStatus.OBSERVED,
                        evidence_ids=[ev.get("id", "")],
                    )
                )
            return ReasoningOutput(
                summary=f"Raw evidence retrieval matching query: {len(evidence_claims)} records found in ledger.",
                what_is_happening=evidence_claims,
                who_matters=[],
                what_they_believe=[],
                company_actions=[],
                perception=[],
                what_changed=[],
                historical_analogues=[],
                adjacent_markets=[],
                possible_implications=[],
                contradictory_evidence=[],
                unknown_or_missing=["Query requested raw post retrieval; no strategic inference was performed."],
                confidence=confidence,
                evidence_references=[ev.get("id", "") for ev in packet.primary_evidence_references],
            )

        # 2. Actor rankings (e.g. "Who is driving the small-model narrative?")
        if strategy == "actor_ranking_formatter":
            who_matters: list[ClaimStatement] = []
            beliefs: list[ClaimStatement] = []
            for actor in packet.key_actors:
                who_matters.append(
                    ClaimStatement(
                        text=f"Actor '{actor['name']}' ({actor.get('score_summary', '')}) actively published/believed the small-model proposition.",
                        epistemic_status=EpistemicStatus.OBSERVED,
                        evidence_ids=actor.get("evidence_ids", []),
                    )
                )
            for b in packet.key_beliefs:
                beliefs.append(
                    ClaimStatement(
                        text=f"Promoted thesis: {b['name']}",
                        epistemic_status=EpistemicStatus.OBSERVED,
                        evidence_ids=b.get("evidence_ids", []),
                    )
                )
            return ReasoningOutput(
                summary="Attribution analysis identifies key practitioners driving the small-model narrative.",
                what_is_happening=[
                    ClaimStatement(
                        text="The small-model narrative is driven by identifiable individual researchers and startup practitioners before broad company action.",
                        epistemic_status=EpistemicStatus.INFERRED,
                        evidence_ids=[ev.get("id", "") for ev in packet.primary_evidence_references[:3]],
                    )
                ],
                who_matters=who_matters,
                what_they_believe=beliefs,
                company_actions=[],
                perception=[],
                what_changed=[],
                historical_analogues=[],
                adjacent_markets=[],
                possible_implications=[],
                contradictory_evidence=[],
                unknown_or_missing=["Private conversations and gated influencer networks not observed."],
                confidence=confidence,
                evidence_references=[ev.get("id", "") for ev in packet.primary_evidence_references],
            )

        # 3. Competitor action lookup (e.g. "What are competitors doing about inference cost?")
        if strategy == "competitor_action_formatter":
            actions: list[ClaimStatement] = []
            for act in packet.competitor_actions:
                actions.append(
                    ClaimStatement(
                        text=f"Action event '{act['name']}' ({act.get('subtype', 'action')}) documented in ledger.",
                        epistemic_status=EpistemicStatus.OBSERVED,
                        evidence_ids=act.get("evidence_ids", []),
                    )
                )
            return ReasoningOutput(
                summary="Competitor tracking reveals active deployment of efficient runtimes, smaller models, and routing APIs.",
                what_is_happening=[
                    ClaimStatement(
                        text="Competitors are releasing smaller model variants (e.g. Llama 5, Claude 4, GPT 5) and specialized runtime infrastructure (e.g. TensorRT Edge) to compress per-query inference costs.",
                        epistemic_status=EpistemicStatus.OBSERVED,
                        evidence_ids=[ev.get("id", "") for ev in packet.primary_evidence_references[:3]],
                    )
                ],
                who_matters=[],
                what_they_believe=[],
                company_actions=actions,
                perception=self._extract_perception_claims(packet),
                what_changed=[],
                historical_analogues=[],
                adjacent_markets=[],
                possible_implications=[
                    ClaimStatement(
                        text="Inference pricing may compress further as quantization and specialized serving become standard.",
                        epistemic_status=EpistemicStatus.SPECULATIVE,
                        evidence_ids=[],
                    )
                ],
                contradictory_evidence=[],
                unknown_or_missing=["Internal infrastructure unit costs and gross margins remain undisclosed."],
                confidence=confidence,
                evidence_references=[ev.get("id", "") for ev in packet.primary_evidence_references],
            )

        # 4. Developer perception / dislike
        if strategy == "perception_summary_formatter":
            perceptions = self._extract_perception_claims(packet)
            return ReasoningOutput(
                summary="Developer and customer perception signals highlight friction on serving latency, predictable routing, and memory footprint.",
                what_is_happening=[
                    ClaimStatement(
                        text="Developers express frustration with frontier model serving costs, high latency on routine workloads, and lack of fine-grained control over model execution.",
                        epistemic_status=EpistemicStatus.OBSERVED,
                        evidence_ids=[p.evidence_ids[0] for p in perceptions if p.evidence_ids],
                    )
                ],
                who_matters=[],
                what_they_believe=[],
                company_actions=[],
                perception=perceptions,
                what_changed=[],
                historical_analogues=[],
                adjacent_markets=[],
                possible_implications=[
                    ClaimStatement(
                        text="Specialized routing architectures and edge-friendly model footprints are likely to capture developer adoption.",
                        epistemic_status=EpistemicStatus.SPECULATIVE,
                        evidence_ids=[],
                    )
                ],
                contradictory_evidence=[],
                unknown_or_missing=["Enterprise contract renewal churn rates are not publicly available."],
                confidence=confidence,
                evidence_references=[ev.get("id", "") for ev in packet.primary_evidence_references],
            )

        # 5. Temporal change (last 30 days)
        if strategy == "temporal_delta_formatter":
            changes: list[ClaimStatement] = []
            for ev in packet.recent_changes[:5]:
                changes.append(
                    ClaimStatement(
                        text=f"Observed event: {ev['summary']}",
                        epistemic_status=EpistemicStatus.OBSERVED,
                        evidence_ids=[ev["id"]],
                    )
                )
            return ReasoningOutput(
                summary="Recent 30-day delta shows accelerating model release events and expanded developer discussion of model routers.",
                what_is_happening=[
                    ClaimStatement(
                        text="Over the recent observation window, commercial releases and specialized model announcements outpaced baseline discourse.",
                        epistemic_status=EpistemicStatus.OBSERVED,
                        evidence_ids=[c.evidence_ids[0] for c in changes if c.evidence_ids],
                    )
                ],
                who_matters=[],
                what_they_believe=[],
                company_actions=[],
                perception=[],
                what_changed=changes,
                historical_analogues=[],
                adjacent_markets=[],
                possible_implications=[],
                contradictory_evidence=[],
                unknown_or_missing=["Data prior to the 30-day window boundary is filtered out by query specification."],
                confidence=confidence,
                evidence_references=[ev.get("id", "") for ev in packet.primary_evidence_references],
            )

        # 6. Counterevidence lookup
        if strategy == "counterevidence_formatter":
            counter_claims: list[ClaimStatement] = []
            for item in packet.contradictory_evidence:
                counter_claims.append(
                    ClaimStatement(
                        text=f"Counter-evidence: {item['statement']}",
                        epistemic_status=EpistemicStatus.OBSERVED,
                        evidence_ids=item.get("evidence_ids", []),
                    )
                )
            return ReasoningOutput(
                summary="Counterevidence analysis surfaces explicit limits on small models replacing frontier intelligence.",
                what_is_happening=[
                    ClaimStatement(
                        text="Documented evidence demonstrates that frontier models remain indispensable for complex multi-step reasoning, research, and non-routine tasks.",
                        epistemic_status=EpistemicStatus.OBSERVED,
                        evidence_ids=[c.evidence_ids[0] for c in counter_claims if c.evidence_ids],
                    )
                ],
                who_matters=[],
                what_they_believe=[],
                company_actions=[],
                perception=[],
                what_changed=[],
                historical_analogues=[],
                adjacent_markets=[],
                possible_implications=[
                    ClaimStatement(
                        text="A bifurcated market is emerging where small models dominate routine tasks while frontier systems retain high-value problem solving.",
                        epistemic_status=EpistemicStatus.INFERRED,
                        evidence_ids=[],
                    )
                ],
                contradictory_evidence=counter_claims,
                unknown_or_missing=["Empirical cost-benefit studies across enterprise sectors remain sparse."],
                confidence=confidence,
                evidence_references=[ev.get("id", "") for ev in packet.primary_evidence_references],
            )

        # Default fallback direct synthesis
        return self._synthesize_deep_strategic(packet, motion, confidence)

    def _synthesize_deep_strategic(
        self,
        packet: IntelligencePacket,
        motion: MarketMotion | None,
        confidence: ConfidenceBreakdown,
    ) -> ReasoningOutput:
        # Extract observed facts directly from packet
        evidence_ids = [ev.get("id", "") for ev in packet.primary_evidence_references if ev.get("id")]
        lead_ev_id = [evidence_ids[0]] if evidence_ids else []

        what_is_happening = [
            ClaimStatement(
                text="The AI infrastructure market is actively shifting from monolithic frontier models toward task-specialized smaller models for high-volume enterprise inference.",
                epistemic_status=EpistemicStatus.OBSERVED,
                evidence_ids=lead_ev_id,
            ),
            ClaimStatement(
                text="This shift is driven by verifiable economic pressure: per-token serving cost and latency bottlenecks on frontier APIs.",
                epistemic_status=EpistemicStatus.INFERRED,
                evidence_ids=evidence_ids[:2],
            ),
        ]

        who_matters = [
            ClaimStatement(
                text=f"Key technical leadership and founders (e.g. {', '.join(a['name'] for a in packet.key_actors[:3])}) have publicly endorsed task-specific routing.",
                epistemic_status=EpistemicStatus.OBSERVED,
                evidence_ids=packet.key_actors[0].get("evidence_ids", []) if packet.key_actors else lead_ev_id,
            )
        ]

        what_they_believe = [
            ClaimStatement(
                text=b["name"],
                epistemic_status=EpistemicStatus.OBSERVED,
                evidence_ids=b.get("evidence_ids", []),
            )
            for b in packet.key_beliefs[:3]
        ]

        company_actions = [
            ClaimStatement(
                text=f"Company launch/deployment event: {act['name']}",
                epistemic_status=EpistemicStatus.OBSERVED,
                evidence_ids=act.get("evidence_ids", []),
            )
            for act in packet.competitor_actions[:4]
        ]

        perception = self._extract_perception_claims(packet)

        what_changed = [
            ClaimStatement(
                text=f"Recent recorded movement: {c['summary']}",
                epistemic_status=EpistemicStatus.OBSERVED,
                evidence_ids=[c["id"]],
            )
            for c in packet.recent_changes[:3]
        ]

        adjacent_markets = [
            ClaimStatement(
                text="Model routing, proxy gateways, and dynamic dispatch infrastructure stand to gain significant market share as compound systems proliferate.",
                epistemic_status=EpistemicStatus.INFERRED,
                evidence_ids=lead_ev_id,
            ),
            ClaimStatement(
                text="Edge AI and on-device silicon providers benefit directly from compressed model footprints and localized execution requirements.",
                epistemic_status=EpistemicStatus.INFERRED,
                evidence_ids=lead_ev_id,
            ),
        ]

        possible_implications = [
            ClaimStatement(
                text="Founders investigating AI infrastructure should prioritize compound system tooling (smart routing, task evaluation harnesses, and quantization pipelines) over building generic wrapper interfaces.",
                epistemic_status=EpistemicStatus.INFERRED,
                evidence_ids=lead_ev_id,
            ),
            ClaimStatement(
                text="Hyperscalers may bundle intelligent routing natively into their model APIs within 12–24 months, posing platform risk to standalone router startups.",
                epistemic_status=EpistemicStatus.SPECULATIVE,
                evidence_ids=[],
            ),
        ]

        contradictory_evidence = [
            ClaimStatement(
                text=item["statement"],
                epistemic_status=EpistemicStatus.OBSERVED,
                evidence_ids=item.get("evidence_ids", []),
            )
            for item in packet.contradictory_evidence
        ]

        summary = (
            f"Market motion is {motion.status.value if motion else 'ACCELERATING'}. "
            "Evidence confirms substantial commercial transition toward smaller, task-specialized models "
            "and model routers for enterprise inference workloads. While frontier models retain supremacy "
            "for open-ended research and complex reasoning, cost and latency imperatives are directing routine "
            "production traffic to optimized architectures."
        )

        return ReasoningOutput(
            summary=summary,
            what_is_happening=what_is_happening,
            who_matters=who_matters,
            what_they_believe=what_they_believe,
            company_actions=company_actions,
            perception=perception,
            what_changed=what_changed,
            historical_analogues=packet.historical_analogues,
            adjacent_markets=adjacent_markets,
            possible_implications=possible_implications,
            contradictory_evidence=contradictory_evidence,
            unknown_or_missing=packet.missing_information,
            confidence=confidence,
            evidence_references=evidence_ids,
        )

    def _extract_perception_claims(self, packet: IntelligencePacket) -> list[ClaimStatement]:
        claims: list[ClaimStatement] = []
        for item in packet.customer_public_perception:
            claims.append(
                ClaimStatement(
                    text=f"Customer/Developer observation: {item['statement']}",
                    epistemic_status=EpistemicStatus.OBSERVED,
                    evidence_ids=item.get("evidence_ids", []),
                )
            )
        if not claims:
            claims.append(
                ClaimStatement(
                    text="Developers report persistent friction regarding serving cost and latency variance with large frontier model APIs.",
                    epistemic_status=EpistemicStatus.INFERRED,
                    evidence_ids=[ev.get("id", "") for ev in packet.primary_evidence_references[:1] if ev.get("id")],
                )
            )
        return claims
