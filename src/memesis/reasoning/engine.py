"""End-to-end Memesis Decision & Reasoning Engine orchestrator."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from memesis.analysis.scoring import DeterministicScoringService
from memesis.graph.repository import GraphRepository
from memesis.reasoning.budget import QueryExecutionMetrics
from memesis.reasoning.classifier import QueryClassifier, QueryIntent
from memesis.reasoning.confidence import ConfidenceCalculator
from memesis.reasoning.contracts import IntelligencePacket, ReasoningOutput
from memesis.reasoning.decision_engine import CachedDecisionEngine, get_decision_engine
from memesis.reasoning.deep_gate import DeepReasoningGate, GateDecision
from memesis.reasoning.fallback import FallbackDetector
from memesis.reasoning.historical_analogues import HistoricalAnalogueEngine
from memesis.reasoning.market_motion import MarketMotionAnalyzer
from memesis.reasoning.packet import IntelligencePacketBuilder
from memesis.reasoning.planner import QueryPlan, QueryPlanner
from memesis.reasoning.synthesizer import ReasoningSynthesizer
from memesis.reasoning.validator import EvidenceValidator
from memesis.retrieval.context_builder import ContextBuilder, MinimumSufficientSubgraph


class MemesisReasoningEngine:
    """The central Phase 5 Decision & Reasoning Engine."""

    def __init__(
        self,
        repository: GraphRepository,
        decision_engine: CachedDecisionEngine | None = None,
        strong_model_adapter: Any = None,
    ) -> None:
        self.repository = repository
        self.decision_engine = decision_engine or get_decision_engine(repository=repository)
        self.classifier = QueryClassifier()
        self.planner = QueryPlanner()
        self.context_builder = ContextBuilder(repository, self.decision_engine)
        self.analogue_engine = HistoricalAnalogueEngine()
        self.motion_analyzer = MarketMotionAnalyzer()
        self.deep_gate = DeepReasoningGate(self.decision_engine)
        self.packet_builder = IntelligencePacketBuilder()
        self.synthesizer = ReasoningSynthesizer(strong_model_adapter=strong_model_adapter)
        self.validator = EvidenceValidator()
        self.confidence_calc = ConfidenceCalculator()
        self.scoring_service = DeterministicScoringService(repository)

    def answer_query(
        self,
        question: str,
        *,
        client_context: str | None = None,
        as_of: datetime | None = None,
        force_full_context: bool = False,
    ) -> tuple[ReasoningOutput, QueryExecutionMetrics, IntelligencePacket]:
        start_time = time.perf_counter()
        as_of = as_of or datetime.now(UTC)

        # 1. Query Classification
        intent = self.classifier.classify(question)

        # 2. Query Planning
        plan = self.planner.create_plan(intent)

        def _to_utc(dt: datetime | None) -> datetime:
            if dt is None:
                return datetime.now(UTC)
            return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)

        # 3. Deterministic Scores (compute or read from repo)
        all_repo_scores = self.repository.list_scores()
        if as_of:
            as_of_utc = _to_utc(as_of)
            scores = [s for s in all_repo_scores if _to_utc(s.as_of) <= as_of_utc]
        else:
            scores = all_repo_scores

        if not scores and plan.required_scores:
            scoring_run = self.scoring_service.compute_all(as_of=as_of, persist=False)
            scores = list(scoring_run.scores)

        # 4. Context Retrieval (Pipeline A: full context vs Pipeline B: minimum sufficient context)
        if force_full_context:
            # Full unconstrained context: load all nodes, all edges, all evidence
            raw_evidence = self.repository.list_evidence()
            if as_of:
                as_of_utc = _to_utc(as_of)
                all_evidence = [
                    ev for ev in raw_evidence
                    if _to_utc(ev.published_at or ev.retrieved_at) <= as_of_utc
                ]
                valid_eids = {ev.id for ev in all_evidence}
                all_edges = [
                    e for e in self.repository.list_edges()
                    if (not e.recorded_at or _to_utc(e.recorded_at) <= as_of_utc)
                    and (not e.valid_from or _to_utc(e.valid_from) <= as_of_utc)
                    and (not e.provenance.evidence_ids or any(eid in valid_eids for eid in e.provenance.evidence_ids))
                ]
                all_nodes = [
                    n for n in self.repository.list_nodes()
                    if (not n.provenance.evidence_ids or any(eid in valid_eids for eid in n.provenance.evidence_ids))
                ]
            else:
                all_nodes = self.repository.list_nodes()
                all_edges = self.repository.list_edges()
                all_evidence = raw_evidence

            subgraph = MinimumSufficientSubgraph(
                nodes=all_nodes,
                edges=all_edges,
                evidence=all_evidence,
                nodes_considered=len(all_nodes),
                nodes_retained=len(all_nodes),
                evidence_considered=len(all_evidence),
                evidence_retained=len(all_evidence),
                limits_applied={"full_context_unconstrained": 1},
            )
            motion = self.motion_analyzer.analyze(subgraph, scores, as_of)
            analogues = self.analogue_engine.find_analogues(question, subgraph)
            gate = GateDecision(
                requires_deep_reasoning=True,
                reason="Forced full-context pipeline always invokes deep reasoning.",
            )
        else:
            # Pipeline B: Minimum Sufficient Subgraph with Jev filtering
            subgraph = self.context_builder.build_context(plan, scores, as_of)
            motion = self.motion_analyzer.analyze(subgraph, scores, as_of) if plan.include_market_motion else None
            analogues = self.analogue_engine.find_analogues(question, subgraph) if plan.include_historical_analogues else []
            gate = self.deep_gate.evaluate(plan)

        # 5. Explainable Confidence
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
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            metrics = QueryExecutionMetrics(
                nodes_considered=subgraph.nodes_considered,
                nodes_retained=subgraph.nodes_retained,
                evidence_considered=subgraph.evidence_considered,
                evidence_retained=subgraph.evidence_retained,
                jev_decisions=self.decision_engine.decisions_made,
                cheap_model_tokens=0,
                expensive_model_tokens=0,
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
        final_output = validation_result.validated_output

        # 10. Instrumentation & Cost Calculation
        elapsed_ms = (time.perf_counter() - start_time) * 1000.0
        cheap_tokens = 0
        expensive_tokens = 0
        if gate.requires_deep_reasoning:
            # Token usage estimated from packet size + output size
            expensive_tokens = packet.estimated_tokens + 500

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
                    "deep_reasoning_required": gate.requires_deep_reasoning,
                    "model": "memesis-strategic-engine-v0.1",
                    "answer": final_output.model_dump(mode="json"),
                    "metrics": metrics.model_dump(mode="json"),
                },
            )

        return final_output, metrics, packet
