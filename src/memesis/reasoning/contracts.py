"""Reasoning contracts: IntelligencePacket, ClaimStatement, ReasoningOutput, Confidence."""

from __future__ import annotations

from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from memesis.reasoning.classifier import QueryIntent
from memesis.reasoning.historical_analogues import HistoricalAnalogue


class EpistemicStatus(str, Enum):
    OBSERVED = "OBSERVED"
    INFERRED = "INFERRED"
    SPECULATIVE = "SPECULATIVE"


class ClaimStatement(BaseModel):
    text: str
    epistemic_status: EpistemicStatus
    evidence_ids: list[str] = Field(default_factory=list)
    downgraded_reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "status": self.epistemic_status.value,
            "evidence_ids": self.evidence_ids,
            "downgraded_reason": self.downgraded_reason,
        }


class ConfidenceBreakdown(BaseModel):
    overall_confidence: float = Field(ge=0.0, le=1.0)
    evidence_quantity: float = Field(ge=0.0, le=1.0)
    evidence_quality: float = Field(ge=0.0, le=1.0)
    source_diversity: float = Field(ge=0.0, le=1.0)
    source_independence: float = Field(ge=0.0, le=1.0)
    entity_resolution_confidence: float = Field(ge=0.0, le=1.0)
    temporal_consistency: float = Field(ge=0.0, le=1.0)
    contradictory_evidence_balance: float = Field(ge=0.0, le=1.0)
    graph_coverage: float = Field(ge=0.0, le=1.0)
    formula: str = "weighted_linear_combination"


class IntelligencePacket(BaseModel):
    question: str
    client_context: str | None = None
    query_intent: QueryIntent
    key_beliefs: list[dict[str, Any]] = Field(default_factory=list)
    key_actors: list[dict[str, Any]] = Field(default_factory=list)
    key_companies: list[dict[str, Any]] = Field(default_factory=list)
    customer_public_perception: list[dict[str, Any]] = Field(default_factory=list)
    competitor_actions: list[dict[str, Any]] = Field(default_factory=list)
    market_relationships: list[dict[str, Any]] = Field(default_factory=list)
    memesis_scores: list[dict[str, Any]] = Field(default_factory=list)
    recent_changes: list[dict[str, Any]] = Field(default_factory=list)
    historical_analogues: list[HistoricalAnalogue] = Field(default_factory=list)
    contradictory_evidence: list[dict[str, Any]] = Field(default_factory=list)
    primary_evidence_references: list[dict[str, Any]] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    estimated_tokens: int = Field(ge=0)
    packet_hash: str = Field(min_length=64, max_length=64)


class ReasoningOutput(BaseModel):
    summary: str
    what_is_happening: list[ClaimStatement] = Field(default_factory=list)
    who_matters: list[ClaimStatement] = Field(default_factory=list)
    what_they_believe: list[ClaimStatement] = Field(default_factory=list)
    company_actions: list[ClaimStatement] = Field(default_factory=list)
    perception: list[ClaimStatement] = Field(default_factory=list)
    what_changed: list[ClaimStatement] = Field(default_factory=list)
    historical_analogues: list[HistoricalAnalogue] = Field(default_factory=list)
    adjacent_markets: list[ClaimStatement] = Field(default_factory=list)
    possible_implications: list[ClaimStatement] = Field(default_factory=list)
    contradictory_evidence: list[ClaimStatement] = Field(default_factory=list)
    unknown_or_missing: list[str] = Field(default_factory=list)
    confidence: ConfidenceBreakdown
    evidence_references: list[str] = Field(default_factory=list)
    fallback_status: str | None = None
