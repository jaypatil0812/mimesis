import asyncio
import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from memesis.analysis.scoring import DeterministicScoringService
from memesis.domain.schemas import (
    Document,
    DocumentVersion,
    EdgeType,
    Evidence,
    ExtractionMethod,
    GraphEdge,
    Market,
    NodeType,
    Provenance,
    Source,
)
from memesis.extraction.evaluation import _persist_fixture
from memesis.extraction.pipeline import EvidenceGraphPipeline
from memesis.graph.repository import GraphRepository
from memesis.knowledge.service import KnowledgeService
from memesis.reasoning.contracts import EpistemicStatus
from memesis.reasoning.engine import MemesisReasoningEngine

REPO_ROOT = Path(__file__).resolve().parents[3]

EVALUATION_QUESTIONS = [
    "Who is driving the small-model narrative?",
    "Is the market actually moving toward specialized models or are people merely talking about it?",
    "What are competitors doing about inference cost?",
    "What do developers dislike about current inference infrastructure?",
    "What adjacent markets could benefit if specialized models grow?",
    "What changed during the last 30 days?",
    "Which people historically discussed this trend before companies began acting?",
    "What evidence contradicts the small-model thesis?",
    "What should an AI infrastructure founder investigate because of these changes?",
    "Give me every post about small models.",
]


def seed_phase5_fixture(repository: GraphRepository) -> None:
    """Populates the graph repository with the comprehensive evaluation fixture if empty."""
    if len(repository.list_nodes()) > 0:
        return

    # 1. Load phase3_examples.json and project graph
    examples_path = REPO_ROOT / "data" / "evaluation" / "phase3_examples.json"
    if examples_path.exists():
        dataset = json.loads(examples_path.read_text())
        for example in dataset["examples"]:
            _persist_fixture(repository, example)
        asyncio.run(EvidenceGraphPipeline(repository).run())

    now = datetime.now(UTC)
    source = repository.add_source(
        Source(
            source_key="eval:phase5_supplement",
            source_type="evaluation_supplement",
            base_url="https://example.org/eval-phase5",
        )
    )

    def _add_evidence_and_node(name: str, node_type: NodeType, text: str, days_ago: int = 5):
        doc = repository.add_document(
            Document(source_id=source.id, external_id=name, canonical_url=f"https://example.org/{name}")
        )
        at = now - timedelta(days=days_ago)
        ver = repository.add_document_version(
            DocumentVersion(
                document_id=doc.id,
                content_hash=hashlib.sha256(text.encode()).hexdigest(),
                raw_payload=text,
                retrieved_at=at,
                published_at=at,
            )
        )
        ev = repository.add_evidence(
            Evidence(
                source_id=source.id,
                document_version_id=ver.id,
                source_url=f"https://example.org/{name}",
                source_type="evaluation_supplement",
                retrieved_at=at,
                published_at=at,
                original_reference=text[:200],
                raw_text=text,
                normalized_text=text,
                content_hash=hashlib.sha256(text.encode()).hexdigest(),
            )
        )
        nid = uuid4()
        prov = Provenance(
            source_url=ev.source_url,
            source_type=ev.source_type,
            retrieved_at=ev.retrieved_at,
            published_at=ev.published_at,
            original_reference=ev.original_reference,
            evidence_ids=(ev.id,),
            confidence=1.0,
            extraction_method=ExtractionMethod.DETERMINISTIC,
            entity_ids=(nid,),
        )
        node = Market(id=nid, name=name, provenance=prov) if node_type == NodeType.MARKET else KnowledgeService(repository).create_node(node_type, name, ev.id)
        if node_type == NodeType.MARKET:
            repository.add_node(node)
        return node, ev

    # 2. Add Markets and Adjacency
    m_ai, ev_ai = _add_evidence_and_node("AI infrastructure", NodeType.MARKET, "AI infrastructure market for serving models.")
    m_edge, ev_edge = _add_evidence_and_node("Edge/on-device AI", NodeType.MARKET, "Edge and on-device machine learning deployment market.")
    m_route, ev_route = _add_evidence_and_node("Model Routing Infrastructure", NodeType.MARKET, "Model routing and gateway dispatch infrastructure.")

    # Edges between markets
    def _add_edge(edge_type: EdgeType, from_id, to_id, ev_id, days_ago: int = 5):
        at = now - timedelta(days=days_ago)
        return repository.add_edge(
            GraphEdge(
                edge_type=edge_type,
                from_node_id=from_id,
                to_node_id=to_id,
                valid_from=at,
                recorded_at=at,
                provenance=Provenance(
                    source_url="https://example.org/eval-phase5",
                    source_type="evaluation_supplement",
                    retrieved_at=at,
                    published_at=at,
                    original_reference=edge_type.value,
                    evidence_ids=(ev_id,),
                    confidence=1.0,
                    extraction_method=ExtractionMethod.DETERMINISTIC,
                    entity_ids=(from_id, to_id),
                ),
            )
        )

    _add_edge(EdgeType.ADJACENT_TO, m_ai.id, m_edge.id, ev_edge.id)
    _add_edge(EdgeType.ADJACENT_TO, m_ai.id, m_route.id, ev_route.id)
    _add_edge(EdgeType.DEPENDS_ON, m_route.id, m_ai.id, ev_route.id)

    # 3. Add Developer Pain / Feedback Evidence
    pain_text = "Developers report high cloud bills and GPU shortages on frontier APIs, expressing frustration with 3-second latency on routine tasks."
    doc_pain = repository.add_document(
        Document(source_id=source.id, external_id="dev-pain", canonical_url="https://example.org/dev-pain")
    )
    ver_pain = repository.add_document_version(
        DocumentVersion(
            document_id=doc_pain.id,
            content_hash=hashlib.sha256(pain_text.encode()).hexdigest(),
            raw_payload=pain_text,
            retrieved_at=now - timedelta(days=2),
            published_at=now - timedelta(days=2),
        )
    )
    ev_pain = repository.add_evidence(
        Evidence(
            source_id=source.id,
            document_version_id=ver_pain.id,
            source_url="https://example.org/dev-pain",
            source_type="evaluation_supplement",
            retrieved_at=now - timedelta(days=2),
            published_at=now - timedelta(days=2),
            original_reference=pain_text,
            raw_text=pain_text,
            normalized_text=pain_text,
            content_hash=hashlib.sha256(pain_text.encode()).hexdigest(),
        )
    )

    # Note: MARKET→BELIEF edges are not in the schema. Belief nodes in the graph
    # are connected via PERSON/CONTENT edges added during node extraction; no
    # cross-type fixture edge is needed here.

    # 4. Compute deterministic scores
    DeterministicScoringService(repository).compute_all(as_of=now, persist=True)


def evaluate_phase5(repository: GraphRepository, output_path: Path | None = None) -> dict[str, Any]:
    seed_phase5_fixture(repository)
    engine = MemesisReasoningEngine(repository)
    results = []

    total_tokens_a = 0
    total_tokens_b = 0
    total_cost_a = 0.0
    total_cost_b = 0.0
    expensive_calls_a = 0
    expensive_calls_b = 0

    for idx, question in enumerate(EVALUATION_QUESTIONS, 1):
        # 1. Pipeline B: Memesis Minimum Sufficient Subgraph Reasoning
        output_b, metrics_b, packet_b = engine.answer_query(question, force_full_context=False)


        # 2. Pipeline A: Full Unconstrained Context
        output_a, metrics_a, packet_a = engine.answer_query(question, force_full_context=True)

        # Collect claims counts for B
        all_claims_b = (
            output_b.what_is_happening
            + output_b.who_matters
            + output_b.what_they_believe
            + output_b.company_actions
            + output_b.perception
            + output_b.what_changed
            + output_b.adjacent_markets
            + output_b.possible_implications
            + output_b.contradictory_evidence
        )
        observed_b = sum(1 for c in all_claims_b if c.epistemic_status == EpistemicStatus.OBSERVED)
        inferred_b = sum(1 for c in all_claims_b if c.epistemic_status == EpistemicStatus.INFERRED)
        speculative_b = sum(1 for c in all_claims_b if c.epistemic_status == EpistemicStatus.SPECULATIVE)
        unsupported_b = sum(1 for c in all_claims_b if c.downgraded_reason is not None)

        total_tokens_a += metrics_a.total_tokens
        total_tokens_b += metrics_b.total_tokens
        total_cost_a += metrics_a.estimated_cost_usd
        total_cost_b += metrics_b.estimated_cost_usd
        if metrics_a.deep_reasoning_invoked:
            expensive_calls_a += 1
        if metrics_b.deep_reasoning_invoked:
            expensive_calls_b += 1

        query_report = {
            "query_number": idx,
            "question": question,
            "intent": packet_b.query_intent.intents[0].value,
            "pipeline_b_memesis": {
                "answer_summary": output_b.summary,
                "sources_used_count": len(output_b.evidence_references),
                "claims": {
                    "observed": observed_b,
                    "inferred": inferred_b,
                    "speculative": speculative_b,
                    "unsupported_claims_detected": unsupported_b,
                },
                "subgraph_size": {
                    "nodes": metrics_b.nodes_retained,
                    "edges": len(output_b.evidence_references),
                    "evidence": metrics_b.evidence_retained,
                },
                "input_tokens": packet_b.estimated_tokens,
                "output_tokens": output_b.reasoning_execution.get("output_tokens"),
                "reasoning_execution": output_b.reasoning_execution,
                "total_tokens": metrics_b.total_tokens,
                "expensive_model_calls": 1 if metrics_b.deep_reasoning_invoked else 0,
                "latency_ms": metrics_b.latency_ms,
                "estimated_cost_usd": metrics_b.estimated_cost_usd,
                "confidence": output_b.confidence.overall_confidence,
                "fallback_status": output_b.fallback_status,
            },
            "pipeline_a_full_context": {
                "answer_summary": output_a.summary,
                "subgraph_size": {
                    "nodes": metrics_a.nodes_retained,
                    "evidence": metrics_a.evidence_retained,
                },
                "input_tokens": packet_a.estimated_tokens,
                "total_tokens": metrics_a.total_tokens,
                "expensive_model_calls": 1 if metrics_a.deep_reasoning_invoked else 0,
                "reasoning_execution": output_a.reasoning_execution,
                "latency_ms": metrics_a.latency_ms,
                "estimated_cost_usd": metrics_a.estimated_cost_usd,
            },
            "comparison": {
                "token_reduction_percent": round(
                    ((metrics_a.total_tokens - metrics_b.total_tokens) / max(metrics_a.total_tokens, 1)) * 100.0, 1
                ),
                "cost_reduction_percent": round(
                    ((metrics_a.estimated_cost_usd - metrics_b.estimated_cost_usd) / max(metrics_a.estimated_cost_usd, 0.000001)) * 100.0, 1
                ),
                "expensive_call_avoided": (metrics_a.deep_reasoning_invoked and not metrics_b.deep_reasoning_invoked),
            },
        }
        results.append(query_report)

    token_savings_pct = (
        round(((total_tokens_a - total_tokens_b) / max(total_tokens_a, 1)) * 100.0, 1)
        if total_tokens_a > 0
        else 0.0
    )
    cost_savings_pct = (
        round(((total_cost_a - total_cost_b) / max(total_cost_a, 0.000001)) * 100.0, 1)
        if total_cost_a > 0
        else 0.0
    )

    report = {
        "status": "COMPLETED",
        "limitations": ["This measures execution and retrieval, not semantic answer quality.",
                        "Absent providers cannot establish real model token savings or successful strategic reasoning."],
        "evaluation_name": "Phase 5 Decision & Reasoning Engine Benchmark",
        "questions_evaluated": len(EVALUATION_QUESTIONS),
        "aggregate_metrics": {
            "pipeline_a_full_context": {
                "total_tokens": total_tokens_a,
                "total_cost_usd": round(total_cost_a, 5),
                "expensive_model_calls": expensive_calls_a,
            },
            "pipeline_b_memesis": {
                "total_tokens": total_tokens_b,
                "total_cost_usd": round(total_cost_b, 5),
                "expensive_model_calls": expensive_calls_b,
            },
            "savings": {
                "token_savings_percent": token_savings_pct,
                "cost_savings_percent": cost_savings_pct,
                "expensive_calls_avoided": expensive_calls_a - expensive_calls_b,
            },
        },
        "query_evaluations": results,
    }

    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report, indent=2))

    return report
