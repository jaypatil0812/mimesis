"""Counterfactual and failure checks; HTTP transport is simulated, never a live model."""
import json
from types import SimpleNamespace
import httpx
import pytest
from memesis.reasoning.adapter import StrategicReasoningAdapter
from memesis.reasoning.classifier import IntentType, QueryIntent
from memesis.reasoning.contracts import ConfidenceBreakdown, IntelligencePacket
from memesis.reasoning.deep_gate import GateDecision
from memesis.reasoning.market_motion import MarketMotionAnalyzer
from memesis.reasoning.synthesizer import ReasoningSynthesizer
from memesis.reasoning.validator import EvidenceValidator
from memesis.retrieval.context_builder import MinimumSufficientSubgraph

def packet(text, observations=None):
    return IntelligencePacket(question="Should we pursue this market?",
        query_intent=QueryIntent(raw_query="Should we pursue this market?", intents=[IntentType.STRATEGIC_DECISION]),
        primary_evidence_references=[{"id": "e1", "text": text, "published_at": "2026-09-01"}],
        memory_observations=observations or [], estimated_tokens=100, packet_hash="a" * 64)

def confidence():
    return ConfidenceBreakdown(**{key: .5 for key in ConfidenceBreakdown.model_fields if key != "formula"})

def adapter(handler):
    config = SimpleNamespace(model_api_key="test-only", reason_strong_model="test-model",
        model_api_base_url="https://test.invalid/v1", reasoning_timeout_seconds=1, reasoning_max_packet_tokens=1000)
    return StrategicReasoningAdapter(config, httpx.MockTransport(handler))

def reply(text, status="INFERRED", ids=None, observation_ids=None):
    return {"summary": text, "summary_evidence_ids": ["e1"], "unknown_or_missing": [],
        "possible_implications": [{"text": text, "epistemic_status": status,
            "evidence_ids": ["e1"] if ids is None else ids, "observation_ids": observation_ids or [],
            "reasoning": "Limited to the supplied workload and source; no general market conclusion."}]}

def response(body):
    return httpx.Response(200, json={"model": "test-model", "usage": {"prompt_tokens": 120, "completion_tokens": 30},
        "choices": [{"message": {"content": json.dumps(body)}}]})

def test_direct_counterfactual_changes_passages_without_ai_story():
    synth = ReasoningSynthesizer()
    gate = GateDecision(requires_deep_reasoning=False, reason="retrieval", direct_answer_strategy="raw_retrieval_formatter")
    positive = synth.synthesize(packet("For our workload, costs fell 40%."), None, gate, confidence())
    negative = synth.synthesize(packet("For our workload, costs rose 40%."), None, gate, confidence())
    assert positive.what_is_happening[0].text != negative.what_is_happening[0].text
    assert "fell" in positive.what_is_happening[0].text and "rose" in negative.what_is_happening[0].text
    assert not positive.possible_implications and not negative.possible_implications

def test_strategic_packet_changes_reach_adapter_and_trace_survives_validation():
    seen = []
    def handler(request):
        payload = json.loads(request.content)
        supplied = json.loads(payload["messages"][1]["content"])
        text = supplied["primary_evidence_references"][0]["text"]
        seen.append(text)
        return response(reply("Potential savings in this workload." if "fell" in text else "Cost advantage challenged in this workload."))
    synth = ReasoningSynthesizer(adapter(handler))
    gate = GateDecision(requires_deep_reasoning=True, reason="strategy")
    outputs = []
    for text in ("Costs fell 40%.", "Costs rose 40%."):
        p = packet(text)
        output = synth.synthesize(p, None, gate, confidence())
        outputs.append(EvidenceValidator().validate(output, p).validated_output)
    assert seen == ["Costs fell 40%.", "Costs rose 40%."]
    assert outputs[0].summary != outputs[1].summary
    assert outputs[0].possible_implications[0].reasoning
    assert outputs[0].reasoning_execution["input_tokens"] == 120
    assert outputs[0].reasoning_execution["usage_source"] == "provider_reported"

@pytest.mark.parametrize("kind", ["timeout", "bad_json", "unknown_citation", "candidate_promotion"])
def test_provider_failure_is_visible_and_cannot_restore_scripted_story(kind):
    def handler(request):
        if kind == "timeout":
            raise httpx.ReadTimeout("simulated", request=request)
        if kind == "bad_json":
            return httpx.Response(200, json={"choices": [{"message": {"content": "invalid"}}]})
        if kind == "unknown_citation":
            return response(reply("Fabricated conclusion", ids=["missing"]))
        return response(reply("Candidate promoted", status="OBSERVED", observation_ids=["o1"]))
    p = packet("Limited evidence", [{"id": "o1", "review_state": "proposed", "evidence_ids": ["e1"]}])
    output = ReasoningSynthesizer(adapter(handler)).synthesize(p, None,
        GateDecision(requires_deep_reasoning=True, reason="strategy"), confidence())
    assert output.fallback_status == ("PROVIDER_FAILED" if kind == "timeout" else "INVALID_RESPONSE")
    assert not output.possible_implications
    assert "specialized" not in output.summary

def test_no_provider_and_empty_motion_do_not_claim_success_or_positive_defaults():
    p = packet("Limited evidence")
    output = ReasoningSynthesizer().synthesize(p, None,
        GateDecision(requires_deep_reasoning=True, reason="strategy"), confidence())
    assert output.fallback_status == "REASONING_NOT_CONFIGURED"
    assert output.reasoning_execution["provider_call_attempted"] is False
    motion = MarketMotionAnalyzer().analyze(MinimumSufficientSubgraph(nodes=[], edges=[], evidence=[],
        nodes_considered=0, nodes_retained=0, evidence_considered=0, evidence_retained=0), [])
    assert motion.status.value == "UNCERTAIN"
    assert motion.evidence_confidence_score is None
    assert not motion.adjacent_market_signals and not motion.contradictory_signals

def test_exploratory_connections_remain_possible_without_citations():
    a = adapter(lambda request: response(reply("Could indicate another market worth investigating.", status="SPECULATIVE", ids=[])))
    output = a.reason(packet("Recorded customer experience."), confidence())
    assert output.possible_implications[0].epistemic_status.value == "SPECULATIVE"

def test_packet_budget_failure_does_not_silently_truncate_or_call_provider():
    a = adapter(lambda request: pytest.fail("Budget overflow must not issue a request"))
    p = packet("Evidence").model_copy(update={"estimated_tokens": 1001})
    output = ReasoningSynthesizer(a).synthesize(p, None,
        GateDecision(requires_deep_reasoning=True, reason="strategy"), confidence())
    assert output.fallback_status == "PACKET_TOO_LARGE"
    assert output.reasoning_execution["provider_call_attempted"] is False

def test_appended_database_counterevidence_changes_answer_and_preserves_cutoff(repository):
    from datetime import UTC, datetime
    from hashlib import sha256
    from memesis.domain.schemas import Source, Document, DocumentVersion, Evidence, NodeType
    from memesis.knowledge.service import KnowledgeService
    from memesis.reasoning.engine import MemesisReasoningEngine
    from memesis.retrieval.scope import QueryScope

    source = repository.add_source(Source(source_key="counterfactual", source_type="fixture", base_url="https://test.invalid"))
    def add(key, text):
        now = datetime.now(UTC)
        digest = sha256(text.encode()).hexdigest()
        document = repository.add_document(Document(source_id=source.id, external_id=key, canonical_url=f"https://test.invalid/{key}"))
        version = repository.add_document_version(DocumentVersion(document_id=document.id, content_hash=digest,
            raw_payload=text, retrieved_at=now, published_at=now))
        ev = repository.add_evidence(Evidence(source_id=source.id, document_version_id=version.id,
            source_url=f"https://test.invalid/{key}", source_type="fixture", retrieved_at=now,
            published_at=now, original_reference=key, raw_text=text, normalized_text=text, content_hash=digest))
        KnowledgeService(repository).create_node(NodeType.CONTENT, key, ev.id)
        return ev

    positive = add("initial-workload-report", "Our specialized model reduced workload costs by 40%.")
    cutoff = datetime.now(UTC)
    engine = MemesisReasoningEngine(repository)
    before, _, _ = engine.answer_query("list all posts", scope=QueryScope(as_of=cutoff))
    negative = add("follow-up-report", "Under production load, costs rose 40% and the earlier advantage disappeared.")
    after, metrics, _ = engine.answer_query("list all posts")
    historical, _, _ = engine.answer_query("list all posts", scope=QueryScope(as_of=cutoff))
    assert len(before.what_is_happening) == 1
    assert len(after.what_is_happening) == 2
    assert any("advantage disappeared" in c.text and str(negative.id) in c.evidence_ids for c in after.what_is_happening)
    assert [c.text for c in historical.what_is_happening] == [c.text for c in before.what_is_happening]
    assert repository.get_evidence(positive.id).raw_text == "Our specialized model reduced workload costs by 40%."
    assert metrics.expensive_model_tokens == 0 and not metrics.deep_reasoning_invoked

def test_api_claim_response_keeps_reasoning_and_observation_trace():
    from memesis.reasoning.contracts import ClaimStatement, EpistemicStatus
    from memesis.web.api import _claim_response
    claim = ClaimStatement(text="Could indicate demand", epistemic_status=EpistemicStatus.SPECULATIVE,
        evidence_ids=["e1"], observation_ids=["o1"], reasoning="One scoped report; demand needs validation.")
    rendered = _claim_response(claim, {"e1": {"id": "e1", "text": "Source"}}, "possible_implications")
    assert rendered["reasoning"] == claim.reasoning
    assert rendered["observation_ids"] == ["o1"]
