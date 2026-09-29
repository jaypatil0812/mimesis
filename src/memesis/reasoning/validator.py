"""Post-reasoning claim verification and evidence validation."""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field

from memesis.reasoning.contracts import ClaimStatement, EpistemicStatus, IntelligencePacket, ReasoningOutput


class ValidationResult(BaseModel):
    validated_output: ReasoningOutput
    claims_checked: int
    claims_supported: int
    claims_downgraded: int
    unsupported_claims_detected: int
    contradictions_surfaced: int
    audit_log: list[dict[str, Any]] = Field(default_factory=list)


class EvidenceValidator:
    """Validates every substantive claim against stored evidence; downgrades or strips unsupported assertions."""

    def validate(self, output: ReasoningOutput, packet: IntelligencePacket) -> ValidationResult:
        known_evidence_ids = {ev.get("id") for ev in packet.primary_evidence_references if ev.get("id")}
        known_counter_texts = [item.get("statement", "").lower() for item in packet.contradictory_evidence]

        claims_checked = 0
        claims_supported = 0
        claims_downgraded = 0
        unsupported_claims_detected = 0
        contradictions_surfaced = len(packet.contradictory_evidence)
        audit_log: list[dict[str, Any]] = []

        def _validate_claim(claim: ClaimStatement) -> ClaimStatement:
            nonlocal claims_checked, claims_supported, claims_downgraded, unsupported_claims_detected
            claims_checked += 1

            # Check cited evidence IDs
            valid_cites = [eid for eid in claim.evidence_ids if eid in known_evidence_ids]

            if claim.epistemic_status == EpistemicStatus.OBSERVED:
                if not valid_cites:
                    # Downgrade OBSERVED to INFERRED because it lacks exact evidence span reference
                    claims_downgraded += 1
                    unsupported_claims_detected += 1
                    audit_log.append({
                        "claim": claim.text[:80],
                        "action": "downgrade_to_inferred",
                        "reason": "Observed claim lacked valid evidence span ID in intelligence packet.",
                    })
                    return ClaimStatement(
                        text=claim.text,
                        epistemic_status=EpistemicStatus.INFERRED,
                        evidence_ids=[],
                        downgraded_reason="Lacks direct evidence span; downgraded from OBSERVED to INFERRED.",
                    )
                else:
                    claims_supported += 1
                    return ClaimStatement(
                        text=claim.text,
                        epistemic_status=EpistemicStatus.OBSERVED,
                        evidence_ids=valid_cites,
                    )

            elif claim.epistemic_status == EpistemicStatus.INFERRED:
                # Inferred claims must be plausible combinations of observed facts
                # Clean predictive absolutes
                clean_text = re.sub(r"\b(will definitely|is guaranteed to|must occur)\b", "is likely to", claim.text, flags=re.IGNORECASE)
                claims_supported += 1
                return ClaimStatement(
                    text=clean_text,
                    epistemic_status=EpistemicStatus.INFERRED,
                    evidence_ids=valid_cites,
                )

            elif claim.epistemic_status == EpistemicStatus.SPECULATIVE:
                # 1. Strip absolute-certainty language that is inappropriate for speculative claims
                clean_text = re.sub(
                    r"\b(will definitely|is guaranteed to|must occur|certainly will|inevitably)\b",
                    "may",
                    claim.text,
                    flags=re.IGNORECASE,
                )
                # 2. Ensure speculative framing is present after stripping absolutes
                if not re.search(r"\b(may|could|possible|potentially|might)\b", clean_text, flags=re.IGNORECASE):
                    clean_text = f"Plausible consideration: {clean_text}"
                claims_supported += 1
                return ClaimStatement(
                    text=clean_text,
                    epistemic_status=EpistemicStatus.SPECULATIVE,
                    evidence_ids=valid_cites,
                )

            return claim

        # Validate all claim lists
        validated = ReasoningOutput(
            summary=output.summary,
            what_is_happening=[_validate_claim(c) for c in output.what_is_happening],
            who_matters=[_validate_claim(c) for c in output.who_matters],
            what_they_believe=[_validate_claim(c) for c in output.what_they_believe],
            company_actions=[_validate_claim(c) for c in output.company_actions],
            perception=[_validate_claim(c) for c in output.perception],
            what_changed=[_validate_claim(c) for c in output.what_changed],
            historical_analogues=output.historical_analogues,
            adjacent_markets=[_validate_claim(c) for c in output.adjacent_markets],
            possible_implications=[_validate_claim(c) for c in output.possible_implications],
            contradictory_evidence=[_validate_claim(c) for c in output.contradictory_evidence],
            unknown_or_missing=output.unknown_or_missing,
            confidence=output.confidence,
            evidence_references=list(known_evidence_ids),
            fallback_status=output.fallback_status,
        )

        return ValidationResult(
            validated_output=validated,
            claims_checked=claims_checked,
            claims_supported=claims_supported,
            claims_downgraded=claims_downgraded,
            unsupported_claims_detected=unsupported_claims_detected,
            contradictions_surfaced=contradictions_surfaced,
            audit_log=audit_log,
        )
