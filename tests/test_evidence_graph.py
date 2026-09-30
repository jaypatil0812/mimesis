import asyncio
from datetime import UTC, datetime
from hashlib import sha256

from memesis.db.models import AssertionRow, EvidenceSpanRow, MergeDecisionRow
from memesis.domain.schemas import (
    Document,
    DocumentVersion,
    EdgeType,
    Evidence,
    ExtractionMethod,
    NodeType,
    NormalizedDocument,
    Provenance,
    Source,
)
from memesis.extraction.contracts import (
    BeliefProposal,
    EntityProposal,
    ExtractionResult,
    RelationshipProposal,
)
from memesis.extraction.deterministic import DeterministicExtractor
from memesis.extraction.pipeline import EvidenceGraphPipeline
from memesis.extraction.resolution import EntityResolver, normalize_alias


def persist_evidence(repository, key, text, *, metadata=None, source_type="fixture"):
    now = datetime.now(UTC)
    source = repository.add_source(
        Source(
            source_key=f"fixture:{key}",
            source_type=source_type,
            base_url=f"https://example.org/{key}",
        )
    )
    document = repository.add_document(
        Document(
            source_id=source.id,
            external_id=key,
            canonical_url=f"https://example.org/{key}",
        )
    )
    version = repository.add_document_version(
        DocumentVersion(
            document_id=document.id,
            content_hash=sha256(text.encode()).hexdigest(),
            raw_payload=text,
            retrieved_at=now,
            published_at=now,
        )
    )
    evidence = repository.add_evidence(
        Evidence(
            source_id=source.id,
            document_version_id=version.id,
            source_url=f"https://example.org/{key}",
            source_type=source_type,
            retrieved_at=now,
            published_at=now,
            original_reference=text,
            raw_text=text,
            normalized_text=text,
            content_hash=sha256(text.encode()).hexdigest(),
            external_id=key,
            metadata=metadata or {},
        )
    )
    repository.add_normalized_document(
        NormalizedDocument(
            document_version_id=version.id,
            normalizer_version="test-v1",
            normalized_text=text,
            content_hash=sha256(text.encode()).hexdigest(),
            provenance=Provenance(
                source_url=evidence.source_url,
                source_type=source_type,
                retrieved_at=now,
                published_at=now,
                original_reference=text,
                evidence_ids=(evidence.id,),
                confidence=1.0,
                extraction_method=ExtractionMethod.DETERMINISTIC,
            ),
        )
    )
    return evidence


def test_topic_is_not_a_belief_but_proposition_is():
    extractor = DeterministicExtractor()
    topic = Evidence(
        source_id="00000000-0000-0000-0000-000000000001",
        source_url="https://example.org/topic",
        source_type="test",
        retrieved_at=datetime.now(UTC),
        original_reference="topic",
        raw_text="Small language models",
        normalized_text="Small language models",
        content_hash=sha256(b"Small language models").hexdigest(),
    )
    assert not extractor.extract(topic).beliefs
    proposition = (
        "Small specialized models will replace frontier models for many enterprise workloads."
    )
    claim = topic.model_copy(
        update={
            "raw_text": proposition,
            "normalized_text": proposition,
        }
    )
    assert extractor.extract(claim).beliefs[0].modality == "predicted"


def test_pipeline_projects_spans_assertions_edges_and_caches(repository):
    persist_evidence(
        repository,
        "claim",
        "Sam Altman (@sama), CEO of OpenAI, said that specialized models will serve "
        "many enterprise workloads.",
    )
    first = asyncio.run(EvidenceGraphPipeline(repository).run())
    assert first.failures == []
    assert first.beliefs_resolved == 1
    assert {edge.edge_type for edge in repository.list_edges()} == {
        EdgeType.WORKS_AT,
        EdgeType.EXPRESSES,
    }
    with repository._sessions() as session:
        legacy = session.query(AssertionRow).filter(AssertionRow.predicate != "MEMORY_OBSERVATION").all()
        assert len({span for row in legacy for span in row.evidence_span_ids}) == 2
        assert session.query(AssertionRow).filter_by(predicate="MEMORY_OBSERVATION", review_state="proposed").count() > 0
        assert session.query(AssertionRow).filter_by(review_state="accepted").count() == 2
    before = repository.storage_metrics()
    second = asyncio.run(EvidenceGraphPipeline(repository).run())
    assert second.extraction_cache_hits == 1
    assert repository.storage_metrics() == before


def test_duplicate_content_reuses_extraction_but_projects_each_source_once(repository):
    text = "Specialized models will reduce cost for enterprise inference workloads."
    first = persist_evidence(repository, "duplicate-1", text)
    second = persist_evidence(repository, "duplicate-2", text)
    report = asyncio.run(EvidenceGraphPipeline(repository).run())
    assert report.evidence_processed == 2
    assert report.extraction_cache_hits == 1
    assert report.llm_calls == 0
    edges = repository.list_edges()
    assert len(edges) == 2
    assert {edge.provenance.evidence_ids[0] for edge in edges} == {first.id, second.id}
    repeat = asyncio.run(EvidenceGraphPipeline(repository).run())
    assert repeat.extraction_cache_hits == 2
    assert repeat.evidence_processed == 0
    assert len(repository.list_edges()) == 2


def test_stable_handle_resolves_but_same_name_alone_does_not(repository):
    persist_evidence(
        repository, "sam-1", "Sam Altman (@sama), CEO of OpenAI, said that models will improve."
    )
    persist_evidence(
        repository,
        "sam-2",
        "Sam Altman (@sama), founder of OpenAI, predicts that demand will increase.",
    )
    persist_evidence(
        repository, "alex-1", "Alex Smith, CEO of Acme Systems, said that cost will decline."
    )
    persist_evidence(
        repository, "alex-2", "Alex Smith, CTO at Beta Compute, said that demand will increase."
    )
    report = asyncio.run(EvidenceGraphPipeline(repository).run())
    assert not report.failures
    sama = repository.find_nodes_by_alias(normalize_alias("@sama"), NodeType.PERSON.value)
    alex = repository.find_nodes_by_alias(normalize_alias("Alex Smith"), NodeType.PERSON.value)
    assert len({node.id for node in sama}) == 1
    assert len({node.id for node in alex}) == 2


class CheapFixtureModel:
    model_name = "cheap-structured-test"
    prompt_version = "evidence-graph-extract-v1"

    async def extract(self, text, *, context):
        proposition = (
            "Infrastructure architecture improves deployment operations across several teams"
        )
        return ExtractionResult(
            beliefs=(
                BeliefProposal(
                    "model-belief",
                    proposition,
                    0,
                    len(proposition),
                    "supports",
                    "observed",
                    "ai infrastructure",
                    "current",
                    0.95,
                ),
            ),
            relationships=(
                RelationshipProposal(
                    EdgeType.EXPRESSES,
                    "content",
                    "model-belief",
                    0,
                    len(proposition),
                    0.95,
                    {"stance": "supports"},
                ),
            ),
            extraction_method=ExtractionMethod.EXTRACTED,
            extraction_model=self.model_name,
            prompt_version=self.prompt_version,
            input_tokens=20,
            output_tokens=8,
        )


def test_cheap_model_fallback_records_model_prompt_tokens_and_evidence(repository):
    text = "Infrastructure architecture improves deployment operations across several teams."
    persist_evidence(repository, "ambiguous", text)
    report = asyncio.run(EvidenceGraphPipeline(repository, cheap_model=CheapFixtureModel()).run())
    assert report.llm_calls == 1
    assert (report.input_tokens, report.output_tokens) == (20, 8)
    with repository._sessions() as session:
        row = session.query(AssertionRow).filter_by(extraction_method="extracted").filter(AssertionRow.predicate != "MEMORY_OBSERVATION").one()
        assert row.extraction_model == "cheap-structured-test"
        assert row.prompt_version == "evidence-graph-extract-v1"
        assert row.evidence_span_ids
        assert row.review_state == "proposed"


class HallucinatingModel(CheapFixtureModel):
    async def extract(self, text, *, context):
        result = await super().extract(text, context=context)
        return ExtractionResult(
            entities=(
                EntityProposal(
                    "invented",
                    NodeType.COMPANY,
                    "Invented Company",
                    0,
                    10,
                    confidence=0.99,
                ),
            ),
            beliefs=result.beliefs,
            relationships=result.relationships,
            extraction_method=result.extraction_method,
            extraction_model=result.extraction_model,
            prompt_version=result.prompt_version,
        )


def test_model_hallucinated_entity_without_exact_span_is_rejected(repository):
    text = "Infrastructure architecture improves deployment operations across several teams."
    persist_evidence(repository, "hallucination", text)
    report = asyncio.run(EvidenceGraphPipeline(repository, cheap_model=HallucinatingModel()).run())
    assert not report.failures
    assert all(node.name != "Invented Company" for node in repository.list_nodes())


def test_reviewed_merge_is_evidence_backed_and_names_never_auto_merge(repository):
    evidence = persist_evidence(
        repository, "merge", "Jordan Lee, CEO of One Labs, said models will improve."
    )
    asyncio.run(EvidenceGraphPipeline(repository).run())
    people = repository.find_nodes_by_alias(normalize_alias("Jordan Lee"), NodeType.PERSON.value)
    # Create another unresolved same-name candidate from independent evidence.
    persist_evidence(
        repository, "merge-2", "Jordan Lee, CTO at Two Labs, said demand will increase."
    )
    asyncio.run(EvidenceGraphPipeline(repository).run())
    people = repository.find_nodes_by_alias(normalize_alias("Jordan Lee"), NodeType.PERSON.value)
    assert len(people) == 2
    with repository._sessions() as session:
        span_id = session.query(EvidenceSpanRow.id).first()[0]
    EntityResolver(repository).record_reviewed_merge(
        people[0], people[1], evidence, span_id, decided_by="reviewer:test"
    )
    with repository._sessions() as session:
        assert session.query(MergeDecisionRow).count() == 1
