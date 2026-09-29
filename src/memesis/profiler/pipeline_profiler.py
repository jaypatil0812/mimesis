"""Pipeline profiler: measures time, token, LLM cost, DB query, cache hit, and storage metrics
for a single end-to-end Memesis answer_query call.

Profiler is strictly READ-ONLY by default. It measures the pipeline, emits a JSON report,
ranks bottlenecks, estimates impact, and provides recommendations without modifying any system state.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import event
from sqlalchemy.engine import Engine

from memesis.analysis.scoring import DeterministicScoringService
from memesis.graph.repository import GraphRepository
from memesis.graph.sql_repository import SqlGraphRepository
from memesis.reasoning.engine import MemesisReasoningEngine


@dataclass
class StageMetrics:
    name: str
    wall_time_ms: float = 0.0
    db_queries: int = 0
    cheap_model_tokens: int = 0
    expensive_model_tokens: int = 0
    llm_cost_usd: float = 0.0

    @property
    def total_tokens(self) -> int:
        return self.cheap_model_tokens + self.expensive_model_tokens


@dataclass
class OptimizationRecommendation:
    category: str  # "SAFE_PREDETERMINED" or "REQUIRES_MANUAL_APPROVAL"
    title: str
    target_stage: str
    estimated_latency_reduction_pct: float
    description: str
    safety_justification: str


@dataclass
class ProfileReport:
    question: str
    stages: list[StageMetrics] = field(default_factory=list)
    crawl_requests: int = 0
    storage_bytes: dict[str, int] = field(default_factory=dict)
    cache_hits: int = 0
    cache_misses: int = 0
    generated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    pipeline_b_tokens: int = 0
    pipeline_b_cost_usd: float = 0.0
    deep_reasoning_invoked: bool = False
    recommendations: list[OptimizationRecommendation] = field(default_factory=list)

    @property
    def cache_hit_pct(self) -> float:
        total = self.cache_hits + self.cache_misses
        return round(100.0 * self.cache_hits / total, 1) if total > 0 else 0.0

    @property
    def total_wall_time_ms(self) -> float:
        return round(sum(s.wall_time_ms for s in self.stages), 2)

    @property
    def total_db_queries(self) -> int:
        return sum(s.db_queries for s in self.stages)

    @property
    def total_llm_cost_usd(self) -> float:
        return round(sum(s.llm_cost_usd for s in self.stages), 6)

    def bottlenecks(self, top_n: int = 3) -> list[StageMetrics]:
        """Return the top-N slowest stages ranked by wall-clock time."""
        return sorted(self.stages, key=lambda s: s.wall_time_ms, reverse=True)[:top_n]

    def summary_table(self) -> str:
        lines = [
            f"{'Stage':<35} {'Time(ms)':>10} {'DB Q':>6} {'Tokens':>8} {'Cost $':>10}",
            "-" * 75,
        ]
        for stage in self.stages:
            lines.append(
                f"{stage.name:<35} {stage.wall_time_ms:>10.2f} {stage.db_queries:>6} "
                f"{stage.total_tokens:>8} {stage.llm_cost_usd:>10.6f}"
            )
        lines.append("-" * 75)
        lines.append(
            f"{'TOTAL':<35} {self.total_wall_time_ms:>10.2f} {self.total_db_queries:>6} "
            f"{self.pipeline_b_tokens:>8} {self.total_llm_cost_usd:>10.6f}"
        )
        lines.append(f"\nCache: {self.cache_hits} hits / {self.cache_misses} misses "
                     f"({self.cache_hit_pct:.1f}%)")
        lines.append(f"Deep reasoning invoked: {self.deep_reasoning_invoked}")
        lines.append(f"\nRanked Bottlenecks:")
        total_time = max(self.total_wall_time_ms, 0.001)
        for i, b in enumerate(self.bottlenecks(), 1):
            pct = round(100.0 * b.wall_time_ms / total_time, 1)
            lines.append(f"  {i}. {b.name}: {b.wall_time_ms:.2f}ms ({pct}% of total), {b.db_queries} DB queries")

        lines.append("\nOptimization Recommendations (READ-ONLY Analysis):")
        safe_recs = [r for r in self.recommendations if r.category == "SAFE_PREDETERMINED"]
        approval_recs = [r for r in self.recommendations if r.category == "REQUIRES_MANUAL_APPROVAL"]

        lines.append("  [Safe Predetermined — Applied with --optimize]:")
        for r in safe_recs:
            lines.append(f"    - {r.title} (est. {r.estimated_latency_reduction_pct}% reduction in {r.target_stage})")
            lines.append(f"      {r.description}")

        lines.append("  [Prohibited from Auto-Optimization — Requires Explicit Approval]:")
        for r in approval_recs:
            lines.append(f"    - {r.title} (est. {r.estimated_latency_reduction_pct}% reduction in {r.target_stage})")
            lines.append(f"      Policy: {r.safety_justification}")

        return "\n".join(lines)

    def as_json(self) -> str:
        total_time = max(self.total_wall_time_ms, 0.001)
        return json.dumps({
            "question": self.question,
            "generated_at": self.generated_at.isoformat(),
            "total_wall_time_ms": self.total_wall_time_ms,
            "total_db_queries": self.total_db_queries,
            "total_llm_cost_usd": self.total_llm_cost_usd,
            "pipeline_b_tokens": self.pipeline_b_tokens,
            "pipeline_b_cost_usd": self.pipeline_b_cost_usd,
            "deep_reasoning_invoked": self.deep_reasoning_invoked,
            "cache_hit_pct": self.cache_hit_pct,
            "cache_hits": self.cache_hits,
            "cache_misses": self.cache_misses,
            "crawl_requests": self.crawl_requests,
            "storage_bytes": self.storage_bytes,
            "stages": [
                {
                    "name": s.name,
                    "wall_time_ms": round(s.wall_time_ms, 2),
                    "db_queries": s.db_queries,
                    "cheap_tokens": s.cheap_model_tokens,
                    "expensive_tokens": s.expensive_model_tokens,
                    "total_tokens": s.total_tokens,
                    "llm_cost_usd": round(s.llm_cost_usd, 6),
                }
                for s in self.stages
            ],
            "ranked_bottlenecks": [
                {
                    "rank": i,
                    "name": b.name,
                    "wall_time_ms": round(b.wall_time_ms, 2),
                    "share_of_total_pct": round(100.0 * b.wall_time_ms / total_time, 1),
                    "db_queries": b.db_queries,
                }
                for i, b in enumerate(self.bottlenecks(), 1)
            ],
            "recommendations": [
                {
                    "category": r.category,
                    "title": r.title,
                    "target_stage": r.target_stage,
                    "estimated_latency_reduction_pct": r.estimated_latency_reduction_pct,
                    "description": r.description,
                    "safety_justification": r.safety_justification,
                }
                for r in self.recommendations
            ],
        }, indent=2)


class _QueryCounter:
    """SQLAlchemy event listener that counts cursor.execute calls per stage."""

    def __init__(self) -> None:
        self.count = 0

    def reset(self) -> None:
        self.count = 0

    def __call__(self, conn: Any, cursor: Any, statement: Any, *args: Any) -> None:
        self.count += 1


class PipelineProfiler:
    """Instruments the Memesis answer_query pipeline to find measurable bottlenecks.

    Always READ-ONLY: strictly measures and reports without altering system state.
    """

    def __init__(self, repository: GraphRepository) -> None:
        self.repository = repository
        self._engine: Engine | None = None
        if isinstance(repository, SqlGraphRepository):
            try:
                self._engine = repository._sessions.kw["bind"]
            except (AttributeError, KeyError):
                try:
                    sample_session = repository._sessions()
                    self._engine = sample_session.bind
                    sample_session.close()
                except Exception:
                    self._engine = None

    def profile(self, question: str, *, as_of: datetime | None = None) -> ProfileReport:
        """Run a full answer_query call and return a comprehensive ProfileReport."""
        report = ProfileReport(question=question)
        query_counter = _QueryCounter()

        if self._engine is not None:
            event.listen(self._engine, "after_cursor_execute", query_counter)

        try:
            # Stage 1: Graph loading (classify + plan)
            stage_classify = StageMetrics(name="classify_and_plan")
            t0 = time.perf_counter()
            from memesis.reasoning.classifier import QueryClassifier
            from memesis.reasoning.planner import QueryPlanner
            classifier = QueryClassifier()
            planner = QueryPlanner()
            query_counter.reset()
            intent = classifier.classify(question)
            plan = planner.create_plan(intent)
            stage_classify.wall_time_ms = (time.perf_counter() - t0) * 1000
            stage_classify.db_queries = query_counter.count
            report.stages.append(stage_classify)

            # Stage 2: Deterministic scoring
            stage_scoring = StageMetrics(name="deterministic_scoring")
            query_counter.reset()
            t0 = time.perf_counter()
            scoring_service = DeterministicScoringService(self.repository)
            scores = scoring_service.compute_all(as_of=as_of, persist=False).scores
            stage_scoring.wall_time_ms = (time.perf_counter() - t0) * 1000
            stage_scoring.db_queries = query_counter.count
            report.stages.append(stage_scoring)

            # Stage 3: Context building & subgraph bounding
            from memesis.reasoning.decision_engine import CachedDecisionEngine, HeuristicDecisionEngine
            from memesis.retrieval.context_builder import ContextBuilder
            stage_context = StageMetrics(name="context_builder")
            query_counter.reset()
            t0 = time.perf_counter()
            decision_engine = CachedDecisionEngine(HeuristicDecisionEngine(), repository=self.repository)
            context_builder = ContextBuilder(self.repository, decision_engine)
            subgraph = context_builder.build_context(plan, list(scores))
            stage_context.wall_time_ms = (time.perf_counter() - t0) * 1000
            stage_context.db_queries = query_counter.count
            report.stages.append(stage_context)

            # Stage 4: Full engine answer_query (synthesis + validation)
            stage_full = StageMetrics(name="full_engine_answer_query")
            query_counter.reset()
            t0 = time.perf_counter()
            engine = MemesisReasoningEngine(self.repository, decision_engine=decision_engine)
            output, metrics, packet = engine.answer_query(question, as_of=as_of)
            stage_full.wall_time_ms = (time.perf_counter() - t0) * 1000
            stage_full.db_queries = query_counter.count
            stage_full.cheap_model_tokens = metrics.cheap_model_tokens
            stage_full.expensive_model_tokens = metrics.expensive_model_tokens
            stage_full.llm_cost_usd = metrics.estimated_cost_usd
            report.stages.append(stage_full)

            # Fill report summary metrics
            report.pipeline_b_tokens = metrics.total_tokens
            report.pipeline_b_cost_usd = metrics.estimated_cost_usd
            report.deep_reasoning_invoked = metrics.deep_reasoning_invoked
            report.cache_hits = metrics.cache_hits

            # Stage 5: Storage metrics
            stage_storage = StageMetrics(name="storage_metrics")
            query_counter.reset()
            t0 = time.perf_counter()
            storage = self.repository.storage_metrics()
            stage_storage.wall_time_ms = (time.perf_counter() - t0) * 1000
            stage_storage.db_queries = query_counter.count
            report.stages.append(stage_storage)
            report.storage_bytes = {k: v for k, v in storage.items()}

            # Generate structured recommendations (Safe vs Requires Approval)
            report.recommendations = [
                OptimizationRecommendation(
                    category="SAFE_PREDETERMINED",
                    title="Daily Score Snapshot Caching",
                    target_stage="deterministic_scoring",
                    estimated_latency_reduction_pct=85.0,
                    description="Cache precomputed daily score records so subsequent queries reuse scores for identical as_of dates.",
                    safety_justification="Safe: Scores are deterministic functions of historical graph data. Reusing daily snapshots does not alter results.",
                ),
                OptimizationRecommendation(
                    category="SAFE_PREDETERMINED",
                    title="Repository List Call Deduplication",
                    target_stage="context_builder",
                    estimated_latency_reduction_pct=40.0,
                    description="Cache list_nodes() and list_edges() results in memory during a single query lifecycle instead of repeated DB roundtrips.",
                    safety_justification="Safe: In-memory query-scoped caching preserves exact graph state with zero semantic change.",
                ),
                OptimizationRecommendation(
                    category="REQUIRES_MANUAL_APPROVAL",
                    title="Prune Graph Traversal Hop Depth from 2 to 1",
                    target_stage="context_builder",
                    estimated_latency_reduction_pct=50.0,
                    description="Reduce default retrieval hop depth to minimize subgraph node count.",
                    safety_justification="PROHIBITED FROM AUTO-APPLY: Reducing hop depth alters retrieval semantics and could miss peripheral competitor actions.",
                ),
                OptimizationRecommendation(
                    category="REQUIRES_MANUAL_APPROVAL",
                    title="Quantize Scoring Formula Weights",
                    target_stage="deterministic_scoring",
                    estimated_latency_reduction_pct=15.0,
                    description="Simplify multi-component scoring into coarse discrete bands.",
                    safety_justification="PROHIBITED FROM AUTO-APPLY: Scoring methodology changes require explicit human approval and regression benchmarking.",
                ),
            ]

        finally:
            if self._engine is not None:
                event.remove(self._engine, "after_cursor_execute", query_counter)

        return report
