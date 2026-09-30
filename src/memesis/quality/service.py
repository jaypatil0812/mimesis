"""No composite accuracy: collection, interpretation and utility have separate denominators."""
import asyncio
import hashlib
import json
import re
from collections import Counter
from datetime import UTC, datetime
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from memesis.config import settings
from memesis.db.session import make_engine, initialize_schema, make_session_factory
from memesis.graph.sql_repository import SqlGraphRepository
from memesis.domain.schemas import Source, SourcePolicy
from memesis.ingestion.contracts import CollectedDocument, CollectionBatch
from memesis.ingestion.service import IngestionService
from memesis.extraction.deterministic import DeterministicExtractor
from memesis.extraction.pipeline import EvidenceGraphPipeline
from memesis.extraction.contracts import DETERMINISTIC_VERSION, SCHEMA_VERSION
from memesis.investigations.contracts import InvestigationConfig, InvestigationScope
from memesis.investigations.service import InvestigationService, PatternModel
from memesis.quality.contracts import QualitySuite, CaseReview, LAYERS, RUBRIC
from memesis.db.models import DocumentRow, EvidenceRow
from sqlalchemy import select
from memesis.ingestion.normalizer import normalize_text


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str, ensure_ascii=False).encode()).hexdigest()


def write_new(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False, default=str)


class FixtureCollector:
    def __init__(self, case):
        self.case = case
        self.source = Source(source_key="quality:" + case.id, source_type="fixture", base_url="https://example.org")

    def source_policy(self, key):
        return SourcePolicy(source_id=key, terms_url="https://example.org", reviewed_at=datetime.now(UTC),
            active=True, policy={"access_method": "isolated_synthetic_fixture", "not_live_collection": True})

    async def collect(self, query, *, cursor, limit):
        documents = [CollectedDocument(external_id=d.id, canonical_url=d.source_url or f"https://example.org/{self.case.id}/{d.id}",
            source_url=d.source_url or f"https://example.org/{self.case.id}/{d.id}", source_type=d.source_type,
            raw_payload=d.text, text=d.text, original_reference=d.text[:280],
            retrieved_at=datetime.fromisoformat(d.known_at), published_at=datetime.fromisoformat(d.published_at),
            metadata=d.metadata) for d in self.case.documents if d.captured]
        return CollectionBatch(documents, None, complete=True)


def check(status, **details):
    return {"status": status, **details}


async def run_case(case, *, live_reasoning=False):
    db = make_engine("sqlite://")
    initialize_schema(db)
    repo = SqlGraphRepository(make_session_factory(db))
    try:
        collection = await IngestionService(repo).collect(FixtureCollector(case), case.question, limit=len(case.documents))
        evidence = repo.list_evidence()
        by_document = {e.external_id: e for e in evidence}
        with repo.session_factory() as session:
            captured_ids = set(session.scalars(select(DocumentRow.external_id)))
        missing = [d.id for d in case.documents if d.id not in captured_ids]
        # Reposts may share processing evidence while retaining distinct raw
        # documents. Deduplication must not be classified as a collection miss.
        for d in case.documents:
            if d.id in captured_ids and d.id not in by_document:
                duplicate = repo.find_evidence_by_hash(hashlib.sha256(normalize_text(d.text).encode()).hexdigest())
                if duplicate:
                    by_document[d.id] = duplicate
        # This is manifest coverage, not measured recall of a real platform.
        layers = {"collection": check("fail" if missing else "pass", measure="known_manifest_coverage",
            live_source_recall_evaluated=False, missing_document_ids=missing, receipt=collection.as_metrics())}
        extractor = DeterministicExtractor()
        raw = {d: asdict(extractor.extract(e)) for d, e in by_document.items()}
        predicted = [b["proposition"] for result in raw.values() for b in result["beliefs"]]
        if case.expected_beliefs is None:
            layers["extraction"] = check("not_evaluated", reason="Semantic extraction requires span/attribution/qualification review")
        else:
            # Final sentence periods are formatting, not negation/scope changes.
            canonical = lambda text: " ".join(text.split()).removesuffix(".")
            expected, actual = Counter(map(canonical, case.expected_beliefs)), Counter(map(canonical, predicted))
            layers["extraction"] = check("pass" if expected == actual else "fail",
                measure="exact_proposition_diagnostic_not_semantic_accuracy", expected=list(expected.elements()),
                predicted=list(actual.elements()), missed=list((expected - actual).elements()), extra=list((actual - expected).elements()))
        projection = await EvidenceGraphPipeline(repo).run()
        if projection.failures:
            layers["extraction"] = check("fail", failures=projection.failures, prior_diagnostic=layers["extraction"])
        authors = {}
        for d, e in by_document.items():
            author = next((p for p in extractor.extract_metadata(e).entities if p.key == "metadata_author"), None)
            if author and author.external_ids:
                identifier = author.external_ids[0]
                node = repo.find_node_by_identifier_value(identifier.identifier_type, identifier.value)
                if node:
                    authors[d] = str(node.id)
        pairs = [{**pair, "actual_same": authors.get(pair["left"]) == authors.get(pair["right"]),
                  "available": pair["left"] in authors and pair["right"] in authors} for pair in case.author_pairs]
        evaluated = [p for p in pairs if p["available"]]
        layers["resolution"] = check("fail" if any(p["actual_same"] != p["same"] for p in evaluated)
            else "pass" if evaluated else "not_evaluated", measure="stable_author_identity_pairs", pairs=pairs,
            upstream_missing_pairs=len(pairs) - len(evaluated), other_entity_resolution_requires_review=True)
        config = InvestigationConfig(name=case.id, question=case.question, scope=InvestigationScope(),
                                     max_patterns=8, max_followups_per_cycle=0, max_investigation_rounds=0)
        model_settings = settings if live_reasoning else settings.model_copy(update={"model_api_key": None})
        service = InvestigationService(repo, PatternModel(model_settings))
        packet = await asyncio.to_thread(service.context, config, [str(e.id) for e in evidence])
        retained = {e["id"] for e in packet.primary_evidence_references}
        available_required = [d for d in case.required_documents if d in by_document]
        omitted = [d for d in available_required if str(by_document[d].id) not in retained]
        layers["retrieval"] = check("fail" if omitted else "pass" if available_required else "not_evaluated",
            measure="required_counterevidence_and_premise_retention", omitted_available_document_ids=omitted,
            upstream_missing_document_ids=[d for d in case.required_documents if d not in by_document], coverage=packet.coverage)
        snapshot = await asyncio.to_thread(service.investigate, config, packet)
        execution = snapshot["reasoning_execution"]
        layers["reasoning"] = check("not_evaluated", reason="Semantic support needs human review; valid IDs do not prove entailment",
            execution=execution, structural_validation_completed=True,
            provider_failure=execution.get("status") in {"provider_failed", "invalid_response", "packet_too_large"})
        result = {"case_id": case.id, "case": case.model_dump(mode="json"), "layers": layers,
            "raw_extraction": raw, "projection": projection.as_metrics(), "document_evidence_ids": {d: str(e.id) for d, e in by_document.items()},
            "preserved_evidence": [e.model_dump(mode="json") for e in evidence],
            "packet": packet.model_dump(mode="json"), "investigation": snapshot,
            "quality_semantics": "Draft diagnostics are not validated semantic accuracy or customer utility"}
        result["trace_hash"] = fingerprint(result)
        return result
    finally:
        db.dispose()


async def run_suite(dataset, *, live_reasoning=False):
    suite = QualitySuite.model_validate(dataset)
    if live_reasoning and (not settings.model_api_key or not settings.reason_strong_model):
        raise ValueError("Live reasoning requires an explicitly configured key and reasoning model")
    traces = [await run_case(case, live_reasoning=live_reasoning) for case in suite.cases]
    report = {"version": "intelligence-quality-v1", "created_at": datetime.now(UTC).isoformat(),
        "extractor_version": DETERMINISTIC_VERSION, "extraction_schema": SCHEMA_VERSION,
        "code_hashes": {str(path.relative_to(Path(__file__).parents[1])): hashlib.sha256(path.read_bytes()).hexdigest()
                        for folder in ("quality", "extraction", "retrieval", "investigations", "reasoning")
                        for path in (Path(__file__).parents[1] / folder).glob("*.py")},
        "dataset_hash": fingerprint(dataset), "live_reasoning_requested": live_reasoning, "traces": traces,
        "draft_diagnostics": {layer: dict(Counter(t["layers"][layer]["status"] for t in traces)) for layer in LAYERS},
        "human_reviewed_quality": None, "customer_decision_usefulness": None,
        "provider_comparison_valid": False,
        "limitations": ["Synthetic collector manifest checks do not measure real-source recall.",
            "Gold labels are drafts unless independently approved by a human.",
            "Exact proposition matches are diagnostic proxies; semantic equivalence needs review.",
            "No customer decision effect is established by a regression test or LLM grade."]}
    report["artifact_hash"] = fingerprint(report)
    return report


def verify_report(report):
    if fingerprint({k: v for k, v in report.items() if k != "artifact_hash"}) != report["artifact_hash"]:
        raise ValueError("Report changed after execution; regenerate the review packet")
    for trace in report["traces"]:
        if fingerprint({k: v for k, v in trace.items() if k != "trace_hash"}) != trace["trace_hash"]:
            raise ValueError("Trace hash mismatch")


def review_template(report):
    verify_report(report)
    return {"artifact_hash": report["artifact_hash"], "reviews": [{"case_id": t["case_id"], "trace_hash": t["trace_hash"],
        "gold_approved": False, "reviewer": None, "reviewer_role": "pending",
        "layer_verdicts": {layer: "pending" for layer in LAYERS}, "findings": {layer: "" for layer in LAYERS},
        "usefulness": {key: None for key in RUBRIC}, "decision_effect": "pending",
        "decision_before": "", "decision_after": "", "customer_confirmed": False} for t in report["traces"]]}


def review_guide(report):
    verify_report(report)
    lines = ["# Intelligence evaluation review", "", "Gold labels are drafts. No human quality score or customer validation has been established.", "",
        "Inspect report.json for full source text, extraction proposals, preserved observations, graph paths and investigation output. Edit reviews.json only; report/trace hashes bind reviews to this run.", "",
        "For each layer choose pass, fail or not_evaluated and explain the finding with document/observation IDs and spans. Structural validity is not semantic support. Unconfigured reasoning must remain not_evaluated.", "",
        "Rate traceability, counterevidence, alternatives, uncertainty and next decision step: 0=absent/misleading, 1=partial, 2=adequate. A usefulness rating is a human assessment, not proof of business outcomes.", "",
        "Record decision_before and decision_after. customer_confirmed requires an actual customer decision exercise; synthetic cases are not customer validation.", ""]
    for trace in report["traces"]:
        case = trace["case"]
        lines += ["## " + case["id"], "", "**Question:** " + case["question"], "",
            "**Decision:** " + case["decision"], "", "**Draft expectation:** " + case["expected_answer_kind"], "",
            "**Assess:** " + " ".join(case["assessment_notes"]), ""]
        for doc in case["documents"]:
            lines += [f"### Source {doc['id']} (captured={doc['captured']})", "", doc["text"], ""]
        lines += ["**Layer diagnostics:** " + "; ".join(f"{k}: {v['status']}" for k, v in trace["layers"].items()), "",
            "**Extracted belief text:** " + json.dumps([b["proposition"] for r in trace["raw_extraction"].values() for b in r["beliefs"]], ensure_ascii=False), "",
            "**Reasoning execution:** " + trace["investigation"]["reasoning_execution"]["status"], "",
            "**Review:** pending; trace_hash=" + trace["trace_hash"], ""]
    return "\n".join(lines)


def score_reviews(report, submitted):
    verify_report(report)
    if submitted.get("artifact_hash") != report["artifact_hash"]:
        raise ValueError("Reviews belong to a different report")
    traces = {t["case_id"]: t for t in report["traces"]}
    reviewed = [CaseReview.model_validate(r) for r in submitted["reviews"]]
    if len({r.case_id for r in reviewed}) != len(reviewed):
        raise ValueError("Duplicate case reviews would distort denominators")
    for r in reviewed:
        if r.case_id not in traces or r.trace_hash != traces[r.case_id]["trace_hash"]:
            raise ValueError("Review does not match an executed trace")
        if r.layer_verdicts["reasoning"] == "pass" and traces[r.case_id]["investigation"]["reasoning_execution"].get("status") != "completed":
            raise ValueError("Unconfigured/failed reasoning cannot be graded as passing live explanation quality")
    approved = [r for r in reviewed if r.gold_approved]
    layers = {}
    for layer in LAYERS:
        values = Counter(r.layer_verdicts[layer] for r in approved)
        n = values["pass"] + values["fail"]
        layers[layer] = {"pass": values["pass"], "fail": values["fail"], "not_evaluated": values["not_evaluated"],
            "evaluated_cases": n, "failure_rate": values["fail"] / n if n else None}
    rated = [r for r in approved if r.decision_effect != "pending"]
    customer_rated = [r for r in rated if r.customer_confirmed and traces[r.case_id]["case"]["origin"] in {"customer_supplied", "user_supplied"}]
    return {"artifact_hash": report["artifact_hash"], "review_hash": fingerprint(submitted),
        "reviewed_cases": len(approved), "total_cases": len(traces), "unreviewed_cases": len(traces) - len(approved),
        "layers": layers, "decision_rated_cases": len(rated), "decision_effects": dict(Counter(r.decision_effect for r in rated)),
        "rubric_means": {key: sum(r.usefulness[key] for r in rated) / len(rated) if rated else None for key in RUBRIC},
        "customer_rated_cases": len(customer_rated), "customer_decision_effects": dict(Counter(r.decision_effect for r in customer_rated)),
        "customer_validation_status": "human_reported" if customer_rated else "not_evaluated",
        "findings": [r.model_dump(mode="json") for r in approved],
        "methodology": "Human-reported assessments, not independently authenticated reviewer identities; no combined accuracy score"}


def compare_provider_traces(records):
    """Reject simulator/fallback/cached results before reporting paired live measurements."""
    eligible, excluded = [], []
    for record in records:
        left, right = record["left"], record["right"]
        reasons = []
        for label, trace in (("left", left), ("right", right)):
            meta = trace.get("metadata", {})
            if meta.get("execution_mode") != "live" or not meta.get("provider_call_succeeded"):
                reasons.append(label + ": not an attested successful live call")
            if "simulat" in trace.get("provider", "") or meta.get("cache_hit") or meta.get("offline_calibrated"):
                reasons.append(label + ": simulation/fallback/cache excluded")
            if not meta.get("request_hash") or not meta.get("response_hash"):
                reasons.append(label + ": missing request/response receipts")
        for field in ("input_hash", "decision_type", "input_references"):
            if not left.get(field) or left.get(field) != right.get(field):
                reasons.append("Unpaired " + field)
        if left.get("metadata", {}).get("allowed_outputs") != right.get("metadata", {}).get("allowed_outputs"):
            reasons.append("Different output contracts")
        if not left.get("metadata", {}).get("allowed_outputs"):
            reasons.append("Missing bounded output contract")
        if reasons:
            excluded.append({"case_id": record["case_id"], "reasons": reasons})
        else:
            eligible.append(record)
    return {"status": "paired_live_receipts_require_quality_review" if eligible else "not_comparable",
        "eligible_pairs": len(eligible), "excluded": excluded,
        "measurements": [{"case_id": r["case_id"], "left_latency_ms": r["left"].get("latency_ms"),
            "right_latency_ms": r["right"].get("latency_ms"),
            "token_comparison_available": all(t.get("metadata", {}).get("usage_source") == "provider_reported" for t in (r["left"], r["right"])),
            "billing_comparison_available": all(t.get("metadata", {}).get("cost_source") == "provider_reported" for t in (r["left"], r["right"]))} for r in eligible],
        "quality_winner": None, "cost_savings_claim": None,
        "limitations": "Submitted receipts need human audit and matched-condition repetitions; no accuracy or savings conclusion from latency alone"}


def sample_live(repository, limit=24):
    """Read-only, stratified queue; keyword cues nominate examples, never label truth."""
    if not 1 <= limit <= 100:
        raise ValueError("Sample limit must be between 1 and 100")
    candidates = []
    sources = ("github", "hackernews", "rss", "bluesky", "openalex")
    with repository.session_factory() as session:
        for source in sources:
            rows = session.scalars(select(EvidenceRow).where(EvidenceRow.source_type == source)
                .order_by(EvidenceRow.retrieved_at.desc(), EvidenceRow.id).limit(100))
            for row in rows:
                text = row.normalized_text or row.raw_text
                tags = []
                if re.search(r"\b(not|never|cannot|no longer|unless)\b", text, re.I): tags.append("negation_or_condition_cue")
                if re.search(r'["“”]|\b(quote|says|according to)\b', text, re.I): tags.append("quotation_or_attribution_cue")
                if re.search(r"\b(but|however|instead|contradict)\b", text, re.I): tags.append("possible_counterevidence_cue")
                if re.search(r"\b(changed|previously|used to|no longer)\b", text, re.I): tags.append("position_change_cue")
                if row.metadata_json.get("duplicate_of_evidence_id") or row.metadata_json.get("origin_url"): tags.append("repost_cue")
                candidates.append((source, len(tags), row.id, tags))
    buckets = {source: sorted((r for r in candidates if r[0] == source), key=lambda r: (-r[1], r[2])) for source in sources}
    chosen = []
    while len(chosen) < limit and any(buckets.values()):
        for source in sources:
            if buckets[source] and len(chosen) < limit:
                chosen.append(buckets[source].pop(0))
    samples = []
    from uuid import UUID
    for source, _, key, tags in chosen:
        evidence = repository.get_evidence(UUID(key))
        samples.append({"evidence": evidence.model_dump(mode="json"), "selection_cues": tags,
            "gold_review_status": "draft", "reviewer": None, "expected_observations": [],
            "expected_identities": [], "source_independence": "unknown", "review_notes": "",
            "collection_recall": None, "semantic_labels_validated": False})
    return {"version": "public-review-queue-v1", "created_at": datetime.now(UTC).isoformat(),
        "question": "What's the next big thing?", "customer_confirmed": False,
        "samples": samples, "sampling": "At most 100 recent records per configured source, then cue-prioritized round robin; not random or representative",
        "limitations": "Cues are not semantic labels. Full normalized text and preserved document IDs are retained; raw documents stay in the source database."}


def export_live_investigations(repository):
    from memesis.investigations.store import InvestigationStore
    store = InvestigationStore(repository.session_factory)
    watches = []
    for record in store.list():
        watches.append({"config": record["config"], "state": record["state"],
            "snapshots": store.history(record["id"], 2), "recent_runs": store.runs(record["id"], 3)})
    return {"version": "live-investigation-review-v1", "created_at": datetime.now(UTC).isoformat(),
        "user_question": "What's the next big thing?", "customer_confirmed": False, "watches": watches,
        "expected_assessment": ["Technical issue frequency is not independent demand or market size.",
            "Offer competing hypotheses and identify buyer/budget/adoption/time-horizon gaps.",
            "No next-big-thing prediction is validated by these records."],
        "reviewer": None, "review_status": "pending", "decision_before": "", "decision_after": "",
        "decision_usefulness": None}


def investigate_live_question(repository, sample, question="What's the next big thing?"):
    """Read existing connected memory; no new collection, extraction or graph writes."""
    config = InvestigationConfig(name="Decision usefulness review", question=question,
        scope=InvestigationScope(graph_hops=3), max_patterns=8, max_followups_per_cycle=0, max_investigation_rounds=0)
    service = InvestigationService(repository, PatternModel(settings.model_copy(update={"model_api_key": None})))
    seeds = [r["evidence"]["id"] for r in sample["samples"]]
    packet = service.context(config, seeds)
    result = {"question": question, "origin": "user_supplied", "customer_confirmed": False,
        "research_seed_ids": seeds, "scope_semantics": "Bounded sampled public evidence; not complete market coverage",
        "investigation": service.investigate(config, packet), "packet": packet.model_dump(mode="json"),
        "decision_contract_gaps": ["Define 'big': revenue, adoption, technical progress or buyer urgency.",
            "Specify target market, buyer, decision and time horizon.",
            "Seek independent adoption/budget evidence and test competing hypotheses."],
        "review_status": "pending", "reviewer": None, "decision_before": "", "decision_after": "",
        "decision_usefulness": None, "forecast_quality": "not_evaluated", "live_reasoning_enabled": False}
    result["trace_hash"] = fingerprint(result)
    return result
