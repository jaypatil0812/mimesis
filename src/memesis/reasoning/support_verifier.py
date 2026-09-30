"""Optional, non-blocking assessment of claim-to-evidence support."""

from __future__ import annotations

import json
import time
from typing import Any

import httpx
from pydantic import BaseModel, Field

from memesis.config import settings
from memesis.reasoning.contracts import ClaimStatement, EpistemicStatus, ReasoningOutput
from memesis.reasoning.contracts import IntelligencePacket


SUPPORT_STATUSES = {
    "SUPPORTED",
    "PARTIALLY_SUPPORTED",
    "CONTRADICTED",
    "INSUFFICIENT_EVIDENCE",
}
MAX_EVIDENCE_CHARS = 36_000
MAX_CHARS_PER_SOURCE = 6_000


class SupportVerificationResult(BaseModel):
    output: ReasoningOutput
    audit: dict[str, Any] = Field(default_factory=dict)
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: float = 0.0


class ClaimSupportVerifier:
    """Judge only whether cited sources bear on claims; never filter the answer.

    The external model is opt-in. Its assessment is advisory and is kept separate
    from epistemic status so a novel inference or hypothesis remains available to
    downstream analysis even when its sources only partially support it.
    """

    def verify(
        self, output: ReasoningOutput, packet: IntelligencePacket
    ) -> SupportVerificationResult:
        sections = (
            "what_is_happening",
            "who_matters",
            "what_they_believe",
            "company_actions",
            "perception",
            "what_changed",
            "adjacent_markets",
            "possible_implications",
            "contradictory_evidence",
        )
        evidence_by_id = {
            str(item.get("id")): item
            for item in packet.primary_evidence_references
            if item.get("id")
        }

        claim_refs: list[tuple[str, int, ClaimStatement]] = []
        updated_sections: dict[str, list[ClaimStatement]] = {}
        for section in sections:
            updated_sections[section] = []
            for index, claim in enumerate(getattr(output, section)):
                if claim.epistemic_status == EpistemicStatus.SPECULATIVE:
                    updated = claim.model_copy(update={
                        "evidence_support_status": "EXPLORATORY_NOT_TRUTH_VERIFIABLE",
                        "evidence_support_note": (
                            "This is a hypothesis. Its cited evidence can inform the idea, "
                            "but cannot establish the future or causal claim."
                        ),
                    })
                elif not any(str(eid) in evidence_by_id for eid in claim.evidence_ids):
                    updated = claim.model_copy(update={
                        "evidence_support_status": "NOT_CHECKED_NO_CITED_EVIDENCE",
                        "evidence_support_note": "No resolvable cited source was available to assess.",
                    })
                elif not (
                    settings.verify_claim_support
                    and settings.model_api_key
                    and settings.reason_strong_model
                ):
                    updated = claim.model_copy(update={
                        "evidence_support_status": "NOT_CHECKED_VERIFIER_DISABLED",
                        "evidence_support_note": (
                            "Citation exists; semantic support checking is opt-in and was not run."
                        ),
                    })
                else:
                    claim_refs.append((section, index, claim))
                    updated = claim
                updated_sections[section].append(updated)

        output = output.model_copy(update=updated_sections)
        if not claim_refs:
            audit = {
                "enabled": bool(settings.verify_claim_support),
                "provider_call_made": False,
                "claims_assessed": 0,
                "claims_not_checked": True,
                "reason": (
                    "no_cited_observed_or_inferred_claims"
                    if settings.verify_claim_support
                    else "opt_in_setting_disabled"
                ),
            }
            return self._with_audit(output, audit)

        request_items: list[dict[str, Any]] = []
        evidence_chars_left = MAX_EVIDENCE_CHARS
        for result_index, (section, claim_index, claim) in enumerate(claim_refs):
            citations = []
            for evidence_id in claim.evidence_ids:
                ref = evidence_by_id.get(str(evidence_id))
                if ref is None or evidence_chars_left <= 0:
                    continue
                text = str(ref.get("text") or "")
                excerpt = text[: min(MAX_CHARS_PER_SOURCE, evidence_chars_left)]
                evidence_chars_left -= len(excerpt)
                citations.append({
                    "evidence_id": str(evidence_id),
                    "source_url": str(ref.get("source_url") or ""),
                    "published_at": ref.get("published_at"),
                    "text": excerpt,
                    "excerpt_truncated": len(excerpt) < len(text),
                })
            request_items.append({
                "result_index": result_index,
                "section": section,
                "claim": claim.text,
                "epistemic_status": claim.epistemic_status.value,
                "cited_evidence": citations,
            })

        try:
            started = time.perf_counter()
            response = httpx.post(
                f"{settings.model_api_base_url.rstrip('/')}/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.model_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": settings.reason_strong_model,
                    "temperature": 0,
                    "response_format": {"type": "json_object"},
                    "messages": [
                        {"role": "system", "content": self._instructions()},
                        {"role": "user", "content": json.dumps(request_items, ensure_ascii=False)},
                    ],
                },
                timeout=settings.ingestion_request_timeout_seconds,
            )
            response.raise_for_status()
            body = response.json()
            parsed = json.loads(body["choices"][0]["message"]["content"])
            raw_results = parsed.get("results", [])
            usage = body.get("usage", {})
            latency_ms = round((time.perf_counter() - started) * 1000.0, 2)
        except Exception as exc:
            # Verification failure is visible but never turns into answer failure.
            for section, index, claim in claim_refs:
                updated_sections[section][index] = claim.model_copy(update={
                    "evidence_support_status": "VERIFICATION_UNAVAILABLE",
                    "evidence_support_note": f"Support check could not run ({type(exc).__name__}); claim retained.",
                })
            output = output.model_copy(update=updated_sections)
            return self._with_audit(
                output,
                {
                    "enabled": True,
                    "provider_call_made": True,
                    "provider": "openai_compatible",
                    "model": settings.reason_strong_model,
                    "claims_assessed": 0,
                    "error_type": type(exc).__name__,
                },
            )

        assessed: set[int] = set()
        for result in raw_results:
            if not isinstance(result, dict):
                continue
            try:
                result_index = int(result.get("result_index"))
            except (TypeError, ValueError):
                continue
            if result_index < 0 or result_index >= len(claim_refs):
                continue
            status = str(result.get("status", "")).upper()
            if status not in SUPPORT_STATUSES:
                continue
            section, index, claim = claim_refs[result_index]
            note = str(result.get("reason", ""))[:600]
            updated_sections[section][index] = claim.model_copy(update={
                "evidence_support_status": status,
                "evidence_support_note": note or None,
            })
            assessed.add(result_index)

        for result_index, (section, index, claim) in enumerate(claim_refs):
            if result_index not in assessed:
                updated_sections[section][index] = claim.model_copy(update={
                    "evidence_support_status": "VERIFICATION_UNRESOLVED",
                    "evidence_support_note": "Verifier returned no valid assessment; claim retained.",
                })

        output = output.model_copy(update=updated_sections)
        audit = {
            "enabled": True,
            "provider_call_made": True,
            "provider": "openai_compatible",
            "model": settings.reason_strong_model,
            "claims_assessed": len(assessed),
            "claims_submitted": len(claim_refs),
            "input_tokens": int(usage.get("prompt_tokens", 0)),
            "output_tokens": int(usage.get("completion_tokens", 0)),
            "latency_ms": latency_ms,
            "evidence_text_character_cap": MAX_EVIDENCE_CHARS,
            "claims_are_never_removed_or_rewritten": True,
        }
        return self._with_audit(output, audit)

    @staticmethod
    def _with_audit(
        output: ReasoningOutput, support_audit: dict[str, Any]
    ) -> SupportVerificationResult:
        citation_audit = {
            **output.citation_audit,
            "support_verification": support_audit,
        }
        output = output.model_copy(update={"citation_audit": citation_audit})
        return SupportVerificationResult(
            output=output,
            audit=support_audit,
            input_tokens=int(support_audit.get("input_tokens", 0)),
            output_tokens=int(support_audit.get("output_tokens", 0)),
            latency_ms=float(support_audit.get("latency_ms", 0.0)),
        )

    @staticmethod
    def _instructions() -> str:
        return (
            "Assess whether each cited source supports the specific claim. Return JSON only: "
            "{\"results\":[{\"result_index\":0,\"status\":\"SUPPORTED|PARTIALLY_SUPPORTED|"
            "CONTRADICTED|INSUFFICIENT_EVIDENCE\",\"reason\":\"brief explanation\"}]}. "
            "Judge only the source text provided for each claim. A citation existing is not support. "
            "Do not use outside knowledge, infer missing facts, rewrite claims, or treat correlation "
            "or sequence as causation. Use PARTIALLY_SUPPORTED when evidence supports only part of a "
            "claim, CONTRADICTED when it materially conflicts, and INSUFFICIENT_EVIDENCE when it is "
            "irrelevant or too weak. This is an advisory source-support assessment, not a truth score."
        )
