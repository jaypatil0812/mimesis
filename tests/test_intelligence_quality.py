import asyncio
import copy
import json
import runpy
from pathlib import Path
import pytest
from pydantic import ValidationError
from memesis.quality.contracts import CaseReview
from memesis.quality.service import run_suite, review_template, score_reviews, fingerprint, compare_provider_traces, sample_live, investigate_live_question
from memesis.reasoning.decision_engine import FrontierLLMDecisionEngine, TypeSafeJevDecisionEngine, CachedDecisionEngine, HeuristicDecisionEngine, DecisionType


@pytest.fixture(scope="module")
def report():
    dataset = json.loads((Path(__file__).parents[1] / "data/evaluation/intelligence_quality_v1.json").read_text(encoding="utf-8"))
    return asyncio.run(run_suite(dataset))


def test_adversarial_suite_separates_layers_and_does_not_validate_customer_demand(report):
    cases = {t["case_id"]: t for t in report["traces"]}
    assert len(cases) == 13
    assert cases["known_collection_gap"]["layers"]["collection"]["missing_document_ids"] == ["w2"]
    retrieval = cases["known_collection_gap"]["layers"]["retrieval"]
    assert retrieval["upstream_missing_document_ids"] == ["w2"] and not retrieval["omitted_available_document_ids"]
    assert cases["reposts"]["layers"]["collection"]["status"] == "pass"
    assert cases["ambiguous_identities"]["layers"]["resolution"]["status"] == "pass"
    assert cases["renamed_identity"]["layers"]["resolution"]["status"] == "pass"
    assert cases["negation"]["layers"]["extraction"]["status"] == "pass"
    assert all(t["layers"]["reasoning"]["status"] == "not_evaluated" for t in report["traces"])
    assert report["human_reviewed_quality"] is None and report["customer_decision_usefulness"] is None
    assert report["code_hashes"] and not report["provider_comparison_valid"]


def test_pending_review_is_not_zero_failure_or_customer_success(report):
    score = score_reviews(report, review_template(report))
    assert score["reviewed_cases"] == 0 and score["unreviewed_cases"] == 13
    assert all(layer["failure_rate"] is None for layer in score["layers"].values())
    assert score["customer_validation_status"] == "not_evaluated"


def reviewed_entry(report):
    template = review_template(report)
    item = template["reviews"][0]
    item.update(gold_approved=True, reviewer="Human reviewer", reviewer_role="human")
    item["layer_verdicts"] = {layer: "not_evaluated" for layer in item["layer_verdicts"]}
    item["layer_verdicts"]["extraction"] = "fail"
    item["findings"] = {layer: "Reviewed the source and trace; semantic/provider limitations remain." for layer in item["findings"]}
    item["findings"]["extraction"] = "Example manually reported failure at n1; test assessment only, not a real review."
    template["reviews"] = [item]
    return template


def test_human_review_has_separate_denominators(report):
    result = score_reviews(report, reviewed_entry(report))
    assert result["layers"]["extraction"]["failure_rate"] == 1
    assert result["layers"]["reasoning"]["failure_rate"] is None
    assert result["reviewed_cases"] == 1 and result["unreviewed_cases"] == 12


def test_assistant_cannot_self_approve_gold(report):
    submitted = reviewed_entry(report)
    submitted["reviews"][0]["reviewer_role"] = "assistant"
    with pytest.raises(ValidationError): score_reviews(report, submitted)


def test_unconfigured_reasoning_cannot_be_scored_as_live_quality_pass(report):
    submitted = reviewed_entry(report)
    submitted["reviews"][0]["layer_verdicts"]["reasoning"] = "pass"
    with pytest.raises(ValueError, match="Unconfigured"): score_reviews(report, submitted)


def test_reviews_reject_mutation_stale_hashes_and_duplicate_cases(report):
    changed = copy.deepcopy(report)
    changed["traces"][0]["case"]["question"] = "Altered question"
    with pytest.raises(ValueError): score_reviews(changed, review_template(report))
    submitted = reviewed_entry(report)
    submitted["reviews"][0]["trace_hash"] = "stale"
    with pytest.raises(ValueError): score_reviews(report, submitted)
    submitted = reviewed_entry(report)
    submitted["reviews"].append(copy.deepcopy(submitted["reviews"][0]))
    with pytest.raises(ValueError, match="Duplicate"): score_reviews(report, submitted)


def test_simulated_provider_measurements_are_rejected(monkeypatch):
    context = {"query": "inference cost", "text": "high inference cost", "references": ["e1"]}
    frontier = FrontierLLMDecisionEngine().evaluate(DecisionType.RELEVANCE, context)
    jev = TypeSafeJevDecisionEngine(api_key="simulated-test")
    monkeypatch.setattr(jev, "_call_typesafe_api", lambda *args: None)
    monkeypatch.setattr(jev, "_call_openrouter_api", lambda *args: None)
    simulated = jev.evaluate(DecisionType.RELEVANCE, context)
    for result in (frontier, simulated):
        assert result.metadata["execution_mode"] == "simulation"
        assert result.input_tokens == result.output_tokens == 0 and result.cost_estimate_usd == 0
    comparison = compare_provider_traces([{"case_id": "e1", "left": frontier.model_dump(mode="json"), "right": simulated.model_dump(mode="json")}])
    assert comparison["status"] == "not_comparable" and comparison["cost_savings_claim"] is None


def test_live_pair_needs_matching_receipts_and_cache_is_excluded():
    live = {"provider": "typesafe", "input_hash": "same", "decision_type": "RELEVANCE", "input_references": ["e1"],
        "latency_ms": 10, "metadata": {"execution_mode": "live", "provider_call_succeeded": True,
        "request_hash": "request", "response_hash": "response", "allowed_outputs": ["RELEVANT", "IRRELEVANT"]}}
    pair = {"case_id": "p1", "left": live, "right": copy.deepcopy(live)}
    result = compare_provider_traces([pair])
    assert result["eligible_pairs"] == 1 and not result["measurements"][0]["billing_comparison_available"]
    pair["right"]["metadata"]["cache_hit"] = True
    assert compare_provider_traces([pair])["eligible_pairs"] == 0


def test_decision_cache_is_bound_to_engine_and_output_contract(repository):
    context = {"text": "inference cost", "references": ["e1"]}
    heuristic = CachedDecisionEngine(HeuristicDecisionEngine(), repository)
    simulated = CachedDecisionEngine(FrontierLLMDecisionEngine(), repository)
    heuristic.evaluate(DecisionType.RELEVANCE, context)
    result = simulated.evaluate(DecisionType.RELEVANCE, context)
    assert result.provider == "frontier-simulated" and simulated.cache_hits == 0
    cached = simulated.evaluate(DecisionType.RELEVANCE, context)
    assert cached.metadata["cache_hit"]
    simulated.evaluate(DecisionType.RELEVANCE, context, ["YES", "NO"])
    assert simulated.decisions_made == 2


def test_real_sample_is_read_only_and_cues_are_not_gold(repository):
    before = repository.storage_metrics()
    sample = sample_live(repository, 24)
    assert sample["samples"] == [] and not sample["customer_confirmed"]
    assert repository.storage_metrics() == before
    with pytest.raises(ValueError): sample_live(repository, 101)


def test_real_question_does_not_invent_an_opportunity_in_an_empty_graph(repository):
    before = repository.storage_metrics()
    result = investigate_live_question(repository, sample_live(repository, 24))
    assert result["question"] == "What's the next big thing?"
    assert not result["investigation"]["patterns"] and result["investigation"]["missing_information"]
    assert result["forecast_quality"] == "not_evaluated" and result["decision_usefulness"] is None
    assert repository.storage_metrics() == before


def test_legacy_runner_is_offline_and_does_not_rewrite_selection_claims(tmp_path):
    root = Path(__file__).parents[1]
    doc = root / "docs/DECISION_ENGINE_BENCHMARK.md"
    before = doc.read_bytes()
    runner = runpy.run_path(str(root / "scripts/benchmark_decision_engine.py"))["run_benchmark"]
    result = runner(tmp_path / "legacy.json")
    assert not result["provider_comparison_valid"] and result["cost_savings_claim"] is None
    assert result["summaries"]["jev_offline_simulation"]["execution_modes"] == {"simulation": 50}
    assert result["summaries"]["frontier_offline_simulation"]["execution_modes"] == {"simulation": 50}
    assert doc.read_bytes() == before
