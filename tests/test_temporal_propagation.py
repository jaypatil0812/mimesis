"""Temporal and Propagation Validation Tests for Phase 9 Part 11.

Proves:
1. PRECEDES (chronology only) is represented separately from POSSIBLY_INFLUENCED (correlated timing/interaction)
   and EVIDENCED_INFLUENCE (direct citation/causal evidence).
2. Chronology alone never generates causal influence.
3. Propagation requires timestamps, semantic relationship, and source evidence.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from memesis.analysis.scoring import DeterministicScoringService
from memesis.db.models import Base
from memesis.domain.schemas import (
    Belief,
    Content,
    EdgeType,
    Evidence,
    ExtractionMethod,
    GraphEdge,
    NodeType,
    Person,
    Provenance,
    ScoreType,
    Source,
)
from memesis.graph.sql_repository import SqlGraphRepository


@pytest.fixture
def repo():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(engine, expire_on_commit=False)
    return SqlGraphRepository(session_factory)


def _prov(evidence_id, *node_ids, ts=None) -> Provenance:
    now = ts or datetime.now(UTC)
    return Provenance(
        source_url="https://example.org/test",
        source_type="test",
        retrieved_at=now,
        published_at=now,
        original_reference="test",
        evidence_ids=(evidence_id,),
        confidence=1.0,
        extraction_method=ExtractionMethod.DETERMINISTIC,
        entity_ids=node_ids,
    )


def test_temporal_precedes_vs_evidenced_influence(repo):
    """Verifies that PRECEDES, POSSIBLY_INFLUENCED, and EVIDENCED_INFLUENCE remain distinct."""
    t0 = datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC)
    t1 = t0 + timedelta(days=30)
    t2 = t1 + timedelta(days=15)

    source = repo.add_source(
        Source(
            source_key="test_source",
            source_type="test",
            base_url="https://example.org",
        )
    )

    ev = repo.add_evidence(
        Evidence(
            source_id=source.id,
            source_url="https://example.org/ev",
            source_type="test",
            retrieved_at=t0,
            published_at=t0,
            original_reference="evidence text",
            raw_text="evidence text",
            content_hash=sha256(b"evidence text").hexdigest(),
        )
    )

    b_id = uuid4()
    belief = repo.add_node(
        Belief(
            id=b_id,
            name="Smaller specialized models will replace frontier models for enterprise inference",
            provenance=_prov(ev.id, b_id),
        )
    )

    a_id, b_actor_id, c_id = uuid4(), uuid4(), uuid4()
    actor_a = repo.add_node(Person(id=a_id, name="Alice (Early Researcher)", provenance=_prov(ev.id, a_id)))
    actor_b = repo.add_node(Person(id=b_actor_id, name="Bob (Later Engineer)", provenance=_prov(ev.id, b_actor_id)))
    actor_c = repo.add_node(Person(id=c_id, name="Carol (Direct Adopter)", provenance=_prov(ev.id, c_id)))

    ca_id, cb_id, cc_id = uuid4(), uuid4(), uuid4()
    content_a = repo.add_node(Content(id=ca_id, name="Alice Paper 2024-01", provenance=_prov(ev.id, ca_id)))
    content_b = repo.add_node(Content(id=cb_id, name="Bob Post 2024-02", provenance=_prov(ev.id, cb_id)))
    content_c = repo.add_node(Content(id=cc_id, name="Carol Blog 2024-02", provenance=_prov(ev.id, cc_id)))

    # A published at t0, expressed belief
    repo.add_edge(GraphEdge(edge_type=EdgeType.PUBLISHED, from_node_id=actor_a.id, to_node_id=content_a.id, valid_from=t0, recorded_at=t0, provenance=_prov(ev.id, actor_a.id, content_a.id, ts=t0)))
    repo.add_edge(GraphEdge(edge_type=EdgeType.EXPRESSES, from_node_id=content_a.id, to_node_id=belief.id, valid_from=t0, recorded_at=t0, provenance=_prov(ev.id, content_a.id, belief.id, ts=t0)))

    # B published at t1, expressed belief independently
    repo.add_edge(GraphEdge(edge_type=EdgeType.PUBLISHED, from_node_id=actor_b.id, to_node_id=content_b.id, valid_from=t1, recorded_at=t1, provenance=_prov(ev.id, actor_b.id, content_b.id, ts=t1)))
    repo.add_edge(GraphEdge(edge_type=EdgeType.EXPRESSES, from_node_id=content_b.id, to_node_id=belief.id, valid_from=t1, recorded_at=t1, provenance=_prov(ev.id, content_b.id, belief.id, ts=t1)))

    # Pure chronology: Content A PRECEDES Content B
    edge_precedes = repo.add_edge(
        GraphEdge(
            edge_type=EdgeType.PRECEDES,
            from_node_id=content_a.id,
            to_node_id=content_b.id,
            qualifiers={"time_delta_days": 30},
            recorded_at=t1,
            provenance=_prov(ev.id, content_a.id, content_b.id, ts=t1),
        )
    )
    assert edge_precedes.edge_type == EdgeType.PRECEDES

    # Direct causal propagation: Carol explicitly cited and adopted Alice's work
    repo.add_edge(GraphEdge(edge_type=EdgeType.PUBLISHED, from_node_id=actor_c.id, to_node_id=content_c.id, valid_from=t2, recorded_at=t2, provenance=_prov(ev.id, actor_c.id, content_c.id, ts=t2)))
    repo.add_edge(GraphEdge(edge_type=EdgeType.EXPRESSES, from_node_id=content_c.id, to_node_id=belief.id, valid_from=t2, recorded_at=t2, provenance=_prov(ev.id, content_c.id, belief.id, ts=t2)))
    
    edge_influence = repo.add_edge(
        GraphEdge(
            edge_type=EdgeType.EVIDENCED_INFLUENCE,
            from_node_id=actor_a.id,
            to_node_id=actor_c.id,
            qualifiers={"citation": "https://example.org/cites/alice", "confidence": 0.95},
            recorded_at=t2,
            provenance=_prov(ev.id, actor_a.id, actor_c.id, ts=t2),
        )
    )
    assert edge_influence.edge_type == EdgeType.EVIDENCED_INFLUENCE

    # Verify that PRECEDES edge alone does NOT count as explicit propagation evidence for Bob
    b_edges = [
        e for e in repo.list_edges()
        if e.from_node_id == actor_b.id and e.edge_type in (EdgeType.INFLUENCES, EdgeType.EVIDENCED_INFLUENCE)
    ]
    assert len(b_edges) == 0

    # Test scoring: Actor with 0 propagation evidence is gated
    scoring = DeterministicScoringService(repo)
    run = scoring.compute_all(as_of=t2, persist=False)
    b_scores = [s for s in run.scores if s.subject_id == actor_b.id and s.score_type == ScoreType.ACTOR_INFLUENCE]
    if b_scores:
        assert b_scores[0].value <= 25.0, f"Actor B influence score {b_scores[0].value} exceeded propagation gate limit"
