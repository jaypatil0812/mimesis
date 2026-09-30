import asyncio
from dataclasses import replace
import pytest
from memesis.extraction.deterministic import DeterministicExtractor
from memesis.extraction.pipeline import EvidenceGraphPipeline
from memesis.extraction.rebuild import rebuild_evidence
from memesis.knowledge.memory import observation_candidates
from memesis.domain.schemas import EdgeType
from test_evidence_graph import persist_evidence

BATTERY = "Recycling costs declined for nickel-rich batteries but did not decline for lithium-iron-phosphate batteries in the same pilot."


def test_generic_claims_and_contrasts_keep_shared_source_scope(repository):
    evidence = persist_evidence(repository, "battery", BATTERY)
    extracted = DeterministicExtractor().extract(evidence)
    assert extracted.beliefs[0].proposition == BATTERY.rstrip(".")
    assert extracted.ambiguous_spans == ((0, len(BATTERY)),)
    observations = list(observation_candidates(BATTERY))
    assert len(observations) == 2
    assert observations[0].statement == "Recycling costs declined for nickel-rich batteries"
    assert observations[1].statement == "did not decline for lithium-iron-phosphate batteries in the same pilot."
    assert all(o.context["source_statement"] == BATTERY for o in observations)
    assert all(BATTERY[o.start:o.end] == o.statement for o in observations)
    assert "same pilot" in extracted.beliefs[0].scope


def test_reporting_prefix_and_criticism_are_not_stripped(repository):
    text = 'The CEO says "costs will decline" but I reject that claim.'
    evidence = persist_evidence(repository, "quoted", text)
    result = DeterministicExtractor().extract(evidence)
    assert result.beliefs[0].proposition == text.rstrip(".")
    assert not any(r.edge_type == EdgeType.BELIEVES for r in result.relationships)
    assert len(list(observation_candidates(text))) == 1


def test_rebuild_is_idempotent_and_preserves_source_and_unchanged_relations(repository):
    evidence = persist_evidence(repository, "battery", BATTERY)
    asyncio.run(EvidenceGraphPipeline(repository, interpretation_version="old").run())
    raw_before = repository.get_evidence(evidence.id).model_dump()
    first = asyncio.run(rebuild_evidence(repository, [evidence.id]))
    assert first["counts"]["rebuilt"] == 1, first
    assert first["records"][0]["unchanged_assertion_ids"]
    assert repository.get_evidence(evidence.id).model_dump() == raw_before
    edges = repository.list_edges()
    assert len(edges) == 1
    second = asyncio.run(rebuild_evidence(repository, [evidence.id]))
    assert second["counts"]["unchanged"] == 1
    assert repository.list_edges() == edges


def test_rebuild_failure_rolls_back_generated_assertions(repository, monkeypatch):
    evidence = persist_evidence(repository, "rollback", BATTERY)
    before = repository.storage_metrics()
    def fail(*args, **kwargs):
        raise RuntimeError("injected failure after projection")
    monkeypatch.setattr(type(repository), "record_extraction_rebuild", fail)
    result = asyncio.run(rebuild_evidence(repository, [evidence.id]))
    assert result["counts"]["failed"] == 1 and result["records"][0]["rolled_back"]
    assert repository.storage_metrics() == before


def test_obsolete_generated_assertion_is_retracted_and_reviewed_one_is_protected(repository, monkeypatch):
    evidence = persist_evidence(repository, "old", "Costs will decline for recycling facilities.")
    asyncio.run(EvidenceGraphPipeline(repository, interpretation_version="old").run())
    relation = next(a for a in repository.assertions_for_evidence(evidence.id) if a.predicate == "EXPRESSES")
    original = DeterministicExtractor.extract
    def metadata_only(self, item):
        result = original(self, item)
        return replace(result, beliefs=(), relationships=tuple(r for r in result.relationships if r.edge_type != EdgeType.EXPRESSES))
    monkeypatch.setattr(DeterministicExtractor, "extract", metadata_only)
    report = asyncio.run(rebuild_evidence(repository, [evidence.id]))
    assert str(relation.id) in report["records"][0]["superseded_assertion_ids"]
    assert repository.get_assertion(relation.id).review_state == "superseded"
    assert not repository.list_edges()
    # Independent reviewed ledger records never get silently overwritten.
    memory = next(a for a in repository.list_memory_assertions() if a.object_value["observation_type"] == "attributed_claim")
    repository.review_memory_assertion(memory.id, "accepted", "human", "Reviewed source wording")
    protected = repository.retire_generated_assertion(memory.id, "another-rebuild")
    assert not protected and repository.get_assertion(memory.id).review_state == "accepted"


def test_shared_scope_metadata_cannot_be_invented(repository):
    from memesis.knowledge.memory import ConnectedMarketMemory
    evidence = persist_evidence(repository, "bad-scope", BATTERY)
    asyncio.run(EvidenceGraphPipeline(repository).run())
    content = next(n for n in repository.list_nodes() if n.node_type.value == "Content")
    normalized = repository.get_normalized_document_for_version(evidence.document_version_id)
    proposal = next(observation_candidates(BATTERY))
    proposal = replace(proposal, context={**proposal.context, "source_statement": "invented context"})
    with pytest.raises(ValueError, match="enclosing exact source"):
        ConnectedMarketMemory(repository).record(evidence, normalized, proposal, {"content": content})


def test_changed_memory_queues_affected_watch_without_overwriting_history(repository):
    from memesis.investigations.store import InvestigationStore
    from memesis.investigations.contracts import InvestigationConfig
    from memesis.db.models import InvestigationRow
    store = InvestigationStore(repository.session_factory)
    watch = store.create(InvestigationConfig(name="Battery watch", question="What changed?", scope={}))
    evidence = persist_evidence(repository, "watched", BATTERY)
    with repository.session_factory.begin() as session:
        row = session.get(InvestigationRow, watch["id"])
        row.state_json = {"tracked_evidence_ids": [str(evidence.id)], "last_fingerprint": "old"}
    affected = store.invalidate_evidence([evidence.id], "test-rebuild")
    assert affected == [watch["id"]]
    state = store.get(watch["id"])["state"]
    assert "last_fingerprint" not in state
    assert state["memory_rebuild_pending"]["rebuild_id"] == "test-rebuild"


def test_rebuild_cannot_resurrect_a_rejected_source_relation(repository):
    evidence = persist_evidence(repository, "rejected", "Costs will decline for recycling facilities.")
    asyncio.run(EvidenceGraphPipeline(repository, interpretation_version="old").run())
    relation = next(a for a in repository.assertions_for_evidence(evidence.id) if a.predicate == "EXPRESSES")
    repository.review_assertion(relation.id, "rejected")
    assert not repository.list_edges()
    report = asyncio.run(rebuild_evidence(repository, [evidence.id]))
    assert report["counts"]["rebuilt"] == 1, report["records"]
    assert any(p["reason"] == "prior_rejection_preserved" for p in report["records"][0]["protected_assertions"])
    assert not repository.list_edges()


def test_exact_retired_belief_can_be_re_supported_without_reusing_a_deleted_identity(repository, monkeypatch):
    from memesis.extraction.resolution import _belief_signature
    evidence = persist_evidence(repository, "restore", "Costs will decline for recycling facilities.")
    asyncio.run(EvidenceGraphPipeline(repository, interpretation_version="old").run())
    result = DeterministicExtractor().extract(evidence)
    signature = _belief_signature(result.beliefs[0])
    old = repository.find_node_by_external_identifier("belief_signature", signature)
    original = DeterministicExtractor.extract
    def metadata_only(self, item):
        result = original(self, item)
        return replace(result, beliefs=(), relationships=tuple(r for r in result.relationships if r.edge_type != EdgeType.EXPRESSES))
    monkeypatch.setattr(DeterministicExtractor, "extract", metadata_only)
    report = asyncio.run(rebuild_evidence(repository, [evidence.id]))
    assert report["counts"]["rebuilt"] == 1, report
    assert repository.find_node_by_external_identifier("belief_signature", signature) is None
    restored = repository.restore_retired_belief(signature)
    assert restored.id == old.id


def test_corrected_relation_qualifiers_keep_a_new_owned_edge(repository, monkeypatch):
    evidence = persist_evidence(repository, "qualifiers", "Costs will decline for recycling facilities.")
    asyncio.run(EvidenceGraphPipeline(repository, interpretation_version="old").run())
    old_edge = repository.list_edges()[0]
    original = DeterministicExtractor.extract
    def corrected(self, item):
        result = original(self, item)
        return replace(result, relationships=tuple(replace(r, qualifiers={**r.qualifiers, "basis": "corrected"})
                                                  for r in result.relationships))
    monkeypatch.setattr(DeterministicExtractor, "extract", corrected)
    report = asyncio.run(rebuild_evidence(repository, [evidence.id]))
    assert report["counts"]["rebuilt"] == 1, report["records"]
    edges = repository.list_edges()
    assert len(edges) == 1 and edges[0].id != old_edge.id
    assert edges[0].qualifiers["basis"] == "corrected"
