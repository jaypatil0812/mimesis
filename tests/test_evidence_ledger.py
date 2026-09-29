from datetime import UTC, datetime
from hashlib import sha256
from uuid import uuid4

import pytest

from memesis.db.models import DocumentVersionRow, GraphRevisionRow
from memesis.domain.schemas import (
    Assertion,
    Belief,
    Content,
    Document,
    DocumentVersion,
    EdgeType,
    Evidence,
    EvidenceSpan,
    ExtractionMethod,
    NormalizedDocument,
    Provenance,
    Source,
    SourcePolicy,
)


def test_versioned_document_to_reviewable_assertion_round_trip(repository):
    now = datetime.now(UTC)
    source = repository.add_source(
        Source(
            source_key="fixture:evidence-ledger",
            source_type="reviewed_fixture",
            base_url="https://example.org/report",
        )
    )
    policy = repository.add_source_policy(
        SourcePolicy(
            source_id=source.id,
            terms_url="https://example.org/terms",
            reviewed_at=now,
            policy={"retention_days": 365, "redistribute": False},
            active=True,
        )
    )
    assert policy.active

    document = repository.add_document(
        Document(
            source_id=source.id,
            external_id="report-1",
            canonical_url="https://example.org/report",
        )
    )
    raw_v1 = "The claim is that specialized models reduce inference cost."
    v1 = DocumentVersion(
        document_id=document.id,
        content_hash=sha256(raw_v1.encode()).hexdigest(),
        raw_payload=raw_v1,
        retrieved_at=now,
        published_at=now,
    )
    saved_v1 = repository.add_document_version(v1)
    assert repository.add_document_version(v1).id == saved_v1.id

    v2_text = raw_v1 + " A later update adds a benchmark."
    v2 = repository.add_document_version(
        DocumentVersion(
            document_id=document.id,
            content_hash=sha256(v2_text.encode()).hexdigest(),
            raw_payload=v2_text,
            retrieved_at=now,
            published_at=now,
        )
    )
    assert v2.id != saved_v1.id
    with repository._sessions() as session:
        assert (
            session.query(DocumentVersionRow).filter_by(document_id=str(document.id)).count() == 2
        )

    evidence = repository.add_evidence(
        Evidence(
            source_id=source.id,
            source_url=document.canonical_url,
            source_type=source.source_type,
            retrieved_at=now,
            published_at=now,
            original_reference="report paragraph 1",
            raw_text=v2_text,
            normalized_text=v2_text,
            content_hash=sha256(v2_text.encode()).hexdigest(),
        )
    )
    belief_id = uuid4()
    content_id = uuid4()
    provenance = Provenance(
        source_url=document.canonical_url,
        source_type=source.source_type,
        retrieved_at=now,
        published_at=now,
        original_reference="report paragraph 1",
        evidence_ids=(evidence.id,),
        confidence=0.94,
        extraction_method=ExtractionMethod.EXTRACTED,
        extraction_model="extract-small-test",
        entity_ids=(belief_id, content_id),
    )
    normalized_text = "The claim is that specialized models reduce inference cost."
    normalized = repository.add_normalized_document(
        NormalizedDocument(
            document_version_id=v2.id,
            normalizer_version="plain-text-1",
            normalized_text=normalized_text,
            content_hash=sha256(normalized_text.encode()).hexdigest(),
            provenance=provenance,
        )
    )
    start = normalized_text.index("specialized models")
    exact = "specialized models reduce inference cost"
    span = repository.add_evidence_span(
        EvidenceSpan(
            normalized_document_id=normalized.id,
            start_offset=start,
            end_offset=start + len(exact),
            exact_text=exact,
            content_hash=sha256(exact.encode()).hexdigest(),
            provenance=provenance,
        )
    )
    belief = repository.add_node(
        Belief(id=belief_id, name="Specialized models reduce inference cost", provenance=provenance)
    )
    content = repository.add_node(
        Content(id=content_id, name="Report paragraph", provenance=provenance)
    )
    assertion = repository.add_assertion(
        Assertion(
            subject_id=content.id,
            predicate=EdgeType.EXPRESSES.value,
            object_value={"belief_id": str(belief.id)},
            stance="supports",
            confidence=0.94,
            evidence_span_ids=(span.id,),
            extraction_method=ExtractionMethod.EXTRACTED,
            extraction_model="extract-small-test",
            prompt_version="extract-beliefs-v1",
            ontology_version="memesis-0.1",
            recorded_at=now,
            provenance=provenance,
        )
    )
    assert assertion.evidence_span_ids == (span.id,)
    assert assertion.provenance.source_url == document.canonical_url
    assert assertion.provenance.extraction_model == "extract-small-test"
    assert not repository.list_active_assertions()
    assert repository.review_assertion(assertion.id, "accepted").review_state == "accepted"
    assert repository.list_active_assertions(content.id)[0].id == assertion.id
    assert repository.review_assertion(assertion.id, "superseded").review_state == "superseded"
    assert not repository.list_active_assertions()
    with repository._sessions() as session:
        assertion_history = (
            session.query(GraphRevisionRow)
            .filter_by(record_type="assertion", record_id=str(assertion.id))
            .all()
        )
        assert [revision.record["review_state"] for revision in assertion_history] == [
            "proposed",
            "accepted",
        ]


def test_evidence_span_write_rejects_nonmatching_offsets(repository):
    now = datetime.now(UTC)
    source = repository.add_source(
        Source(source_key="fixture:bad-span", source_type="test", base_url="https://example.org")
    )
    evidence = repository.add_evidence(
        Evidence(
            source_id=source.id,
            source_url="https://example.org/post",
            source_type="test",
            retrieved_at=now,
            original_reference="body",
            raw_text="canonical text",
            content_hash=sha256(b"canonical text").hexdigest(),
        )
    )
    from memesis.domain.schemas import Document, DocumentVersion

    document = repository.add_document(
        Document(source_id=source.id, external_id="1", canonical_url="https://example.org/post")
    )
    version = repository.add_document_version(
        DocumentVersion(
            document_id=document.id,
            content_hash=sha256(b"canonical text").hexdigest(),
            raw_payload="canonical text",
            retrieved_at=now,
        )
    )
    provenance = Provenance(
        source_url=evidence.source_url,
        source_type=evidence.source_type,
        retrieved_at=now,
        original_reference="body",
        evidence_ids=(evidence.id,),
        confidence=1,
        extraction_method=ExtractionMethod.DETERMINISTIC,
    )
    normalized = repository.add_normalized_document(
        NormalizedDocument(
            document_version_id=version.id,
            normalizer_version="1",
            normalized_text="canonical text",
            content_hash=sha256(b"canonical text").hexdigest(),
            provenance=provenance,
        )
    )
    bad_span = EvidenceSpan(
        normalized_document_id=normalized.id,
        start_offset=0,
        end_offset=9,
        exact_text="different",
        content_hash=sha256(b"different").hexdigest(),
        provenance=provenance,
    )
    with pytest.raises(ValueError, match="does not match exact normalized text offsets"):
        repository.add_evidence_span(bad_span)
