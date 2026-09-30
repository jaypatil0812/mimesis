"""End-to-end Memesis Decision & Reasoning Engine orchestrator."""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from memesis.analysis.scoring import DeterministicScoringService
from memesis.graph.repository import GraphRepository
from memesis.reasoning.budget import QueryExecutionMetrics
from memesis.reasoning.classifier import QueryClassifier, QueryIntent
from memesis.reasoning.confidence import ConfidenceCalculator
from memesis.reasoning.contracts import IntelligencePacket, ReasoningOutput
from memesis.reasoning.decision_engine import CachedDecisionEngine, HeuristicDecisionEngine
from memesis.reasoning.deep_gate import DeepReasoningGate, GateDecision
from memesis.reasoning.fallback import FallbackDetector
from memesis.reasoning.historical_analogues import HistoricalAnalogueEngine
from memesis.reasoning.market_motion import MarketMotionAnalyzer
from memesis.reasoning.packet import IntelligencePacketBuilder
from memesis.reasoning.planner import QueryPlan, QueryPlanner
from memesis.reasoning.synthesizer import ReasoningSynthesizer
from memesis.reasoning.support_verifier import ClaimSupportVerifier
from memesis.reasoning.validator import EvidenceValidator
from memesis.retrieval.context_builder import ContextBuilder, MinimumSufficientSubgraph
from memesis.retrieval.scope import QueryScope, ScopedGraphRepository, utc


class MemesisReasoningEngine:
    """The central Phase 5 Decision & Reasoning Engine."""

    def __init__(
        self,
        repository: GraphRepository,
        decision_engine: CachedDecisionEngine | None = None,
        strong_model_adapter: Any = None,
    ) -> None:
        self.repository = repository
        self.decision_engine = decision_engine or CachedDecisionEngine(
            HeuristicDecisionEngine(), repository=repository
        )
        self.classifier = QueryClassifier()
        self.planner = QueryPlanner()
        self.context_builder = ContextBuilder(repository, self.decision_engine)
        self.analogue_engine = HistoricalAnalogueEngine()
        self.motion_analyzer = MarketMotionAnalyzer()
        self.deep_gate = DeepReasoningGate(self.decision_engine)
        self.packet_builder = IntelligencePacketBuilder()
        self.synthesizer = ReasoningSynthesizer(strong_model_adapter=strong_model_adapter)
        self.validator = EvidenceValidator()
        self.support_verifier = ClaimSupportVerifier()
        self.confidence_calc = ConfidenceCalculator()
        self.scoring_service = DeterministicScoringService(repository)

    def answer_query(
        self,
        question: str,
        *,
        client_context: str | None = None,
        as_of: datetime | None = None,
        force_full_context: bool = False,
        scope: QueryScope | None = None,
    ) -> tuple[ReasoningOutput, QueryExecutionMetrics, IntelligencePacket]:
        start_time = time.perf_counter()
        if scope is not None and as_of is not None and utc(as_of) != scope.as_of:
            raise ValueError("as_of must match the explicit query scope")
        scope = scope or QueryScope(as_of=as_of or datetime.now(UTC))
        as_of = scope.as_of

        # 1. Query Classification
        intent = self.classifier.classify(question)

        # 2. Query Planning
        plan = self.planner.create_plan(intent)
        if scope.start_at is None and plan.time_filter_days:
            scope = QueryScope(**{
                **scope.model_dump(),
                "start_at": as_of - timedelta(days=plan.time_filter_days),
            })
        view = ScopedGraphRepository(self.repository, scope)

        # 3. Deterministic Scores (compute or read from repo)
        scores = []
        if plan.required_scores:
            scores = view.compute_scores()

        # 4. Context Retrieval (Pipeline A: full context vs Pipeline B: minimum sufficient context)
        if force_full_context:
            # Full retrieval removes ranking budgets, never the requested scope.
            all_nodes = view.list_nodes()
            all_edges = view.list_edges()
            all_evidence = view.list_evidence()
            subgraph = MinimumSufficientSubgraph(
                nodes=all_nodes,
                edges=all_edges,
                evidence=all_evidence,
                nodes_considered=len(all_nodes),
                nodes_retained=len(all_nodes),
                evidence_considered=len(all_evidence),
                evidence_retained=len(all_evidence),
                limits_applied={"full_context_unconstrained": 1},
                query_scope=view.scope_metadata(),
                coverage={
                    **view.coverage,
                    "retained_nodes": len(all_nodes),
                    "retained_edges": len(all_edges),
                    "retained_evidence": len(all_evidence),
                },
                evidence_membership=view.evidence_membership,
            )
            motion = self.motion_analyzer.analyze(subgraph, scores, as_of)
            analogues = self.analogue_engine.find_analogues(question, subgraph)
            gate = GateDecision(
                requires_deep_reasoning=True,
                reason="Forced full-context pipeline always invokes deep reasoning.",
            )
        else:
            # Pipeline B: Minimum Sufficient Subgraph with Jev filtering
            subgraph = ContextBuilder(view, self.decision_engine).build_context(plan, scores, as_of)
            motion = self.motion_analyzer.analyze(subgraph, scores, as_of) if plan.include_market_motion else None
            analogues = self.analogue_engine.find_analogues(question, subgraph) if plan.include_historical_analogues else []
            gate = self.deep_gate.evaluate(plan)

        # 5. Explainable Confidence
        scores = [score for score in scores if score.subject_id in subgraph.node_ids()]
        contra_count = sum(1 for e in subgraph.edges if e.qualifiers.get("stance") == "opposes")
        confidence = self.confidence_calc.compute_confidence(subgraph, contra_count, scores)

        # 6. Intelligence Packet
        packet = self.packet_builder.build_packet(
            question=question,
            intent=intent,
            subgraph=subgraph,
            market_motion=motion,
            analogues=analogues,
            scores=scores,
            client_context=client_context,
        )

        # 7. Fallback Detection
        fallback_output = FallbackDetector.check_fallback(packet, subgraph, confidence)
        if fallback_output:
            # Fallback answers are still answer outputs: run citation-integrity
            # checks so they carry the same audit metadata as synthesized answers.
            fallback_output = self.validator.validate(fallback_output, packet).validated_output
            support_result = self.support_verifier.verify(fallback_output, packet)
            fallback_output = support_result.output.model_copy(update={
                "query_scope": packet.query_scope, "coverage": packet.coverage,
            })
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            metrics = QueryExecutionMetrics(
                nodes_considered=subgraph.nodes_considered,
                nodes_retained=subgraph.nodes_retained,
                evidence_considered=subgraph.evidence_considered,
                evidence_retained=subgraph.evidence_retained,
                jev_decisions=self.decision_engine.decisions_made,
                cheap_model_tokens=0,
                expensive_model_tokens=support_result.input_tokens + support_result.output_tokens,
                cache_hits=self.decision_engine.cache_hits,
                latency_ms=round(elapsed_ms, 2),
                deep_reasoning_invoked=False,
            )
            metrics.compute_cost()
            return fallback_output, metrics, packet

        # 8. Synthesis
        raw_output = self.synthesizer.synthesize(packet, motion, gate, confidence)

        # 9. Evidence Validation
        validation_result = self.validator.validate(raw_output, packet)
        support_result = self.support_verifier.verify(validation_result.validated_output, packet)
        final_output = support_result.output.model_copy(update={
            "query_scope": packet.query_scope, "coverage": packet.coverage,
        })

        # 10. Instrumentation & Cost Calculation
        elapsed_ms = (time.perf_counter() - start_time) * 1000.0
        cheap_tokens = 0
        expensive_tokens = 0
        if gate.requires_deep_reasoning:
            # Token usage estimated from packet size + output size
            expensive_tokens = packet.estimated_tokens + 500
        expensive_tokens += support_result.input_tokens + support_result.output_tokens

        metrics = QueryExecutionMetrics(
            nodes_considered=subgraph.nodes_considered,
            nodes_retained=subgraph.nodes_retained,
            evidence_considered=subgraph.evidence_considered,
            evidence_retained=subgraph.evidence_retained,
            jev_decisions=self.decision_engine.decisions_made,
            cheap_model_tokens=cheap_tokens,
            expensive_model_tokens=expensive_tokens,
            cache_hits=self.decision_engine.cache_hits,
            latency_ms=round(elapsed_ms, 2),
            deep_reasoning_invoked=gate.requires_deep_reasoning,
        )
        metrics.compute_cost()

        # 11. Persist Reasoning Run
        run_id = uuid4()
        if hasattr(self.repository, "save_reasoning_run"):
            self.repository.save_reasoning_run(
                run_id,
                {
                    "question": question,
                    "intent": intent.model_dump(mode="json"),
                    "packet_hash": packet.packet_hash,
                    "query_scope": packet.query_scope,
                    "coverage": packet.coverage,
                    "deep_reasoning_required": gate.requires_deep_reasoning,
                    "model": "memesis-strategic-engine-v0.1",
                    "answer": final_output.model_dump(mode="json"),
                    "metrics": metrics.model_dump(mode="json"),
                },
            )

        return final_output, metrics, packet
