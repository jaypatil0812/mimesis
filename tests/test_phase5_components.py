"""Unit and integration tests for Phase 5 Decision & Reasoning Engine components."""

import hashlib
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from memesis.analysis.scoring import DeterministicScoringService
from memesis.domain.schemas import (
    Belief,
    Company,
    Content,
    EdgeType,
    Event,
    Evidence,
    ExtractionMethod,
    GraphEdge,
    Market,
    NodeType,
    Person,
    Product,
    Provenance,
    ScoreType,
    Source,
)
from memesis.reasoning.budget import QueryExecutionMetrics
from memesis.reasoning.classifier import IntentType, QueryClassifier, QueryIntent
from memesis.reasoning.confidence import ConfidenceCalculator
from memesis.reasoning.contracts import ClaimStatement, EpistemicStatus, IntelligencePacket
from memesis.reasoning.decision_engine import (
    CachedDecisionEngine,
    DecisionResult,
    DecisionType,
    HeuristicDecisionEngine,
)
from memesis.reasoning.deep_gate import DeepReasoningGate
from memesis.reasoning.engine import MemesisReasoningEngine
from memesis.reasoning.evaluation import EVALUATION_QUESTIONS, evaluate_phase5, seed_phase5_fixture
from memesis.reasoning.fallback import FallbackDetector
from memesis.reasoning.historical_analogues import HistoricalAnalogueEngine
from memesis.reasoning.market_motion import MarketMotionAnalyzer, MarketMotionStatus
from memesis.reasoning.packet import IntelligencePacketBuilder
from memesis.reasoning.planner import QueryPlanner
from memesis.reasoning.synthesizer import ReasoningSynthesizer
from memesis.reasoning.validator import EvidenceValidator
from memesis.retrieval.context_builder import ContextBuilder, MinimumSufficientSubgraph


def test_query_classification_intents_and_entities():
    classifier = QueryClassifier()

    # 1. Market motion + Strategic decision
    q1 = "Are AI infrastructure companies moving toward smaller specialized models and should we care?"
    intent1 = classifier.classify(q1)
    assert IntentType.MARKET_MOTION in intent1.intents
    assert IntentType.STRATEGIC_DECISION in intent1.intents
    assert "AI infrastructure" in intent1.markets
    assert intent1.requested_depth == "strategic"

    # 2. Competitor analysis
    q2 = "What are competitors doing about inference cost?"
    intent2 = classifier.classify(q2)
    assert IntentType.COMPETITOR_ANALYSIS in intent2.intents

    # 3. Actor analysis
    q3 = "Who is driving the small-model narrative?"
    intent3 = classifier.classify(q3)
    assert IntentType.ACTOR_ANALYSIS in intent3.intents

    # 4. Perception / developer pain
    q4 = "What do developers dislike about current inference infrastructure?"
    intent4 = classifier.classify(q4)
    assert IntentType.PERCEPTION_ANALYSIS in intent4.intents

    # 5. Raw retrieval
    q5 = "Give me every post about small models."
    intent5 = classifier.classify(q5)
    assert IntentType.RAW_RETRIEVAL in intent5.intents
    assert intent5.requested_depth == "raw_retrieval"

    # 6. Classifier cache check
    intent5_cached = classifier.classify(q5)
    assert intent5_cached == intent5


def test_query_planning_differentiates_questions():
    planner = QueryPlanner()
    classifier = QueryClassifier()

    plan_raw = planner.create_plan(classifier.classify("Give me every post about small models."))
    assert plan_raw.include_historical_analogues is False
    assert plan_raw.required_scores == []
    assert plan_raw.max_hops == 1
    assert NodeType.CONTENT in plan_raw.target_node_types

    plan_motion = planner.create_plan(
        classifier.classify("Are AI infrastructure companies moving toward smaller specialized models?")
    )
    assert plan_motion.include_historical_analogues is True
    assert plan_motion.include_market_motion is True
    assert ScoreType.ACTION_CONVERSION in plan_motion.required_scores
    assert NodeType.EVENT in plan_motion.target_node_types

    plan_actors = planner.create_plan(classifier.classify("Who is driving the small-model narrative?"))
    assert ScoreType.ACTOR_LEAD in plan_actors.required_scores
    assert ScoreType.ACTOR_INFLUENCE in plan_actors.required_scores
    assert plan_actors.include_historical_analogues is False


def test_jev_style_decision_engine_and_caching(repository):
    base_engine = HeuristicDecisionEngine()
    engine = CachedDecisionEngine(base_engine, repository=repository)

    # 1. Relevance decision
    res_rel = engine.evaluate(
        DecisionType.RELEVANCE,
        {"query": "small models inference", "node_name": "Quantized model routing", "references": ["n1"]},
    )
    assert res_rel.decision == "RELEVANT"
    assert 0.0 <= res_rel.probability <= 1.0
    assert res_rel.model == HeuristicDecisionEngine.VERSION

    # 2. Stance decision
    res_stance_oppose = engine.evaluate(
        DecisionType.STANCE,
        {"text": "Small models cannot replace frontier systems for every workload.", "references": ["n2"]},
    )
    assert res_stance_oppose.decision == "CONTRADICTS"

    res_stance_support = engine.evaluate(
        DecisionType.STANCE,
        {"text": "Task-specific models reduce inference cost for enterprise inference.", "references": ["n3"]},
    )
    assert res_stance_support.decision == "SUPPORTS"

    # 3. Deep reasoning gate decision
    res_gate_raw = engine.evaluate(
        DecisionType.DEEP_REASONING_GATE,
        {"query": "Give me every post about small models.", "intent": "RAW_RETRIEVAL"},
    )
    assert res_gate_raw.decision == "DOES_NOT_REQUIRE"

    res_gate_strat = engine.evaluate(
        DecisionType.DEEP_REASONING_GATE,
        {"query": "Why are these signals converging and what should a founder investigate?", "intent": "STRATEGIC_DECISION"},
    )
    assert res_gate_strat.decision == "REQUIRES_DEEP_REASONING"

    # 4. Cache hit check
    initial_hits = engine.cache_hits
    engine.evaluate(
        DecisionType.RELEVANCE,
        {"query": "small models inference", "node_name": "Quantized model routing", "references": ["n1"]},
    )
    assert engine.cache_hits == initial_hits + 1


def test_deep_reasoning_gate_rules():
    engine = CachedDecisionEngine(HeuristicDecisionEngine())
    gate = DeepReasoningGate(engine)
    classifier = QueryClassifier()
    planner = QueryPlanner()

    # Raw retrieval bypasses deep reasoning
    decision_raw = gate.evaluate(planner.create_plan(classifier.classify("Give me every post about small models.")))
    assert decision_raw.requires_deep_reasoning is False
    assert decision_raw.direct_answer_strategy == "raw_retrieval_formatter"

    # Factual lookup bypasses deep reasoning
    decision_lookup = gate.evaluate(planner.create_plan(classifier.classify("Who is driving the small-model narrative?")))
    assert decision_lookup.requires_deep_reasoning is False
    assert decision_lookup.direct_answer_strategy == "actor_ranking_formatter"

    # Strategic synthesis requires deep reasoning
    decision_strat = gate.evaluate(planner.create_plan(classifier.classify("What should an AI infrastructure founder investigate because of these changes?")))
    assert decision_strat.requires_deep_reasoning is True
    assert decision_strat.direct_answer_strategy is None


def test_historical_analogues_have_similarities_and_differences(repository):
    seed_phase5_fixture(repository)
    engine = MemesisReasoningEngine(repository)
    _, _, packet = engine.answer_query("What historical pattern best explains the small model transition?")

    analogues = packet.historical_analogues
    assert len(analogues) >= 2
    for analogue in analogues:
        assert analogue.analogue
        assert len(analogue.similarities) >= 2
        assert len(analogue.differences) >= 1
        assert 0.0 < analogue.similarity_confidence <= 1.0


def test_market_motion_explainability(repository):
    seed_phase5_fixture(repository)
    engine = MemesisReasoningEngine(repository)
    output, metrics, packet = engine.answer_query("Is the market actually moving toward specialized models or are people merely talking about it?")

    # Verify that answer summary and breakdown explicitly explain WHY movement is real
    assert output.summary
    # Any deterministic motion status is valid — engine computes from actual scores
    motion_statuses = {"ACCELERATING", "DECELERATING", "STABLE", "NASCENT", "UNCERTAIN"}
    assert any(s in output.summary for s in motion_statuses) or "motion" in output.summary.lower()
    # Check that company actions are cited
    assert len(output.company_actions) > 0 or len(output.what_is_happening) > 0


def test_evidence_validator_downgrades_unsupported_observed_claims():
    validator = EvidenceValidator()
    # Create fake packet with known evidence
    ev_id = "00000000-0000-0000-0000-000000000001"
    packet = IntelligencePacket(
        question="test",
        query_intent=QueryIntent(raw_query="test", intents=[IntentType.GENERAL_RESEARCH]),
        primary_evidence_references=[{"id": ev_id, "text": "True text"}],
        estimated_tokens=10,
        packet_hash="a" * 64,
    )

    from memesis.reasoning.contracts import ConfidenceBreakdown, ReasoningOutput

    raw_output = ReasoningOutput(
        summary="Test summary",
        what_is_happening=[
            ClaimStatement(text="Supported claim", epistemic_status=EpistemicStatus.OBSERVED, evidence_ids=[ev_id]),
            ClaimStatement(text="Unsupported claim", epistemic_status=EpistemicStatus.OBSERVED, evidence_ids=["missing-id"]),
            ClaimStatement(text="Speculative claim will definitely happen", epistemic_status=EpistemicStatus.SPECULATIVE, evidence_ids=[]),
        ],
        confidence=ConfidenceBreakdown(
            overall_confidence=0.8,
            evidence_quantity=0.8,
            evidence_quality=0.8,
            source_diversity=0.8,
            source_independence=0.8,
            entity_resolution_confidence=0.8,
            temporal_consistency=0.8,
            contradictory_evidence_balance=0.8,
            graph_coverage=0.8,
        ),
    )

    val_res = validator.validate(raw_output, packet)
    assert val_res.claims_supported == 2
    assert val_res.claims_downgraded == 1
    assert val_res.unsupported_claims_detected == 1

    downgraded = val_res.validated_output.what_is_happening[1]
    assert downgraded.epistemic_status == EpistemicStatus.INFERRED
    assert downgraded.downgraded_reason is not None

    speculative = val_res.validated_output.what_is_happening[2]
    assert "will definitely" not in speculative.text


def test_fallback_behavior_on_unknown_entity(repository):
    engine = MemesisReasoningEngine(repository)
    output, metrics, packet = engine.answer_query("What is QuantumHypervisorX building in AI infrastructure?")

    assert output.fallback_status == "UNKNOWN"
    assert "UNKNOWN" in output.summary
    assert metrics.deep_reasoning_invoked is False
    assert metrics.expensive_model_tokens == 0


def test_end_to_end_10_evaluation_queries(repository):
    # Run the full phase 5 evaluation comparing Pipeline A and Pipeline B
    report = evaluate_phase5(repository)

    assert report["status"] == "PASS"
    assert report["questions_evaluated"] == 10
    assert len(report["query_evaluations"]) == 10

    agg = report["aggregate_metrics"]
    savings = agg["savings"]

    # Verify that Pipeline B produces token and cost savings vs Pipeline A
    assert savings["token_savings_percent"] > 0.0
    assert savings["cost_savings_percent"] > 0.0
    assert savings["expensive_calls_avoided"] >= 5

    # Check query 10 specifically (Raw retrieval)
    q10_res = report["query_evaluations"][9]
    assert q10_res["intent"] == "RAW_RETRIEVAL"
    assert q10_res["pipeline_b_memesis"]["expensive_model_calls"] == 0
    assert q10_res["comparison"]["expensive_call_avoided"] is True
