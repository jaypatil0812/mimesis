"""Configured research boundaries, budgets and provisional explanations."""
from datetime import datetime
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator

INVESTIGATION_VERSION = "investigation-v2"

class SourceWatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: Literal["hackernews", "bluesky", "openalex", "rss", "github", "web"]
    query: str = Field(min_length=1, max_length=500)
    feed_url: HttpUrl | None = None
    page_url: HttpUrl | None = None
    @model_validator(mode="after")
    def rss_feed(self):
        if self.source == "rss" and not self.feed_url:
            raise ValueError("RSS requires feed_url")
        if self.source == "web" and not self.page_url:
            raise ValueError("Web collection requires page_url")
        return self

class InvestigationScope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    market_id: UUID | None = None
    start_at: datetime | None = None
    time_basis: Literal["published_at", "known_at"] = "published_at"
    graph_hops: int = Field(default=3, ge=1, le=6)
    include_adjacent_markets: bool = True

class InvestigationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=200)
    question: str = Field(min_length=1, max_length=2000)
    scope: InvestigationScope
    sources: list[SourceWatch] = Field(default_factory=list, max_length=4)
    enabled: bool = False
    interval_seconds: int = Field(default=3600, ge=60, le=604800)
    initial_lookback_days: int = Field(default=14, ge=1, le=365)
    page_size: int = Field(default=20, ge=1, le=100)
    max_pages_per_source: int = Field(default=2, ge=1, le=10)
    max_evidence_per_tick: int = Field(default=50, ge=1, le=200)
    max_patterns: int = Field(default=6, ge=1, le=12)
    max_followups_per_cycle: int = Field(default=1, ge=0, le=3)
    max_investigation_rounds: int = Field(default=2, ge=0, le=3)
    processing_version: str = Field(default="memory-worker-v1", min_length=1, max_length=40)
    @model_validator(mode="after")
    def bounded_sources(self):
        keys = [(s.source, s.query, str(s.feed_url), str(s.page_url)) for s in self.sources]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate source watches")
        return self

class Followup(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=1, max_length=1000)
    query: str = Field(min_length=1, max_length=500)
    source: Literal["hackernews", "bluesky", "openalex", "rss", "github", "web"]
    rationale: str = Field(min_length=1, max_length=2000)

class PatternCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    category: str = Field(min_length=1, max_length=100)
    explanation: str = Field(min_length=1, max_length=4000)
    supporting_observation_ids: list[str] = Field(min_length=1, max_length=30)
    connecting_paths: list[list[str]] = Field(default_factory=list, max_length=20)
    alternative_explanations: list[str] = Field(min_length=1, max_length=10)
    contradictory_evidence_ids: list[str] = Field(default_factory=list, max_length=30)
    missing_information: list[str] = Field(min_length=1, max_length=20)
    next_investigation: Followup | None = None
    epistemic_status: Literal["INFERRED", "SPECULATIVE"] = "SPECULATIVE"

class PatternResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    patterns: list[PatternCandidate] = Field(default_factory=list, max_length=12)
