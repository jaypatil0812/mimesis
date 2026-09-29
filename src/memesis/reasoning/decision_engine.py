"""Jev-style typed decision engine layer for cheap, bounded evaluations."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Protocol

from pydantic import BaseModel, Field


class DecisionType(str, Enum):
    RELEVANCE = "RELEVANCE"
    STANCE = "STANCE"
    BELIEF_EQUIVALENCE = "BELIEF_EQUIVALENCE"
    ACTOR_IMPORTANCE = "ACTOR_IMPORTANCE"
    MARKET_SIGNAL = "MARKET_SIGNAL"
    DEEP_REASONING_GATE = "DEEP_REASONING_GATE"
    EVIDENCE_DIRECTNESS = "EVIDENCE_DIRECTNESS"
    CHANGE_TYPE = "CHANGE_TYPE"
    COMPANY_ACTION_TYPE = "COMPANY_ACTION_TYPE"
    PERCEPTION_CATEGORY = "PERCEPTION_CATEGORY"


STANDARD_ALLOWED_OUTPUTS: dict[DecisionType, list[str]] = {
    DecisionType.RELEVANCE: ["RELEVANT", "IRRELEVANT"],
    DecisionType.STANCE: ["SUPPORTS", "CONTRADICTS", "NEUTRAL"],
    DecisionType.BELIEF_EQUIVALENCE: ["SAME_BELIEF", "DIFFERENT_BELIEF", "UNCERTAIN"],
    DecisionType.ACTOR_IMPORTANCE: ["IMPORTANT_ACTOR", "NORMAL_ACTOR", "UNKNOWN"],
    DecisionType.MARKET_SIGNAL: ["MARKET_SIGNAL", "NOISE", "UNCERTAIN"],
    DecisionType.DEEP_REASONING_GATE: ["REQUIRES_DEEP_REASONING", "DOES_NOT_REQUIRE"],
    DecisionType.EVIDENCE_DIRECTNESS: ["DIRECT_EVIDENCE", "INDIRECT_EVIDENCE"],
    DecisionType.CHANGE_TYPE: ["STRUCTURAL_CHANGE", "TEMPORARY_CHANGE", "UNKNOWN"],
    DecisionType.COMPANY_ACTION_TYPE: ["COMPETITOR_ACTION", "GENERAL_ACTIVITY"],
    DecisionType.PERCEPTION_CATEGORY: ["CUSTOMER_PAIN", "FEATURE_REQUEST", "PRAISE", "OTHER"],
}


class DecisionResult(BaseModel):
    decision_type: DecisionType
    decision: str
    probability: float = Field(ge=0.0, le=1.0)
    model: str
    version: str
    input_references: list[str] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = Field(default_factory=dict)


class DecisionEngine(Protocol):
    def evaluate(
        self,
        decision_type: DecisionType,
        context: dict[str, Any],
        allowed_outputs: list[str] | None = None,
    ) -> DecisionResult: ...


class HeuristicDecisionEngine:
    """Fast, deterministic, rule-based typed evaluator representing Jev heuristics."""

    VERSION = "jev-heuristic-v0.1"

    def evaluate(
        self,
        decision_type: DecisionType,
        context: dict[str, Any],
        allowed_outputs: list[str] | None = None,
    ) -> DecisionResult:
        allowed = allowed_outputs or STANDARD_ALLOWED_OUTPUTS.get(decision_type, [])
        input_refs = [str(ref) for ref in context.get("references", [])]
        if not input_refs and "id" in context:
            input_refs = [str(context["id"])]

        handler = getattr(self, f"_eval_{decision_type.value.lower()}", None)
        if handler:
            decision, prob, meta = handler(context)
        else:
            decision, prob, meta = allowed[0] if allowed else "UNKNOWN", 0.5, {}

        if allowed and decision not in allowed:
            decision = allowed[0]

        return DecisionResult(
            decision_type=decision_type,
            decision=decision,
            probability=prob,
            model=self.VERSION,
            version=self.VERSION,
            input_references=input_refs,
            timestamp=datetime.now(UTC),
            metadata=meta,
        )

    def _eval_relevance(self, ctx: dict[str, Any]) -> tuple[str, float, dict[str, Any]]:
        query = str(ctx.get("query", "")).lower()
        text = str(ctx.get("text", "")).lower()
        node_name = str(ctx.get("node_name", "")).lower()
        combined = f"{text} {node_name}"

        # Stop words removal for simple token match
        tokens = [t for t in re.findall(r"\w+", query) if len(t) > 2 and t not in {"the", "and", "are", "what", "which", "who", "about", "for", "with"}]
        matches = [t for t in tokens if t in combined or any(t.startswith(part) or part.startswith(t) for part in re.findall(r"\w+", combined))]
        
        # Check topic relevance
        topic_terms = ["small", "model", "specialized", "inference", "cost", "routing", "latency", "router", "quantiz"]
        if matches or any(term in combined for term in topic_terms):
            return "RELEVANT", min(0.5 + 0.1 * max(len(matches), 1), 0.99), {"matched_tokens": matches}
        return "IRRELEVANT", 0.90, {"matched_tokens": []}


    def _eval_stance(self, ctx: dict[str, Any]) -> tuple[str, float, dict[str, Any]]:
        # If explicit stance was stored on assertion/edge, honor it
        explicit = ctx.get("explicit_stance")
        if explicit in {"supports", "opposes", "qualifies", "mentions"}:
            if explicit == "supports":
                return "SUPPORTS", 0.98, {"source": "explicit_stance"}
            elif explicit == "opposes":
                return "CONTRADICTS", 0.98, {"source": "explicit_stance"}
            elif explicit == "qualifies":
                return "NEUTRAL", 0.85, {"source": "explicit_stance"}

        text = str(ctx.get("text", "")).lower()
        if re.search(r"\b(will not|cannot replace|not replace|never replace|fails to|disagree|contradicts|false)\b", text):
            return "CONTRADICTS", 0.92, {"rule": "negation_pattern"}
        if re.search(r"\b(will replace|replaces|reduce[sd]?\s+\w+\s+cost|reduce[sd]?\s+cost|reduce[sd]?\s+inference|gain share|more efficient|adopt|cheaper|faster|enable|task.specific|specialized)\b", text):
            return "SUPPORTS", 0.90, {"rule": "affirmation_pattern"}
        return "NEUTRAL", 0.70, {"rule": "neutral_fallback"}

    def _eval_belief_equivalence(self, ctx: dict[str, Any]) -> tuple[str, float, dict[str, Any]]:
        prop_a = str(ctx.get("proposition_a", "")).lower().strip()
        prop_b = str(ctx.get("proposition_b", "")).lower().strip()
        if prop_a == prop_b:
            return "SAME_BELIEF", 1.0, {"match": "exact"}
        
        # Normalized token similarity
        tokens_a = set(re.findall(r"\w+", prop_a))
        tokens_b = set(re.findall(r"\w+", prop_b))
        jaccard = len(tokens_a & tokens_b) / max(len(tokens_a | tokens_b), 1)
        if jaccard > 0.8:
            return "SAME_BELIEF", round(jaccard, 2), {"jaccard": jaccard}
        elif jaccard < 0.3:
            return "DIFFERENT_BELIEF", round(1.0 - jaccard, 2), {"jaccard": jaccard}
        return "UNCERTAIN", 0.60, {"jaccard": jaccard}

    def _eval_actor_importance(self, ctx: dict[str, Any]) -> tuple[str, float, dict[str, Any]]:
        lead_score = float(ctx.get("lead_score", 0.0))
        influence_score = float(ctx.get("influence_score", 0.0))
        degree = int(ctx.get("degree", 0))
        attributes = ctx.get("attributes", {})
        
        is_executive = any(k in str(attributes).lower() for k in ["ceo", "cto", "founder", "head of", "director"])
        if lead_score > 40.0 or influence_score > 40.0 or is_executive or degree >= 4:
            return "IMPORTANT_ACTOR", min(0.70 + 0.005 * (lead_score + influence_score), 0.99), {
                "lead_score": lead_score,
                "influence_score": influence_score,
                "is_executive": is_executive,
            }
        return "NORMAL_ACTOR", 0.80, {"lead_score": lead_score, "influence_score": influence_score}

    def _eval_market_signal(self, ctx: dict[str, Any]) -> tuple[str, float, dict[str, Any]]:
        event_type = str(ctx.get("event_type", "")).lower()
        text = str(ctx.get("text", "")).lower()
        
        commercial = {"product_launch", "model_release", "pricing_change", "deployment", "partnership", "investment"}
        if event_type in commercial or any(k in text for k in ["launched", "released", "announced pricing", "cut prices", "shipped"]):
            return "MARKET_SIGNAL", 0.95, {"type": "commercial_action"}
        if any(k in text for k in ["cookie", "subscribe", "panel", "discussion", "talked about", "conference"]):
            return "NOISE", 0.90, {"type": "boilerplate_or_meta"}
        return "UNCERTAIN", 0.60, {"type": "general"}

    def _eval_deep_reasoning_gate(self, ctx: dict[str, Any]) -> tuple[str, float, dict[str, Any]]:
        query = str(ctx.get("query", "")).lower()
        intent = str(ctx.get("intent", ""))

        # Raw retrieval or pure lookup
        if intent == "RAW_RETRIEVAL" or re.search(r"\b(give me every|list all|every post|all posts|raw)\b", query):
            return "DOES_NOT_REQUIRE", 1.0, {"reason": "raw_retrieval_request"}

        # Direct factual lookups
        if re.search(r"^(who are the \d+|what beliefs increased|which competitors launched|what evidence supports)\b", query):
            return "DOES_NOT_REQUIRE", 0.95, {"reason": "structured_data_lookup"}

        # Strategic / causal / synthesis queries
        if re.search(r"\b(why|how|should|what does this mean|what should .* investigate|implications|interpret|converging)\b", query):
            return "REQUIRES_DEEP_REASONING", 0.95, {"reason": "strategic_synthesis"}

        # Complex market motion
        if intent in {"STRATEGIC_DECISION", "MARKET_MOTION", "HISTORICAL_ANALOGUE"}:
            return "REQUIRES_DEEP_REASONING", 0.90, {"reason": "strategic_intent"}

        return "DOES_NOT_REQUIRE", 0.75, {"reason": "factual_default"}

    def _eval_evidence_directness(self, ctx: dict[str, Any]) -> tuple[str, float, dict[str, Any]]:
        method = str(ctx.get("extraction_method", "")).lower()
        source_type = str(ctx.get("source_type", "")).lower()
        if method in {"source_explicit", "deterministic"} or source_type in {"web", "blog", "paper"}:
            return "DIRECT_EVIDENCE", 0.95, {"method": method}
        return "INDIRECT_EVIDENCE", 0.80, {"method": method}

    def _eval_change_type(self, ctx: dict[str, Any]) -> tuple[str, float, dict[str, Any]]:
        action_count = int(ctx.get("action_count", 0))
        span_days = int(ctx.get("span_days", 0))
        if action_count >= 2 and span_days >= 30:
            return "STRUCTURAL_CHANGE", 0.88, {"actions": action_count, "span_days": span_days}
        if action_count == 1:
            return "TEMPORARY_CHANGE", 0.70, {"actions": action_count}
        return "UNKNOWN", 0.60, {}

    def _eval_company_action_type(self, ctx: dict[str, Any]) -> tuple[str, float, dict[str, Any]]:
        subtype = str(ctx.get("subtype", "")).lower()
        if subtype in {"product_launch", "model_release", "pricing_change", "deployment", "partnership"}:
            return "COMPETITOR_ACTION", 0.95, {"subtype": subtype}
        return "GENERAL_ACTIVITY", 0.85, {"subtype": subtype}

    def _eval_perception_category(self, ctx: dict[str, Any]) -> tuple[str, float, dict[str, Any]]:
        text = str(ctx.get("text", "")).lower()
        if any(w in text for w in ["expensive", "cost", "latency", "slow", "dislike", "frustrated", "hard to", "pain", "outage"]):
            return "CUSTOMER_PAIN", 0.92, {"signals": "pain_keywords"}
        if any(w in text for w in ["feature", "wish", "please add", "support for", "router"]):
            return "FEATURE_REQUEST", 0.85, {"signals": "request_keywords"}
        if any(w in text for w in ["love", "great", "faster", "impressed", "seamless"]):
            return "PRAISE", 0.85, {"signals": "praise_keywords"}
        return "OTHER", 0.70, {}


class CachedDecisionEngine:
    """Decorates a DecisionEngine with in-memory caching and optional database persistence."""

    def __init__(self, engine: DecisionEngine, repository: Any = None) -> None:
        self.engine = engine
        self.repository = repository
        self._memory_cache: dict[str, DecisionResult] = {}
        self.cache_hits = 0
        self.decisions_made = 0

    def evaluate(
        self,
        decision_type: DecisionType,
        context: dict[str, Any],
        allowed_outputs: list[str] | None = None,
    ) -> DecisionResult:
        context_str = json.dumps(context, sort_keys=True, default=str)
        context_hash = hashlib.sha256(context_str.encode()).hexdigest()
        cache_key = hashlib.sha256(f"{decision_type.value}:{context_hash}".encode()).hexdigest()

        if cache_key in self._memory_cache:
            self.cache_hits += 1
            return self._memory_cache[cache_key]

        if self.repository and hasattr(self.repository, "get_decision_cache"):
            stored = self.repository.get_decision_cache(cache_key)
            if stored:
                self.cache_hits += 1
                res = DecisionResult(
                    decision_type=DecisionType(stored["decision_type"]),
                    decision=str(stored["decision"]),
                    probability=float(stored["probability"]),
                    model=str(stored["model"]),
                    version=str(stored["version"]),
                    input_references=list(stored["result"].get("input_references", [])),
                    timestamp=datetime.fromisoformat(stored["created_at"]),
                    metadata=dict(stored["result"].get("metadata", {})),
                )
                self._memory_cache[cache_key] = res
                return res

        self.decisions_made += 1
        result = self.engine.evaluate(decision_type, context, allowed_outputs)
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
                    "result": {
                        "input_references": result.input_references,
                        "metadata": result.metadata,
                    },
                },
            )

        return result
