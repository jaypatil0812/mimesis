"""Versioned, atomic reinterpretation of preserved evidence with change receipts."""
from datetime import UTC, datetime
import asyncio
import hashlib
import json
from uuid import uuid4

from memesis.extraction.contracts import DETERMINISTIC_VERSION
from memesis.extraction.pipeline import EvidenceGraphPipeline


def assertion_signature(record, repository):
    """Compare source meaning, not generated IDs or extraction lineage."""
    value = dict(record.object_value)
    for key in ("memory_version", "reviews", "projected_edge_id", "superseded_by_rebuild"):
        value.pop(key, None)
    spans = [repository.get_evidence_span(sid) for sid in record.evidence_span_ids]
    body = {"subject": str(record.subject_id), "predicate": record.predicate,
            "object": value, "stance": record.stance,
            "spans": sorted((s.start_offset, s.end_offset, s.exact_text) for s in spans if s)}
    return hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()


async def rebuild_evidence(repository, evidence_ids, *, interpretation_version="memory-worker-v1",
                           cheap_model=None, ambiguity_model=None, before_record=None, fence_record=None):
    report = {"id": str(uuid4()), "started_at": datetime.now(UTC).isoformat(),
              "extractor_version": DETERMINISTIC_VERSION, "interpretation_version": interpretation_version,
              "records": [], "raw_documents_modified": False,
              "historical_limitations": "Archived revisions preserve changes; historical graph reconstruction is not implemented."}
    for evidence_id in dict.fromkeys(evidence_ids):
        await asyncio.sleep(0)
        if before_record:
            before_record()
        receipt = {"evidence_id": str(evidence_id), "status": "failed"}
        try:
            with repository.atomic_repository() as atomic:
                before_all = atomic.assertions_for_evidence(evidence_id)
                before = [a for a in before_all
                          if a.review_state in {"accepted", "proposed"}]
                old = {a.id: a for a in before_all}
                rejected = {assertion_signature(a, atomic): a for a in before_all if a.review_state == "rejected"}
                old_by_signature = {}
                for a in before:
                    old_by_signature.setdefault(assertion_signature(a, atomic), []).append(a)
                pipeline = EvidenceGraphPipeline(atomic, cheap_model=cheap_model,
                    ambiguity_model=ambiguity_model, interpretation_version=interpretation_version)
                result = await pipeline.run(evidence_ids=[evidence_id])
                if result.failures:
                    raise ValueError(str(result.failures))
                if not result.evidence_processed:
                    receipt.update(status="unchanged", reason="current_version_already_projected",
                                   processing=result.as_metrics())
                else:
                    after = [a for a in atomic.assertions_for_evidence(evidence_id)
                             if a.review_state in {"accepted", "proposed"} and a.id not in old]
                    new_signatures = {assertion_signature(a, atomic) for a in after}
                    unchanged, added, retired, protected = [], [], [], []
                    for a in after:
                        signature = assertion_signature(a, atomic)
                        if signature in rejected:
                            atomic.retire_generated_assertion(a.id, report["id"])
                            protected.append({"id": str(rejected[signature].id), "reason": "prior_rejection_preserved"})
                            continue
                        matches = old_by_signature.get(signature, [])
                        if matches:
                            unchanged.extend(str(b.id) for b in matches)
                            atomic.retire_generated_assertion(a.id, report["id"])
                        else:
                            added.append(str(a.id))
                    model_names = set()
                    if cheap_model and result.llm_calls:
                        model_names.add(cheap_model.model_name)
                    if ambiguity_model and result.strong_model_calls:
                        model_names.add(ambiguity_model.model_name)
                    for a in before:
                        if assertion_signature(a, atomic) in new_signatures:
                            continue
                        # A rules-only run is not evidence that an earlier model
                        # interpretation was wrong. Keep it until that adapter
                        # actually re-evaluates the preserved source.
                        if a.extraction_model and a.extraction_model not in model_names:
                            protected.append({"id": str(a.id), "reason": "model_not_reexecuted"})
                        elif atomic.retire_generated_assertion(a.id, report["id"]):
                            retired.append(str(a.id))
                        else:
                            protected.append({"id": str(a.id), "reason": "human_review_or_owned_projection"})
                    if retired:
                        atomic.prune_retired_beliefs(evidence_id)
                    receipt.update(status="rebuilt", unchanged_assertion_ids=sorted(set(unchanged)),
                        added_assertion_ids=added, superseded_assertion_ids=retired,
                        protected_assertions=protected, processing=result.as_metrics())
                if fence_record:
                    fence_record(atomic)
                atomic.record_extraction_rebuild(uuid4(), {"rebuild_id": report["id"], **receipt})
        except Exception as error:
            receipt = {"evidence_id": str(evidence_id), "status": "failed",
                       "error": f"{type(error).__name__}: {error}", "rolled_back": True}
            try:
                repository.record_extraction_rebuild(uuid4(), {"rebuild_id": report["id"], **receipt})
            except Exception as audit_error:
                receipt["audit_error"] = type(audit_error).__name__
        report["records"].append(receipt)
    report["completed_at"] = datetime.now(UTC).isoformat()
    report["counts"] = {state: sum(r["status"] == state for r in report["records"])
                        for state in ("rebuilt", "unchanged", "failed")}
    return report
