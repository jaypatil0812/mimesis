"""TypeSafe Jev & Heuristic Decision Engine layer for cheap, bounded evaluations."""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Protocol
import urllib.error
import urllib.request

from pydantic import BaseModel, Field

from memesis.config import settings
from memesis.retrieval.relevance import overlap, terms


class DecisionPrimitive(str, Enum):
    CHOICE = "CHOICE"
    SCORE = "SCORE"
    NOUL = "NOUL"


class DecisionType(str, Enum):
    # Core Phase 9 Decision Types
    CONTENT_RELEVANCE = "CONTENT_RELEVANCE"
    EVIDENCE_RELATION = "EVIDENCE_RELATION"
    BELIEF_EQUIVALENCE = "BELIEF_EQUIVALENCE"
    PERCEPTION_TYPE = "PERCEPTION_TYPE"
    SIGNAL_TYPE = "SIGNAL_TYPE"
    COMPANY_ACTION_RELEVANCE = "COMPANY_ACTION_RELEVANCE"
    DEEP_REASONING_GATE = "DEEP_REASONING_GATE"
    CLAIM_SUPPORT = "CLAIM_SUPPORT"

    # Pre-existing aliases / types
    RELEVANCE = "RELEVANCE"
    STANCE = "STANCE"
    PERCEPTION_CATEGORY = "PERCEPTION_CATEGORY"
    MARKET_SIGNAL = "MARKET_SIGNAL"
    COMPANY_ACTION_TYPE = "COMPANY_ACTION_TYPE"
    ACTOR_IMPORTANCE = "ACTOR_IMPORTANCE"
    EVIDENCE_DIRECTNESS = "EVIDENCE_DIRECTNESS"
    CHANGE_TYPE = "CHANGE_TYPE"


STANDARD_ALLOWED_OUTPUTS: dict[DecisionType, list[str]] = {
    DecisionType.CONTENT_RELEVANCE: ["RELEVANT", "IRRELEVANT", "UNCERTAIN"],
    DecisionType.RELEVANCE: ["RELEVANT", "IRRELEVANT", "UNCERTAIN"],
    DecisionType.EVIDENCE_RELATION: ["SUPPORT", "CONTRADICT", "MENTION", "NEITHER"],
    DecisionType.STANCE: ["SUPPORTS", "CONTRADICTS", "NEUTRAL"],
    DecisionType.BELIEF_EQUIVALENCE: ["SAME", "RELATED", "DIFFERENT", "UNCERTAIN"],
    DecisionType.PERCEPTION_TYPE: [
        "PAIN",
        "PRAISE",
        "FEATURE_REQUEST",
        "SWITCHING_INTENT",
        "PRICE_SENSITIVITY",
        "TRUST",
        "PERFORMANCE",
        "USABILITY",
        "USE_CASE",
        "OTHER",
    ],
    DecisionType.PERCEPTION_CATEGORY: ["CUSTOMER_PAIN", "FEATURE_REQUEST", "PRAISE", "OTHER"],
    DecisionType.SIGNAL_TYPE: ["STRUCTURAL_SIGNAL", "TEMPORARY_SIGNAL", "NOISE", "UNCERTAIN"],
    DecisionType.MARKET_SIGNAL: ["MARKET_SIGNAL", "NOISE", "UNCERTAIN"],
    DecisionType.COMPANY_ACTION_RELEVANCE: ["YES", "NO"],
    DecisionType.COMPANY_ACTION_TYPE: ["COMPETITOR_ACTION", "GENERAL_ACTIVITY"],
    DecisionType.DEEP_REASONING_GATE: ["REQUIRES_DEEP_REASONING", "DOES_NOT_REQUIRE"],
    DecisionType.CLAIM_SUPPORT: ["YES", "NO"],
    DecisionType.ACTOR_IMPORTANCE: ["IMPORTANT_ACTOR", "NORMAL_ACTOR", "UNKNOWN"],
    DecisionType.EVIDENCE_DIRECTNESS: ["DIRECT_EVIDENCE", "INDIRECT_EVIDENCE"],
    DecisionType.CHANGE_TYPE: ["STRUCTURAL_CHANGE", "TEMPORARY_CHANGE", "UNKNOWN"],
}

DECISION_PRIMITIVES: dict[DecisionType, DecisionPrimitive] = {
    DecisionType.CONTENT_RELEVANCE: DecisionPrimitive.CHOICE,
    DecisionType.RELEVANCE: DecisionPrimitive.CHOICE,
    DecisionType.EVIDENCE_RELATION: DecisionPrimitive.CHOICE,
    DecisionType.STANCE: DecisionPrimitive.CHOICE,
    DecisionType.BELIEF_EQUIVALENCE: DecisionPrimitive.CHOICE,
    DecisionType.PERCEPTION_TYPE: DecisionPrimitive.CHOICE,
    DecisionType.PERCEPTION_CATEGORY: DecisionPrimitive.CHOICE,
    DecisionType.SIGNAL_TYPE: DecisionPrimitive.CHOICE,
    DecisionType.MARKET_SIGNAL: DecisionPrimitive.CHOICE,
    DecisionType.COMPANY_ACTION_RELEVANCE: DecisionPrimitive.NOUL,
    DecisionType.COMPANY_ACTION_TYPE: DecisionPrimitive.CHOICE,
    DecisionType.DEEP_REASONING_GATE: DecisionPrimitive.NOUL,
    DecisionType.CLAIM_SUPPORT: DecisionPrimitive.NOUL,
    DecisionType.ACTOR_IMPORTANCE: DecisionPrimitive.CHOICE,
    DecisionType.EVIDENCE_DIRECTNESS: DecisionPrimitive.CHOICE,
    DecisionType.CHANGE_TYPE: DecisionPrimitive.CHOICE,
}


class DecisionResult(BaseModel):
    decision_type: DecisionType
    decision: str
    probability: float = Field(ge=0.0, le=1.0)
    probability_distribution: dict[str, float] = Field(default_factory=dict)
    primitive: DecisionPrimitive = DecisionPrimitive.CHOICE
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    confidence_bucket: str = "high"  # "high", "medium", "low"
    provider: str = "heuristic"  # "typesafe", "openrouter", "heuristic", "frontier"
    model: str
    version: str
    input_hash: str = ""
    input_references: list[str] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    latency_ms: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_estimate_usd: float = 0.0
    metadata: dict[str, Any] = Field(default_factory=dict)


class DecisionEngine(Protocol):
    def evaluate(
        self,
        decision_type: DecisionType,
        context: dict[str, Any],
        allowed_outputs: list[str] | None = None,
    ) -> DecisionResult: ...


def _assign_confidence_bucket(prob: float) -> str:
    if prob >= 0.80:
        return "high"
    elif prob >= 0.60:
        return "medium"
    return "low"


class HeuristicDecisionEngine:
    """Local deterministic hints, not model inference or calibrated truth scores."""

    VERSION = "market-neutral-heuristic-v1"

    def evaluate(
        self,
        decision_type: DecisionType,
        context: dict[str, Any],
        allowed_outputs: list[str] | None = None,
    ) -> DecisionResult:
        start_t = time.perf_counter()
        allowed = allowed_outputs or STANDARD_ALLOWED_OUTPUTS.get(decision_type, [])
        input_refs = [str(ref) for ref in context.get("references", [])]
        if not input_refs and "id" in context:
            input_refs = [str(context["id"])]

        method_name = f"_eval_{decision_type.value.lower()}"
        handler = getattr(self, method_name, None)
        if not handler:
            # Check alias
            if decision_type == DecisionType.CONTENT_RELEVANCE:
                handler = self._eval_relevance
            elif decision_type == DecisionType.EVIDENCE_RELATION:
                handler = self._eval_evidence_relation
            elif decision_type == DecisionType.PERCEPTION_TYPE:
                handler = self._eval_perception_type
            elif decision_type == DecisionType.SIGNAL_TYPE:
                handler = self._eval_signal_type
            elif decision_type == DecisionType.COMPANY_ACTION_RELEVANCE:
                handler = self._eval_company_action_relevance
            elif decision_type == DecisionType.CLAIM_SUPPORT:
                handler = self._eval_claim_support

        if handler:
            decision, prob, meta, dist = handler(context, allowed)
        else:
            decision, prob, meta, dist = (allowed[0] if allowed else "UNKNOWN", 0.5, {}, {})

        if allowed and decision not in allowed:
            decision = allowed[0]

        latency_ms = (time.perf_counter() - start_t) * 1000.0
        context_str = json.dumps(context, sort_keys=True, default=str)
        input_hash = hashlib.sha256(context_str.encode()).hexdigest()
        input_tokens = 0  # Local heuristics do not consume provider tokens.

        return DecisionResult(
            decision_type=decision_type,
            decision=decision,
            probability=prob,
            probability_distribution=dist,
            primitive=DECISION_PRIMITIVES.get(decision_type, DecisionPrimitive.CHOICE),
            confidence=prob,
            confidence_bucket=_assign_confidence_bucket(prob),
            provider="heuristic",
            model=self.VERSION,
            version=self.VERSION,
            input_hash=input_hash,
            input_references=input_refs,
            timestamp=datetime.now(UTC),
            latency_ms=round(latency_ms, 2),
            input_tokens=input_tokens,
            output_tokens=0,
            cost_estimate_usd=0.0,
            metadata=meta,
        )

    def _eval_relevance(
        self, ctx: dict[str, Any], allowed: list[str]
    ) -> tuple[str, float, dict[str, Any], dict[str, float]]:
        return self._query_relevance(ctx, allowed)

    def _query_relevance(self, ctx, allowed):
        text = f"{ctx.get('text', '')} {ctx.get('node_name', '')}"
        score = overlap(ctx.get("query", ""), text)
        supported_path = bool(ctx.get("supported_path"))
        decision = "RELEVANT" if score or supported_path else ("UNCERTAIN" if "UNCERTAIN" in allowed else "RELEVANT")
        probability = min(0.55 + score * 0.25, 0.8) if score else 0.5
        return decision, probability, {"basis": "query_overlap_hint_not_semantic_proof", "overlap": score,
            "supported_path": supported_path}, {decision: probability}

    def _eval_content_relevance(
        self, ctx: dict[str, Any], allowed: list[str]
    ) -> tuple[str, float, dict[str, Any], dict[str, float]]:
        return self._eval_relevance(ctx, allowed)

    def _eval_stance(
        self, ctx: dict[str, Any], allowed: list[str]
    ) -> tuple[str, float, dict[str, Any], dict[str, float]]:
        explicit = ctx.get("explicit_stance")
        if explicit in {"supports", "opposes", "qualifies", "mentions"}:
            if explicit == "supports":
                return "SUPPORTS", 0.98, {"source": "explicit_stance"}, {"SUPPORTS": 0.98, "CONTRADICTS": 0.01, "NEUTRAL": 0.01}
            elif explicit == "opposes":
                return "CONTRADICTS", 0.98, {"source": "explicit_stance"}, {"CONTRADICTS": 0.98, "SUPPORTS": 0.01, "NEUTRAL": 0.01}
            elif explicit == "qualifies":
                return "NEUTRAL", 0.85, {"source": "explicit_stance"}, {"NEUTRAL": 0.85, "SUPPORTS": 0.08, "CONTRADICTS": 0.07}

        return "NEUTRAL", 0.5, {"requires_semantic_review": True}, {"NEUTRAL": 0.5}

    def _eval_evidence_relation(self, ctx, allowed):
        stance = ctx.get("explicit_stance")
        decision = {"supports": "SUPPORT", "opposes": "CONTRADICT", "mentions": "MENTION", "qualifies": "MENTION"}.get(stance, "MENTION" if overlap(ctx.get("belief", ""), ctx.get("text", "")) else "NEITHER")
        return decision, 0.5, {"requires_semantic_review": stance is None}, {decision: 0.5}

    def _eval_belief_equivalence(
        self, ctx: dict[str, Any], allowed: list[str]
    ) -> tuple[str, float, dict[str, Any], dict[str, float]]:
        prop_a = str(ctx.get("proposition_a", "")).lower().strip()
        prop_b = str(ctx.get("proposition_b", "")).lower().strip()
        if prop_a == prop_b:
            dec = "SAME" if "SAME" in allowed else "SAME_BELIEF"
            dist = {dec: 1.0}
            return dec, 1.0, {"match": "exact"}, dist

        tokens_a = set(re.findall(r"\w+", prop_a))
        tokens_b = set(re.findall(r"\w+", prop_b))
        jaccard = len(tokens_a & tokens_b) / max(len(tokens_a | tokens_b), 1)

        if jaccard > 0.40:
            dec = "RELATED" if "RELATED" in allowed else "UNCERTAIN"
            prob = 0.75
        elif jaccard < 0.20:
            dec = "DIFFERENT" if "DIFFERENT" in allowed else "DIFFERENT_BELIEF"
            prob = round(1.0 - jaccard, 2)
        else:
            dec = "UNCERTAIN"
            prob = 0.60

        dist = {opt: (prob if opt == dec else round((1.0 - prob) / max(len(allowed) - 1, 1), 3)) for opt in allowed}
        return dec, prob, {"jaccard": jaccard}, dist

    def _eval_actor_importance(
        self, ctx: dict[str, Any], allowed: list[str]
    ) -> tuple[str, float, dict[str, Any], dict[str, float]]:
        lead_score = float(ctx.get("lead_score", 0.0))
        influence_score = float(ctx.get("influence_score", 0.0))
        degree = int(ctx.get("degree", 0))
        attributes = ctx.get("attributes", {})

        is_executive = any(
            k in str(attributes).lower() for k in ["ceo", "cto", "founder", "head of", "director"]
        )
        if lead_score > 40.0 or influence_score > 40.0 or is_executive or degree >= 4:
            prob = min(0.70 + 0.005 * (lead_score + influence_score), 0.99)
            dec = "IMPORTANT_ACTOR"
        else:
            prob = 0.80
            dec = "NORMAL_ACTOR"
        dist = {opt: (prob if opt == dec else round((1.0 - prob) / max(len(allowed) - 1, 1), 3)) for opt in allowed}
        return dec, prob, {"lead_score": lead_score, "influence_score": influence_score}, dist

    def _eval_market_signal(
        self, ctx: dict[str, Any], allowed: list[str]
    ) -> tuple[str, float, dict[str, Any], dict[str, float]]:
        event_type = str(ctx.get("event_type", "")).lower()
        text = str(ctx.get("text", "")).lower()

        commercial = {
            "product_launch",
            "model_release",
            "pricing_change",
            "deployment",
            "partnership",
            "investment",
        }
        if event_type in commercial or any(
            k in text for k in ["launched", "released", "announced pricing", "cut prices", "shipped"]
        ):
            prob = 0.95
            dec = "MARKET_SIGNAL"
        elif any(
            k in text for k in ["cookie", "subscribe", "panel", "discussion", "talked about", "conference"]
        ):
            prob = 0.90
            dec = "NOISE"
        else:
            prob = 0.65
            dec = "UNCERTAIN"
        dist = {opt: (prob if opt == dec else round((1.0 - prob) / max(len(allowed) - 1, 1), 3)) for opt in allowed}
        return dec, prob, {"type": "heuristic"}, dist

    def _eval_signal_type(
        self, ctx: dict[str, Any], allowed: list[str]
    ) -> tuple[str, float, dict[str, Any], dict[str, float]]:
        text = str(ctx.get("text", "")).lower()
        if any(w in text for w in ["architecture", "speculative decoding", "hardware", "silicon", "protocol", "standard"]):
            dec, prob = "STRUCTURAL_SIGNAL", 0.92
        elif any(w in text for w in ["hype", "demo", "viral", "weekend project", "toy"]):
            dec, prob = "TEMPORARY_SIGNAL", 0.85
        elif any(w in text for w in ["spam", "ad", "sponsor", "subscribe"]):
            dec, prob = "NOISE", 0.95
        else:
            dec, prob = "STRUCTURAL_SIGNAL" if "infrastructure" in text else "UNCERTAIN", 0.70
        dist = {opt: (prob if opt == dec else round((1.0 - prob) / max(len(allowed) - 1, 1), 3)) for opt in allowed}
        return dec, prob, {}, dist

    def _eval_deep_reasoning_gate(
        self, ctx: dict[str, Any], allowed: list[str]
    ) -> tuple[str, float, dict[str, Any], dict[str, float]]:
        query = str(ctx.get("query", "")).lower()
        intent = str(ctx.get("intent", ""))

        if intent == "RAW_RETRIEVAL" or re.search(r"\b(give me every|list all|every post|all posts|raw)\b", query):
            dec = "DOES_NOT_REQUIRE" if "DOES_NOT_REQUIRE" in allowed else "NO"
            prob = 1.0
        elif re.search(r"^(who are the \d+|what beliefs increased|which competitors launched|what evidence supports)\b", query):
            dec = "DOES_NOT_REQUIRE" if "DOES_NOT_REQUIRE" in allowed else "NO"
            prob = 0.95
        elif re.search(r"\b(why|how|should|what does this mean|implications|interpret|converging|structural rather than hype)\b", query):
            dec = "REQUIRES_DEEP_REASONING" if "REQUIRES_DEEP_REASONING" in allowed else "YES"
            prob = 0.95
        elif intent in {"STRATEGIC_DECISION", "MARKET_MOTION", "HISTORICAL_ANALOGUE"}:
            dec = "REQUIRES_DEEP_REASONING" if "REQUIRES_DEEP_REASONING" in allowed else "YES"
            prob = 0.90
        else:
            dec = "DOES_NOT_REQUIRE" if "DOES_NOT_REQUIRE" in allowed else "NO"
            prob = 0.75

        dist = {opt: (prob if opt == dec else round((1.0 - prob) / max(len(allowed) - 1, 1), 3)) for opt in allowed}
        return dec, prob, {"query": query}, dist

    def _eval_evidence_directness(
        self, ctx: dict[str, Any], allowed: list[str]
    ) -> tuple[str, float, dict[str, Any], dict[str, float]]:
        method = str(ctx.get("extraction_method", "")).lower()
        source_type = str(ctx.get("source_type", "")).lower()
        if method in {"source_explicit", "deterministic"} or source_type in {"web", "blog", "paper"}:
            dec, prob = "DIRECT_EVIDENCE", 0.95
        else:
            dec, prob = "INDIRECT_EVIDENCE", 0.80
        dist = {opt: (prob if opt == dec else round((1.0 - prob) / max(len(allowed) - 1, 1), 3)) for opt in allowed}
        return dec, prob, {"method": method}, dist

    def _eval_change_type(
        self, ctx: dict[str, Any], allowed: list[str]
    ) -> tuple[str, float, dict[str, Any], dict[str, float]]:
        action_count = int(ctx.get("action_count", 0))
        span_days = int(ctx.get("span_days", 0))
        if action_count >= 2 and span_days >= 30:
            dec, prob = "STRUCTURAL_CHANGE", 0.88
        elif action_count == 1:
            dec, prob = "TEMPORARY_CHANGE", 0.70
        else:
            dec, prob = "UNKNOWN", 0.60
        dist = {opt: (prob if opt == dec else round((1.0 - prob) / max(len(allowed) - 1, 1), 3)) for opt in allowed}
        return dec, prob, {"actions": action_count, "span_days": span_days}, dist

    def _eval_company_action_type(
        self, ctx: dict[str, Any], allowed: list[str]
    ) -> tuple[str, float, dict[str, Any], dict[str, float]]:
        subtype = str(ctx.get("subtype", "")).lower()
        if subtype in {"product_launch", "model_release", "pricing_change", "deployment", "partnership"}:
            dec, prob = "COMPETITOR_ACTION", 0.95
        else:
            dec, prob = "GENERAL_ACTIVITY", 0.85
        dist = {opt: (prob if opt == dec else round((1.0 - prob) / max(len(allowed) - 1, 1), 3)) for opt in allowed}
        return dec, prob, {"subtype": subtype}, dist

    def _eval_company_action_relevance(self, ctx, allowed):
        matched = overlap(ctx.get("belief", ctx.get("query", "")), ctx.get("text", ""))
        decision = "YES" if matched else "NO"
        return decision, 0.5, {"basis": "lexical_hint_requires_semantic_review"}, {decision: 0.5}

    def _eval_perception_category(
        self, ctx: dict[str, Any], allowed: list[str]
    ) -> tuple[str, float, dict[str, Any], dict[str, float]]:
        text = str(ctx.get("text", "")).lower()
        if any(w in text for w in ["expensive", "cost", "latency", "slow", "dislike", "frustrated", "hard to", "pain", "outage"]):
            dec, prob = "CUSTOMER_PAIN", 0.92
        elif any(w in text for w in ["feature", "wish", "please add", "support for", "router"]):
            dec, prob = "FEATURE_REQUEST", 0.85
        elif any(w in text for w in ["love", "great", "faster", "impressed", "seamless"]):
            dec, prob = "PRAISE", 0.85
        else:
            dec, prob = "OTHER", 0.70
        dist = {opt: (prob if opt == dec else round((1.0 - prob) / max(len(allowed) - 1, 1), 3)) for opt in allowed}
        return dec, prob, {}, dist

    def _eval_perception_type(
        self, ctx: dict[str, Any], allowed: list[str]
    ) -> tuple[str, float, dict[str, Any], dict[str, float]]:
        text = str(ctx.get("text", "")).lower()
        if any(w in text for w in ["expensive", "bill", "price", "token price", "cost per token", "over budget"]):
            dec, prob = "PRICE_SENSITIVITY", 0.94
        elif any(w in text for w in ["latency", "slow", "ttft", "tokens/sec", "throughput", "timeout", "delay"]):
            dec, prob = "PERFORMANCE", 0.93
        elif any(w in text for w in ["pain", "broken", "frustrating", "bug", "crash", "outage", "unreliable"]):
            dec, prob = "PAIN", 0.90
        elif any(w in text for w in ["switch", "migrated", "moved from", "replaced", "leaving", "ditching"]):
            dec, prob = "SWITCHING_INTENT", 0.92
        elif any(w in text for w in ["privacy", "security", "leak", "gdpr", "hipaa", "audit", "trust", "closed source"]):
            dec, prob = "TRUST", 0.88
        elif any(w in text for w in ["setup", "install", "docker", "config", "sdk", "python", "developer experience", "dx"]):
            dec, prob = "USABILITY", 0.89
        elif any(w in text for w in ["need", "feature", "wish", "roadmap", "rfc"]):
            dec, prob = "FEATURE_REQUEST", 0.87
        elif any(w in text for w in ["code generation", "summarization", "rag", "agent", "workflow", "production"]):
            dec, prob = "USE_CASE", 0.84
        elif any(w in text for w in ["love", "amazing", "smooth", "impressed", "huge fan", "best"]):
            dec, prob = "PRAISE", 0.90
        else:
            dec, prob = "OTHER", 0.70

        if dec not in allowed:
            dec = allowed[0]
        dist = {opt: (prob if opt == dec else round((1.0 - prob) / max(len(allowed) - 1, 1), 3)) for opt in allowed}
        return dec, prob, {}, dist

    def _eval_claim_support(self, ctx, allowed):
        # Rules cannot establish entailment from shared words.
        return "NO", 0.5, {"requires_semantic_review": True, "meaning": "support_not_established_by_rules"}, {"NO": 0.5}


class TypeSafeJevDecisionEngine:
    """Real TypeSafe AI Jev Decision Engine client targeting POST /v1/systemone

    Features:
    - Official /v1/systemone endpoint support
    - Native Jev primitives: CHOICE, SCORE, NOUL
    - Fallback to OpenRouter (typesafe-ai/jev-1.13) when configured
    - Explicit local rule fallback when API keys are absent; no model emulation
    - Full telemetry: probability distributions, confidence, input tokens, latency, cost ($0.042/M tokens)
    """

    PRICE_PER_M_INPUT_TOKENS = 0.042  # TypeSafe Jev pricing ($0.042 per 1M input tokens, free outputs)

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        openrouter_api_key: str | None = None,
    ) -> None:
        self.api_key = api_key or settings.typesafe_api_key or os.getenv("TYPESAFE_API_KEY")
        self.base_url = (base_url or settings.typesafe_base_url).rstrip("/")
        self.model = model or settings.typesafe_model or "jev-latest"
        self.openrouter_api_key = openrouter_api_key or settings.openrouter_api_key or os.getenv("OPENROUTER_API_KEY")
        self._heuristic_fallback = HeuristicDecisionEngine()

    def evaluate(
        self,
        decision_type: DecisionType,
        context: dict[str, Any],
        allowed_outputs: list[str] | None = None,
    ) -> DecisionResult:
        start_t = time.perf_counter()
        allowed = allowed_outputs or STANDARD_ALLOWED_OUTPUTS.get(decision_type, [])
        primitive = DECISION_PRIMITIVES.get(decision_type, DecisionPrimitive.CHOICE)

        input_refs = [str(ref) for ref in context.get("references", [])]
        if not input_refs and "id" in context:
            input_refs = [str(context["id"])]

        context_str = json.dumps(context, sort_keys=True, default=str)
        input_hash = hashlib.sha256(context_str.encode()).hexdigest()
        input_tokens = max(len(context_str) // 4, 1)

        self.request_receipts = []
        # 1. Attempt Official TypeSafe API
        if self.api_key:
            res = self._call_typesafe_api(decision_type, context, allowed, primitive, input_tokens)
            if res:
                res.metadata["request_receipts"] = list(self.request_receipts)
                return res

        # 2. Attempt OpenRouter Jev fallback
        if self.openrouter_api_key:
            res = self._call_openrouter_api(decision_type, context, allowed, primitive, input_tokens)
            if res:
                res.metadata["request_receipts"] = list(self.request_receipts)
                return res

        # 3. Explicit local fallback; no proprietary model emulation.
        dec, prob, meta, dist = self._jev_systemone_eval(decision_type, context, allowed)
        latency_ms = (time.perf_counter() - start_t) * 1000.0

        return DecisionResult(
            decision_type=decision_type,
            decision=dec,
            probability=prob,
            probability_distribution=dist,
            primitive=primitive,
            confidence=prob,
            confidence_bucket=_assign_confidence_bucket(prob),
            provider="jev-simulated",
            model=self.model,
            version=f"jev-{self.model}",
            input_hash=input_hash,
            input_references=input_refs,
            timestamp=datetime.now(UTC),
            latency_ms=round(latency_ms, 2),
            input_tokens=0,
            output_tokens=0,
            cost_estimate_usd=0.0,
            metadata={
                "primitive": primitive.value,
                "allowed_outputs": allowed,
                "offline_calibrated": False,
                "execution_mode": "simulation",
                "request_receipts": list(self.request_receipts),
                "provider_call_attempted": bool(self.api_key or self.openrouter_api_key),
                "provider_usage_available": False,
                "latency_semantics": "measured local fallback including attempted requests; not Jev inference latency",
                **meta,
            },
        )

    def _jev_systemone_eval(self, decision_type, ctx, allowed):
        """Local fallback; never claim to approximate proprietary model weights."""
        result = self._heuristic_fallback.evaluate(decision_type, ctx, allowed)
        return result.decision, result.probability, {"basis": "local_rules_not_model_inference"}, result.probability_distribution

    def _call_typesafe_api(self, decision_type, context, allowed, primitive, input_tokens):
        instructions = {
            DecisionType.RELEVANCE: "Does this record help answer the question, through direct evidence, counterevidence or a supported connecting path? No market is intrinsically relevant. Missing lexical overlap is not irrelevance.",
            DecisionType.CONTENT_RELEVANCE: "Does this content bear on the question, including contradictions, conditions and adjacent supported relationships?",
            DecisionType.BELIEF_EQUIVALENCE: "Compare complete propositions including subjects, negation, attribution, conditions and time. Shared vocabulary alone is not equivalence.",
            DecisionType.CLAIM_SUPPORT: "Does the cited evidence actually support the complete claim, preserving negation, scope and attribution? Citation existence is insufficient.",
            DecisionType.PERCEPTION_TYPE: "Classify only the attributable customer experience. Quotations and company marketing are not the author's experience.",
        }.get(decision_type, f"Evaluate {decision_type.value} using supplied state only. Preserve uncertainty, attribution, negation and conditions; do not infer causality from timing.")
        # Choice preserves the existing named application contract, including YES/NO labels.
        payload = {"model": self.model, "state": context, "questions": {"decision": {
            "type": "choice", "instructions": instructions,
            "criteria": {option: ("Insufficient evidence or ambiguous meaning" if option in {"UNCERTAIN", "UNKNOWN"} else option.replace("_", " ")) for option in allowed}}}}
        return self._request_decision(self.base_url.rstrip("/") + "/v1/systemone", self.api_key,
            payload, decision_type, context, allowed, typesafe=True)

    def _call_openrouter_api(self, decision_type, context, allowed, primitive, input_tokens):
        payload = {"model": "typesafe-ai/jev-1.13", "temperature": 0,
            "messages": [{"role": "user", "content": json.dumps({"task": decision_type.value,
                "instructions": "Judge only supplied evidence. Preserve scope, negation and attribution. No domain is inherently relevant. Missing keyword overlap does not disprove a supported connection. Return decision from allowed options and probability; use UNCERTAIN when available and unsupported.",
                "context": context, "allowed": allowed,
                "output": {"decision": "allowed option", "probability": "number 0..1"}})}]}
        return self._request_decision("https://openrouter.ai/api/v1/chat/completions", self.openrouter_api_key,
            payload, decision_type, context, allowed, typesafe=False)

    def _request_decision(self, url, key, payload, decision_type, context, allowed, *, typesafe):
        started = time.perf_counter()
        receipt = {"provider": "typesafe" if typesafe else "openrouter", "model": payload["model"],
            "status": "failed", "usage_source": "unavailable", "input_tokens": 0, "output_tokens": 0}
        self.request_receipts.append(receipt)
        data = json.dumps(payload).encode()
        request = urllib.request.Request(url, data=data, method="POST", headers={
            "Authorization": f"Bearer {key}", "Content-Type": "application/json", "User-Agent": "Memesis/0.1"})
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                body = json.loads(response.read().decode())
            usage = body.get("usage") or {}
            inp = usage.get("input_tokens" if typesafe else "prompt_tokens")
            out = usage.get("output_tokens" if typesafe else "completion_tokens")
            if type(inp) is int and type(out) is int and min(inp, out) >= 0:
                receipt.update(input_tokens=inp, output_tokens=out, usage_source="provider_reported")
            receipt.update(status="invalid_response", model=body.get("model", payload["model"]))
            if typesafe:
                answer = body["answers"]["decision"]
                decision, distribution = answer["choice"], answer["probabilities"]
                if set(distribution) != set(allowed) or any(type(v) not in (int, float) or not 0 <= v <= 1 for v in distribution.values()) or abs(sum(distribution.values()) - 1) > 0.02:
                    raise ValueError("Invalid choice distribution")
                probability = distribution[decision]
                confidence = float(answer["confidence"])
            else:
                answer = json.loads(body["choices"][0]["message"]["content"])
                decision, probability = answer["decision"], float(answer["probability"])
                distribution, confidence = {decision: probability}, probability
            if decision not in allowed or not 0 <= probability <= 1 or not 0 <= confidence <= 1:
                raise ValueError("Provider decision violates contract")
            receipt["status"] = "completed"
            return DecisionResult(decision_type=decision_type, decision=decision, probability=probability,
                probability_distribution=distribution, primitive=DecisionPrimitive.CHOICE, confidence=confidence,
                confidence_bucket=_assign_confidence_bucket(confidence), provider=receipt["provider"],
                model=receipt["model"], version="typed-decision-v1", input_hash=hashlib.sha256(json.dumps(context, sort_keys=True, default=str).encode()).hexdigest(),
                input_references=list(map(str, context.get("references", []))), latency_ms=round((time.perf_counter()-started)*1000, 2),
                input_tokens=receipt["input_tokens"], output_tokens=receipt["output_tokens"],
                metadata={"execution_mode": "live", "provider_call_succeeded": True,
                    "usage_source": receipt["usage_source"], "cost_source": "configured_rates_required",
                    "request_hash": hashlib.sha256(data).hexdigest(), "response_hash": hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest(),
                    "allowed_outputs": allowed})
        except Exception as error:
            receipt["error_type"] = type(error).__name__
            return None



class FrontierLLMDecisionEngine:
    """Legacy offline simulator. No frontier provider request is implemented."""

    VERSION = "frontier-simulation-v2"
    INPUT_COST_PER_M = 2.50
    OUTPUT_COST_PER_M = 10.00

    def __init__(self, api_key: str | None = None, base_url: str | None = None) -> None:
        self.api_key = api_key or settings.model_api_key
        self.base_url = (base_url or settings.model_api_base_url).rstrip("/")
        self._heuristic = HeuristicDecisionEngine()

    def evaluate(
        self,
        decision_type: DecisionType,
        context: dict[str, Any],
        allowed_outputs: list[str] | None = None,
    ) -> DecisionResult:
        start_t = time.perf_counter()
        allowed = allowed_outputs or STANDARD_ALLOWED_OUTPUTS.get(decision_type, [])
        context_str = json.dumps(context, sort_keys=True, default=str)
        input_tokens = max(len(context_str) // 4, 1) + 120
        output_tokens = 25

        jev_engine = TypeSafeJevDecisionEngine()
        dec, prob, meta, dist = jev_engine._jev_systemone_eval(decision_type, context, allowed)
        decision = dec

        latency_ms = (time.perf_counter() - start_t) * 1000.0

        dist = {
            opt: (prob if opt == decision else round((1.0 - prob) / max(len(allowed) - 1, 1), 3))
            for opt in allowed
        }

        return DecisionResult(
            decision_type=decision_type,
            decision=decision,
            probability=prob,
            probability_distribution=dist,
            primitive=DECISION_PRIMITIVES.get(decision_type, DecisionPrimitive.CHOICE),
            confidence=prob,
            confidence_bucket=_assign_confidence_bucket(prob),
            provider="frontier-simulated",
            model=self.VERSION,
            version=self.VERSION,
            input_hash=hashlib.sha256(context_str.encode()).hexdigest(),
            input_references=[str(r) for r in context.get("references", [])],
            timestamp=datetime.now(UTC),
            latency_ms=round(latency_ms, 2),
            input_tokens=0,
            output_tokens=0,
            cost_estimate_usd=0.0,
            metadata={"benchmark_class": "offline_simulation", "execution_mode": "simulation",
                "provider_call_attempted": False, "provider_usage_available": False,
                "latency_semantics": "measured local computation; not frontier inference latency", **meta},
        )


class HybridDecisionEngine:
    """Best-of-both decision engine:
    - Pure rule-based / instant evaluation for simple routing & gate lookups
    - TypeSafe Jev for bounded semantic judgments (relevance, signal, perception)
    - Escalation to frontier/secondary when confidence is low or equivalence is ambiguous
    """

    def __init__(
        self,
        heuristic_engine: HeuristicDecisionEngine | None = None,
        jev_engine: TypeSafeJevDecisionEngine | None = None,
        frontier_engine: FrontierLLMDecisionEngine | None = None,
        confidence_threshold: float = 0.70,
    ) -> None:
        self.heuristic = heuristic_engine or HeuristicDecisionEngine()
        self.jev = jev_engine or TypeSafeJevDecisionEngine()
        self.frontier = frontier_engine or FrontierLLMDecisionEngine()
        self.confidence_threshold = confidence_threshold

    VERSION = "hybrid-market-neutral-v1"

    def evaluate(
        self,
        decision_type: DecisionType,
        context: dict[str, Any],
        allowed_outputs: list[str] | None = None,
    ) -> DecisionResult:
        # 1. Deterministic / Fast Gates -> Heuristic
        fast_types = {
            DecisionType.DEEP_REASONING_GATE,
            DecisionType.ACTOR_IMPORTANCE,
            DecisionType.EVIDENCE_DIRECTNESS,
            DecisionType.CHANGE_TYPE,
            DecisionType.COMPANY_ACTION_TYPE,
        }
        if decision_type in fast_types:
            return self.heuristic.evaluate(decision_type, context, allowed_outputs)

        # 2. Semantic Bounded Judgments -> Jev
        jev_result = self.jev.evaluate(decision_type, context, allowed_outputs)

        # 3. Confidence Gating & Escalation
        if jev_result.probability >= self.confidence_threshold:
            return jev_result

        # A simulator cannot repair uncertainty from an actual provider.
        jev_result.metadata["needs_semantic_review"] = True

        return jev_result


class CachedDecisionEngine:
    """Decorates a DecisionEngine with in-memory caching and optional database persistence."""

    def __init__(self, engine: DecisionEngine, repository: Any = None) -> None:
        self.engine = engine
        self.repository = repository
        self._memory_cache: dict[str, DecisionResult] = {}
        self.cache_hits = 0
        self.decisions_made = 0
        self.usage_events: list[dict[str, Any]] = []

    def evaluate(
        self,
        decision_type: DecisionType,
        context: dict[str, Any],
        allowed_outputs: list[str] | None = None,
    ) -> DecisionResult:
        context_str = json.dumps(context, sort_keys=True, default=str)
        context_hash = hashlib.sha256(context_str.encode()).hexdigest()
        identity = {"class": type(self.engine).__name__, "version": getattr(self.engine, "VERSION", "quality-v1"),
                    "model": getattr(self.engine, "model", None), "base_url": getattr(self.engine, "base_url", None),
                    "credentials_present": bool(getattr(self.engine, "api_key", None)),
                    "openrouter_credentials_present": bool(getattr(self.engine, "openrouter_api_key", None)),
                    "jev_model": getattr(getattr(self.engine, "jev", None), "model", None),
                    "jev_url": getattr(getattr(self.engine, "jev", None), "base_url", None),
                    "jev_credentials_present": bool(getattr(getattr(self.engine, "jev", None), "api_key", None)
                        or getattr(getattr(self.engine, "jev", None), "openrouter_api_key", None))}
        contract = allowed_outputs or STANDARD_ALLOWED_OUTPUTS.get(decision_type, [])
        cache_key = hashlib.sha256(json.dumps(["decision-cache-v3-market-neutral", decision_type.value, context_hash, identity, contract], sort_keys=True).encode()).hexdigest()

        if cache_key in self._memory_cache:
            self.cache_hits += 1
            result = self._memory_cache[cache_key]
            return result.model_copy(update={"metadata": {**result.metadata, "cache_hit": True}})

        if self.repository and hasattr(self.repository, "get_decision_cache"):
            stored = self.repository.get_decision_cache(cache_key)
            if stored:
                self.cache_hits += 1
                res = DecisionResult.model_validate(stored["result"])
                self._memory_cache[cache_key] = res
                return res.model_copy(update={"metadata": {**res.metadata, "cache_hit": True}})

        self.decisions_made += 1
        result = self.engine.evaluate(decision_type, context, allowed_outputs)
        receipts = result.metadata.get("request_receipts", [])
        if not receipts and result.metadata.get("execution_mode") == "live":
            receipts = [{"provider": result.provider, "model": result.model,
                "status": "completed", "usage_source": result.metadata.get("usage_source", "unavailable"),
                "input_tokens": result.input_tokens, "output_tokens": result.output_tokens}]
        self.usage_events.extend(dict(receipt) for receipt in receipts)
        self._memory_cache[cache_key] = result

        if self.repository and hasattr(self.repository, "save_decision_cache"):
            self.repository.save_decision_cache(
                cache_key,
                {
                    "decision_type": decision_type.value,
                    "context_hash": context_hash,
                    "model": result.model,
                    "version": result.version,
                    "decision": result.decision,
                    "probability": result.probability,
                    "result": result.model_dump(mode="json"),
                },
            )

        return result


def get_decision_engine(
    mode: str | None = None, repository: Any = None
) -> CachedDecisionEngine:
    engine_mode = (mode or settings.decision_engine).lower()
    if engine_mode == "jev":
        base_engine: DecisionEngine = TypeSafeJevDecisionEngine()
    elif engine_mode == "heuristic":
        base_engine = HeuristicDecisionEngine()
    elif engine_mode == "frontier":
        base_engine = FrontierLLMDecisionEngine()
    else:  # "hybrid" (default)
        base_engine = HybridDecisionEngine()

    return CachedDecisionEngine(base_engine, repository=repository)
