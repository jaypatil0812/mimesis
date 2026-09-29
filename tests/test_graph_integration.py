"""End-to-end durable CRUD, subgraph retrieval, and provenance round trip."""

from datetime import UTC, datetime
from uuid import uuid4

from memesis.db.models import GraphRevisionRow
from memesis.domain.schemas import (
    Belief,
    Content,
    EdgeType,
    Evidence,
    ExtractionMethod,
    GraphEdge,
    Person,
    Provenance,
    Source,
)


def test_person_content_belief_round_trip(repository):
    now = datetime.now(UTC)
    source = repository.add_source(
        Source(
            source_key="fixture:roundtrip",
            source_type="test_fixture",
            base_url="https://example.org/post/1",
        )
    )
    evidence = repository.add_evidence(
        Evidence(
            source_id=source.id,
            source_url="https://example.org/post/1",
            source_type=source.source_type,
            retrieved_at=now,
            published_at=now,
            original_reference="paragraph-1",
            raw_text="Mira Example states that small models are useful for local inference.",
            normalized_text="Mira Example states that small models are useful for local inference.",
            content_hash="a" * 64,
        )
    )

    ids = [uuid4(), uuid4(), uuid4()]
    person_id, content_id, belief_id = ids

    def make_provenance(entity_ids):
        return Provenance(
            source_url=evidence.source_url,
            source_type=evidence.source_type,
            retrieved_at=evidence.retrieved_at,
            published_at=evidence.published_at,
            original_reference=evidence.original_reference,
            evidence_ids=(evidence.id,),
            confidence=0.97,
            extraction_method=ExtractionMethod.SOURCE_EXPLICIT,
            entity_ids=tuple(entity_ids),
        )

    person = repository.add_node(
        Person(id=person_id, name="Mira Example", provenance=make_provenance([person_id]))
    )
    repository.add_node(
        Content(
            id=content_id, name="Local inference post", provenance=make_provenance([content_id])
        )
    )
    repository.add_node(
        Belief(
            id=belief_id,
            name="Small models are useful for local inference",
            provenance=make_provenance([belief_id]),
        )
    )
    published = repository.add_edge(
        GraphEdge(
            edge_type=EdgeType.PUBLISHED,
            from_node_id=person_id,
            to_node_id=content_id,
            recorded_at=now,
            provenance=make_provenance([person_id, content_id]),
        )
    )
    expresses = repository.add_edge(
        GraphEdge(
            edge_type=EdgeType.EXPRESSES,
            from_node_id=content_id,
            to_node_id=belief_id,
            recorded_at=now,
            provenance=make_provenance([content_id, belief_id]),
        )
    )

    repository.update_node(person.model_copy(update={"name": "Mira Chen"}))
    repository.update_edge(expresses.model_copy(update={"qualifiers": {"stance": "supports"}}))

    result = repository.retrieve_subgraph([person_id], max_hops=2)
    assert {node.id for node in result["nodes"]} == set(ids)
    assert {edge.id for edge in result["edges"]} == {published.id, expresses.id}
    assert len(result["evidence"]) == 1
    round_tripped_evidence = result["evidence"][0]
    assert round_tripped_evidence.source_url == evidence.source_url
    assert round_tripped_evidence.source_type == "test_fixture"
    assert round_tripped_evidence.retrieved_at.replace(tzinfo=UTC) == now
    assert round_tripped_evidence.published_at.replace(tzinfo=UTC) == now
    assert round_tripped_evidence.original_reference == "paragraph-1"
    assert round_tripped_evidence.raw_text == evidence.raw_text
    for edge in result["edges"]:
        assert edge.provenance.evidence_ids == (evidence.id,)
        assert edge.provenance.source_url == evidence.source_url
        assert edge.provenance.confidence == 0.97
        assert len(edge.provenance.entity_ids) == 2

    assert repository.get_node(person_id).name == "Mira Chen"
    assert repository.get_edge(published.id).edge_type == EdgeType.PUBLISHED
    assert repository.get_evidence(evidence.id).content_hash == "a" * 64
    assert repository.health()["status"] == "ok"
    with repository._sessions() as session:
        revisions = session.query(GraphRevisionRow).all()
        assert {revision.record_type for revision in revisions} == {"node", "edge"}
        old_person = next(
            revision.record for revision in revisions if revision.record_type == "node"
        )
        assert old_person["name"] == person.name


def test_graph_crud_delete_tombstones_incident_edges(repository):
    now = datetime.now(UTC)
    source = repository.add_source(
        Source(source_key="fixture:delete", source_type="test", base_url="https://example.org")
    )
    evidence = repository.add_evidence(
        Evidence(
            source_id=source.id,
            source_url="https://example.org/post",
            source_type="test",
            retrieved_at=now,
            original_reference="span",
            raw_text="The source text.",
            content_hash="b" * 64,
        )
    )
    a, b = uuid4(), uuid4()

    def prov(ids):
        return Provenance(
            source_url=evidence.source_url,
            source_type="test",
            retrieved_at=now,
            original_reference="span",
            evidence_ids=(evidence.id,),
            confidence=1,
            extraction_method=ExtractionMethod.ANALYST,
            entity_ids=tuple(ids),
        )

    repository.add_node(Person(id=a, name="A", provenance=prov([a])))
    repository.add_node(Content(id=b, name="B", provenance=prov([b])))
    edge = repository.add_edge(
        GraphEdge(
            edge_type=EdgeType.PUBLISHED,
            from_node_id=a,
            to_node_id=b,
            recorded_at=now,
            provenance=prov([a, b]),
        )
    )
    assert repository.delete_edge(edge.id)
    assert not repository.retrieve_subgraph([a], 1)["edges"]
    assert repository.delete_node(a)
    assert repository.get_node(a) is None
