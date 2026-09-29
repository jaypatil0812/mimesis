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
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))

    def compute_cost(self) -> float:
        cost = (
            (self.cheap_model_tokens / 1000.0) * CHEAP_MODEL_COST_PER_1K
            + (self.expensive_model_tokens / 1000.0) * EXPENSIVE_MODEL_COST_PER_1K
        )
        self.estimated_cost_usd = round(cost, 6)
        self.total_tokens = self.cheap_model_tokens + self.expensive_model_tokens
        return self.estimated_cost_usd
