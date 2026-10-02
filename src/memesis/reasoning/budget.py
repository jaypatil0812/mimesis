"""Instrumentation, token counting, cost tracking, and execution metrics."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

# Pricing estimates per 1,000 tokens
CHEAP_MODEL_COST_PER_1K = 0.00015   # $0.15 per 1M tokens
EXPENSIVE_MODEL_COST_PER_1K = 0.005 # $5.00 per 1M tokens


class QueryExecutionMetrics(BaseModel):
    nodes_considered: int = 0
    nodes_retained: int = 0
    evidence_considered: int = 0
    evidence_retained: int = 0
    jev_decisions: int = 0
    cheap_model_tokens: int = 0
    expensive_model_tokens: int = 0
    total_tokens: int = 0
    cache_hits: int = 0
    latency_ms: float = 0.0
    estimated_cost_usd: float = 0.0
    deep_reasoning_invoked: bool = False
    usage_complete: bool = True
    cost_status: str = "illustrative_legacy_rates"
    provider_calls: list[dict[str, Any]] = Field(default_factory=list)
    cost_semantics: str = "Illustrative legacy rates, not billing."
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))

    def compute_cost(self) -> float:
        cost = (
            (self.cheap_model_tokens / 1000.0) * CHEAP_MODEL_COST_PER_1K
            + (self.expensive_model_tokens / 1000.0) * EXPENSIVE_MODEL_COST_PER_1K
        )
        self.estimated_cost_usd = round(cost, 6)
        self.total_tokens = self.cheap_model_tokens + self.expensive_model_tokens
        return self.estimated_cost_usd

    def apply_usage(self, calls, config):
        """Count each newly attempted request once, including invalid responses.

        Cache hits and local rules have no new provider usage. An unsuccessful
        request with unavailable usage is an unknown charge, not a free call.
        """
        self.provider_calls = [dict(call) for call in calls]
        self.cheap_model_tokens = self.expensive_model_tokens = 0
        self.usage_complete = True
        cost, priced = 0.0, True
        for call in self.provider_calls:
            tier = call.get("tier", "decision")
            inp, out = call.get("input_tokens", 0), call.get("output_tokens", 0)
            reported = call.get("usage_source") == "provider_reported" and type(inp) is int and type(out) is int and min(inp, out) >= 0
            if not reported:
                self.usage_complete = False
                continue
            if tier == "decision":
                self.cheap_model_tokens += inp + out
            else:
                self.expensive_model_tokens += inp + out
            in_rate = getattr(config, tier + "_input_usd_per_million", None)
            out_rate = getattr(config, tier + "_output_usd_per_million", None)
            if in_rate is None or out_rate is None or min(in_rate, out_rate) < 0:
                priced = False
            else:
                cost += (inp * in_rate + out * out_rate) / 1_000_000
        self.total_tokens = self.cheap_model_tokens + self.expensive_model_tokens
        self.estimated_cost_usd = round(cost, 8)
        self.cost_status = "no_provider_calls" if not calls else "estimated_from_configured_rates" if priced and self.usage_complete else "unavailable"
        self.cost_semantics = "Provider-reported tokens; configured rates are estimates, not invoices. Token totals and cost are incomplete if usage is unavailable. No provider comparison has been established."


def reasoning_receipts(execution, support):
    calls = []
    if execution.get("provider_call_attempted"):
        calls.append({"tier": "reasoning", "provider": "openai_compatible", **execution})
    if support.audit.get("provider_call_made"):
        calls.append({"tier": "reasoning", "provider": "openai_compatible",
            "model": support.audit.get("model"), "status": support.audit.get("status", "completed" if not support.audit.get("error_type") else "failed"),
            "usage_source": support.audit.get("usage_source", "unavailable"),
            "input_tokens": support.input_tokens, "output_tokens": support.output_tokens})
    return calls
