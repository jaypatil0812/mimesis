"""Evidence formatters and explicit routing to configured strategic reasoning."""
from __future__ import annotations
from typing import Any
from memesis.reasoning.contracts import ClaimStatement, EpistemicStatus, ReasoningOutput

SECTIONS = ("what_is_happening", "who_matters", "what_they_believe", "company_actions",
            "perception", "what_changed", "adjacent_markets", "possible_implications", "contradictory_evidence")

class ReasoningSynthesizer:
    def __init__(self, strong_model_adapter: Any = None):
        self.strong_model_adapter = strong_model_adapter

    def synthesize(self, packet, market_motion, gate, confidence):
        if not gate.requires_deep_reasoning:
            return self._format(packet, market_motion, gate.direct_answer_strategy, confidence)
        if self.strong_model_adapter is None:
            output = self._format(packet, market_motion, None, confidence)
            output.fallback_status = "REASONING_NOT_CONFIGURED"
            output.unknown_or_missing.append("Strategic interpretation requires a configured reasoning provider. Showing recorded evidence only.")
            output.reasoning_execution = {"status": "not_configured", "provider_call_attempted": False}
            return output
        try:
            output = self.strong_model_adapter.reason(packet, confidence)
            if not isinstance(output, ReasoningOutput):
                raise ValueError("Reasoning adapter must return ReasoningOutput")
            return output
        except Exception:
            output = self._format(packet, market_motion, None, confidence)
            execution = dict(getattr(self.strong_model_adapter, "last_execution", {}))
            execution.setdefault("status", "provider_failed")
            execution.setdefault("provider_call_attempted", True)
            output.reasoning_execution = execution
            output.fallback_status = execution["status"].upper()
            output.unknown_or_missing.append("Strategic reasoning could not complete. Showing recorded evidence only; retry or inspect provider configuration.")
            return output

    @staticmethod
    def _format(packet, motion, strategy, confidence):
        output = ReasoningOutput(
            summary=f"Retrieved {len(packet.primary_evidence_references)} source records within the requested scope. "
                    + (f"Recorded motion indicator: {motion.status.value}. " if motion else "")
                    + "The sections below describe records; they do not establish market-wide conclusions.",
            confidence=confidence, unknown_or_missing=list(packet.missing_information),
            evidence_references=[e["id"] for e in packet.primary_evidence_references],
            reasoning_execution={"status": "deterministic", "provider_call_attempted": False},
        )
        def records(items, label):
            return [ClaimStatement(
                text=f"{label}" + (f" [{item['review_state']}]" if item.get('review_state') else "")
                     + f": {item.get('statement', item.get('name', item.get('summary', '')))}",
                epistemic_status=EpistemicStatus.INFERRED if item.get("review_state") == "proposed" else EpistemicStatus.OBSERVED,
                evidence_ids=item.get("evidence_ids", [item["id"]] if label == "Source passage" else []),
                observation_ids=[item["id"]] if item.get("observation_type") else [],
                reasoning="This reports a stored record or attributed passage, not independent verification of its content.",
            ) for item in items]
        if strategy == "raw_retrieval_formatter":
            output.what_is_happening = records([{**e, "statement": e.get("text", "")} for e in packet.primary_evidence_references], "Source passage")
            return output
        if strategy in (None, "direct_structured_formatter"):
            output.what_is_happening = records([{**e, "statement": e.get("text", "")[:300]}
                for e in packet.primary_evidence_references[:3]], "Source passage")
        if strategy in (None, "direct_structured_formatter", "actor_ranking_formatter", "historical_actor_sequence_formatter"):
            actors = sorted(packet.key_actors, key=lambda a: max([s["value"] for s in packet.memesis_scores
                if s.get("subject_id") == a["id"] and s["type"] == "actor_influence"] or [-1]), reverse=True)
            output.who_matters = records(actors, "Recorded actor")
            output.what_they_believe = records(packet.key_beliefs, "Recorded proposition; see attribution links")
            for s in packet.memesis_scores:
                if s["type"] in {"actor_lead", "actor_influence"}:
                    output.who_matters.append(ClaimStatement(
                        text=f"{s['subject']}: {s['type']} = {s['value']}/100; formula {s['formula']}; as of {s['as_of']}.",
                        epistemic_status=EpistemicStatus.OBSERVED, evidence_ids=s.get("evidence_ids", []),
                        reasoning="Calculated from scoped recorded evidence. Timing and amplification do not prove causal influence."))
        if strategy in (None, "direct_structured_formatter", "competitor_action_formatter"):
            output.company_actions = records(packet.competitor_actions, "Recorded company action")
        if strategy in (None, "direct_structured_formatter", "perception_summary_formatter"):
            output.perception = records(packet.customer_public_perception, "Attributed perception")
        if strategy in (None, "direct_structured_formatter", "temporal_delta_formatter"):
            output.what_changed = records([{**r, "name": f"{r.get('published_at') or 'undated'}: {r['summary']}",
                "evidence_ids": [r["id"]]} for r in packet.recent_changes], "Record in requested window")
        if strategy in (None, "direct_structured_formatter"):
            output.adjacent_markets = records([{**r, "name": f"{r['from']} {r['type']} {r['to']}"}
                for r in packet.market_relationships], "Recorded relationship")
        if strategy in (None, "direct_structured_formatter", "counterevidence_formatter"):
            output.contradictory_evidence = records(packet.contradictory_evidence, "Recorded opposing or qualifying statement")
        if strategy == "historical_actor_sequence_formatter":
            output.what_is_happening = records([
                {**r, "name": f"{r['from']} {r['type']} {r['to']} (valid from {r['valid_from']})"}
                for r in packet.graph_relationships if r["type"] == "PRECEDES"], "Recorded temporal sequence")
        return output
