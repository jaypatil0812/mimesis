from datetime import UTC, datetime
from hashlib import sha256
from uuid import uuid4

import pytest
from pydantic import ValidationError

from memesis.domain.schemas import (
    Belief,
    EdgeType,
    EvidenceSpan,
    ExtractionMethod,
    NodeType,
    Person,
    Provenance,
    validate_edge_endpoints,
)


def provenance(entity_id):
    return Provenance(
        source_url="https://example.org/post",
        source_type="test",
        retrieved_at=datetime.now(UTC),
        original_reference="span-1",
        evidence_ids=(uuid4(),),
        confidence=0.9,
        extraction_method=ExtractionMethod.ANALYST,
        entity_ids=(entity_id,),
    )


def test_all_initial_node_schemas_accept_required_provenance():
    for node_type, schema in (
        (NodeType.PERSON, Person),
        (NodeType.BELIEF, Belief),
    ):
        node_id = uuid4()
        node = schema(id=node_id, name=f"{node_type.value} sample", provenance=provenance(node_id))
        assert node.node_type == node_type
        assert node.provenance.entity_ids == (node_id,)


def test_derived_node_requires_its_entity_id_in_provenance():
    with pytest.raises(ValidationError, match="must include the node id"):
        Person(name="Ada Example", provenance=provenance(uuid4()))


def test_extraction_requires_a_model_identifier():
    with pytest.raises(ValidationError, match="requires extraction_model"):
        Provenance(
            source_url="https://example.org/post",
            source_type="test",
            retrieved_at=datetime.now(UTC),
            original_reference="span-1",
            evidence_ids=(uuid4(),),
            confidence=0.9,
            extraction_method=ExtractionMethod.EXTRACTED,
        )


def test_ontology_rejects_invalid_edge_endpoints():
    with pytest.raises(ValueError, match="cannot connect"):
        validate_edge_endpoints(EdgeType.EXPRESSES, NodeType.PERSON, NodeType.BELIEF)


def test_evidence_span_preserves_exact_text_coordinates():
    start = 12
    text = "specialized models"
    span = EvidenceSpan(
        normalized_document_id=uuid4(),
        start_offset=start,
        end_offset=start + len(text),
        exact_text=text,
        content_hash=sha256(text.encode()).hexdigest(),
        provenance=Provenance(
            source_url="https://example.org/post",
            source_type="test",
            retrieved_at=datetime.now(UTC),
            original_reference="paragraph 2",
            evidence_ids=(uuid4(),),
            confidence=1,
            extraction_method=ExtractionMethod.DETERMINISTIC,
        ),
    )
    assert span.end_offset - span.start_offset == len(span.exact_text)
