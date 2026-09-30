"""Post-reasoning claim verification and evidence validation."""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field

from memesis.reasoning.contracts import ClaimStatement, EpistemicStatus, IntelligencePacket, ReasoningOutput


class ValidationResult(BaseModel):
    validated_output: ReasoningOutput
    claims_checked: int
    claims_supported: int = Field(
        description="Legacy non-downgraded count; this does not mean semantic support was verified."
    )
    claims_with_valid_citations: int
    claims_without_valid_citations: int
    invalid_citations_removed: int
    claims_downgraded: int
    unsupported_claims_detected: int
    contradictions_surfaced: int
    audit_log: list[dict[str, Any]] = Field(default_factory=list)


class EvidenceValidator:
    """Checks citation integrity without suppressing exploratory analysis.

    A citation resolving to a packet record proves only that the source is available
    for inspection. This validator does not claim that the source semantically entails
    the attached claim; that remains a reviewer or separately evaluated verifier task.
    """

    def validate(self, output: ReasoningOutput, packet: IntelligencePacket) -> ValidationResult:
        known_evidence_ids = {
            str(ev.get("id"))
            for ev in packet.primary_evidence_references
            if ev.get("id")
        }

        claims_checked = 0
        claims_supported = 0
        claims_with_valid_citations = 0
        claims_without_valid_citations = 0
        invalid_citations_removed = 0
        claims_downgraded = 0
        unsupported_claims_detected = 0
        contradictions_surfaced = len(packet.contradictory_evidence)
        audit_log: list[dict[str, Any]] = []

        def _validate_claim(claim: ClaimStatement) -> ClaimStatement:
            nonlocal claims_checked, claims_supported, claims_with_valid_citations
            nonlocal claims_without_valid_citations, invalid_citations_removed
            nonlocal claims_downgraded, unsupported_claims_detected
            claims_checked += 1

            # Keep only references the answer packet can actually resolve.
            original_cites = [str(eid) for eid in claim.evidence_ids]
            valid_cites = list(
                dict.fromkeys(eid for eid in original_cites if eid in known_evidence_ids)
            )
            removed_cites = len(original_cites) - len(valid_cites)
            invalid_citations_removed += removed_cites
            if valid_cites:
                claims_with_valid_citations += 1
                link_status = "linked_not_semantically_verified"
            else:
                claims_without_valid_citations += 1
                link_status = "invalid_citation_removed" if original_cites else "uncited_exploration"

            if claim.epistemic_status == EpistemicStatus.OBSERVED:
                if not valid_cites:
                    # Downgrade OBSERVED because it lacks a resolvable source record.
                    claims_downgraded += 1
                    unsupported_claims_detected += 1
                    audit_log.append({
                        "claim": claim.text[:80],
                        "action": "downgrade_to_inferred",
                        "reason": "Observed claim lacked a resolvable source record in the intelligence packet.",
                    })
                    return ClaimStatement(
                        text=claim.text,
                        epistemic_status=EpistemicStatus.INFERRED,
                        evidence_ids=[],
                        downgraded_reason="No resolvable source record; retained as an inference.",
                        evidence_link_status=link_status,
                    )
                else:
                    claims_supported += 1
                    return ClaimStatement(
                        text=claim.text,
                        epistemic_status=EpistemicStatus.OBSERVED,
                        evidence_ids=valid_cites,
                        downgraded_reason=claim.downgraded_reason,
                        evidence_link_status=link_status,
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
                    downgraded_reason=claim.downgraded_reason,
                    evidence_link_status=link_status,
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
                    downgraded_reason=(
                        claim.downgraded_reason
                        or ("Exploratory hypothesis; no evidence link was retrieved." if not valid_cites else None)
                    ),
                    evidence_link_status=("exploratory_uncited" if not valid_cites else link_status),
                )

            return claim

        # Validate all claim lists
        validated = ReasoningOutput(
            summary=output.summary,
            query_scope=output.query_scope,
            coverage=output.coverage,
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
            evidence_references=sorted(known_evidence_ids),
            fallback_status=output.fallback_status,
            summary_evidence_ids=sorted({
                evidence_id
                for section in (
                    output.what_is_happening,
                    output.who_matters,
                    output.what_they_believe,
                    output.company_actions,
                    output.perception,
                    output.what_changed,
                    output.adjacent_markets,
                    output.possible_implications,
                    output.contradictory_evidence,
                )
                for claim in section
                for evidence_id in claim.evidence_ids
                if evidence_id in known_evidence_ids
            } | {
                evidence_id
                for analogue in output.historical_analogues
                for evidence_id in analogue.current_evidence_ids
                if evidence_id in known_evidence_ids
            }),
            citation_audit={
                "claims_checked": claims_checked,
                "claims_with_valid_citations": claims_with_valid_citations,
                "claims_without_valid_citations": claims_without_valid_citations,
                "invalid_citations_removed": invalid_citations_removed,
                "citation_links_are_not_semantic_support_verification": True,
                "exploratory_claims_preserved": True,
            },
        )

        return ValidationResult(
            validated_output=validated,
            claims_checked=claims_checked,
            claims_supported=claims_supported,
            claims_with_valid_citations=claims_with_valid_citations,
            claims_without_valid_citations=claims_without_valid_citations,
            invalid_citations_removed=invalid_citations_removed,
            claims_downgraded=claims_downgraded,
            unsupported_claims_detected=unsupported_claims_detected,
            contradictions_surfaced=contradictions_surfaced,
            audit_log=audit_log,
        )
