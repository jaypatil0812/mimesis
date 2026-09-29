"""V0 scoring is historical, deterministic, and fully explainable."""

import hashlib
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from memesis.analysis.scoring import DeterministicScoringService
from memesis.domain.schemas import (
    Belief,
    Company,
    Content,
    EdgeType,
    Event,
    Evidence,
    ExtractionMethod,
    GraphEdge,
    Person,
    Provenance,
    ScoreType,
    Source,
)


def _build_score_graph(repository):
    base = datetime(2026, 1, 1, tzinfo=UTC)
    sources = {}

    def evidence(label, day, confidence=0.01):
        source_label = label.split("-")[0]
        source = sources.get(source_label)
        if source is None:
            source = repository.add_source(
                Source(
                    source_key=f"score:{source_label}",
                    source_type=source_label,
                    base_url=f"https://{source_label}.example",
                )
            )
            sources[source_label] = source
        text = f"{label} at day {day}"
        at = base + timedelta(days=day)
        return repository.add_evidence(
            Evidence(
                source_id=source.id,
                source_url=f"https://{source_label}.example/{label}",
                source_type=source_label,
                retrieved_at=at,
                published_at=at,
                original_reference=label,
                raw_text=text,
                normalized_text=text,
                content_hash=hashlib.sha256(text.encode()).hexdigest(),
                metadata={"declared_confidence_for_test": confidence},
            )
        )

    node_evidence = evidence("nodes-all", 0)

    def prov(ev, ids, confidence=0.01):
        return Provenance(
            source_url=ev.source_url,
            source_type=ev.source_type,
            retrieved_at=ev.retrieved_at,
            published_at=ev.published_at,
            original_reference=ev.original_reference,
            evidence_ids=(ev.id,),
            confidence=confidence,
            extraction_method=ExtractionMethod.DETERMINISTIC,
            entity_ids=tuple(ids),
        )

    def node(schema, name, **attributes):
        node_id = uuid4()
        return repository.add_node(
            schema(
                id=node_id,
                name=name,
                attributes=attributes,
                provenance=prov(node_evidence, [node_id]),
            )
        )

    belief = node(Belief, "Specialized models will replace frontier models in many workloads")
    actor_a = node(Person, "Actor A")
    actor_b = node(Person, "Actor B")
    actor_c = node(Person, "Actor C")
    actor_future = node(Person, "Future Actor")
    company_a = node(Company, "Company A")
    company_b = node(Company, "Company B")
    company_c = node(Company, "Company C")
    company_future = node(Company, "Future Company")
    event = node(Event, "Commercial deployment", subtype="deployment")

    def edge(edge_type, source, target, label, day, *, stance=None):
        ev = evidence(label, day)
        ids = [source.id, target.id]
        return repository.add_edge(
            GraphEdge(
                edge_type=edge_type,
                from_node_id=source.id,
                to_node_id=target.id,
                qualifiers={"stance": stance} if stance else {},
                valid_from=base + timedelta(days=day),
                recorded_at=base + timedelta(days=day),
                provenance=prov(ev, ids),
            )
        )

    edge(EdgeType.WORKS_AT, actor_a, company_a, "org-a", 0)
    edge(EdgeType.WORKS_AT, actor_b, company_b, "org-b", 0)
    edge(EdgeType.WORKS_AT, actor_c, company_c, "org-c", 0)
    edge(EdgeType.WORKS_AT, actor_future, company_future, "org-future", 0)

    def expression(actor, label, day, stance="supports"):
        content = node(Content, f"{label} content")
        edge(EdgeType.PUBLISHED, actor, content, f"{label}-published", day)
        edge(EdgeType.EXPRESSES, content, belief, f"{label}-expresses", day, stance=stance)

    expression(actor_a, "alpha", 1)
    expression(actor_b, "beta", 10)
    expression(company_b, "beta-company", 12)
    expression(actor_c, "gamma", 20, stance="qualifies")
    expression(actor_future, "future", 45)
    edge(EdgeType.AMPLIFIES, actor_a, belief, "alpha-amplifies", 5)
    edge(EdgeType.ACTS_ON, company_b, belief, "beta-action", 25)
    edge(EdgeType.PARTICIPATED_IN, company_b, event, "beta-event", 28)
    return {
        "as_of": base + timedelta(days=30),
        "belief": belief,
        "actor_a": actor_a,
    }


def _score(run, score_type, subject_id):
    return next(
        score
        for score in run.scores
        if score.score_type == score_type and score.subject_id == subject_id
    )


def test_actor_scores_are_decomposable_and_ignore_future_evidence(repository):
    graph = _build_score_graph(repository)
    run = DeterministicScoringService(repository).compute_all(as_of=graph["as_of"], window_days=15)
    lead = _score(run, ScoreType.ACTOR_LEAD, graph["actor_a"].id)
    influence = _score(run, ScoreType.ACTOR_INFLUENCE, graph["actor_a"].id)

    assert lead.value == pytest.approx(50.0, abs=0.01)
    assert influence.value == pytest.approx(48.3333, abs=0.01)
    assert sum(component.contribution for component in lead.components) == pytest.approx(lead.value)
    assert all("Future" not in str(component.details) for component in lead.components)
    explicit = next(c for c in influence.components if c.name == "explicit_propagation")
    assert explicit.numerator == 1
    assert "popularity" not in influence.formula.lower()
    assert run.as_metrics()["llm_calls"] == 0


def test_belief_scores_measure_diversity_conversion_and_auditable_confidence(repository):
    graph = _build_score_graph(repository)
    run = DeterministicScoringService(repository).compute_all(as_of=graph["as_of"], window_days=15)
    diversity = _score(run, ScoreType.BELIEF_DIVERSITY, graph["belief"].id)
    conversion = _score(run, ScoreType.ACTION_CONVERSION, graph["belief"].id)
    confidence = _score(run, ScoreType.EVIDENCE_CONFIDENCE, graph["belief"].id)

    source_entropy = next(c for c in diversity.components if c.name == "source_family_entropy")
    actor_entropy = next(c for c in diversity.components if c.name == "independent_actor_entropy")
    assert source_entropy.value > 90
    assert actor_entropy.value > 90
    assert next(c for c in conversion.components if c.name == "conversion_rate").value == 100
    assert 60 < conversion.value < 70
    assert confidence.inputs["declared_confidence_values_used"] is False
    assert next(c for c in confidence.components if c.name == "exact_span_coverage").value == 0
    assert "stored model/assertion confidence is never an input" in confidence.formula


def test_score_persistence_is_idempotent_and_explanation_reconciles(repository):
    graph = _build_score_graph(repository)
    service = DeterministicScoringService(repository)
    first = service.compute_all(as_of=graph["as_of"], window_days=15)
    second = service.compute_all(as_of=graph["as_of"], window_days=15)

    assert first.persisted == len(first.scores)
    assert second.persisted == 0
    assert len(repository.list_scores()) == len(first.scores)
    stored_ids = {score.id for score in repository.list_scores()}
    assert {score.id for score in second.scores} == stored_ids
    stored = repository.list_scores(ScoreType.ACTOR_INFLUENCE.value, graph["actor_a"].id)[0]
    explanation = service.explain(stored.id)
    assert explanation["reconciliation"]["component_points"] == pytest.approx(stored.value)
    assert explanation["warning"].startswith("This is a deterministic graph statistic")


def test_empty_belief_scores_zero_with_visible_coverage_gaps(repository):
    now = datetime(2026, 1, 1, tzinfo=UTC)
    source = repository.add_source(
        Source(source_key="empty", source_type="test", base_url="https://empty.example")
    )
    ev = repository.add_evidence(
        Evidence(
            source_id=source.id,
            source_url="https://empty.example/belief",
            source_type="test",
            retrieved_at=now,
            original_reference="empty",
            raw_text="No supporting relations.",
            content_hash=hashlib.sha256(b"No supporting relations.").hexdigest(),
        )
    )
    belief_id = uuid4()
    repository.add_node(
        Belief(
            id=belief_id,
            name="Unsupported belief",
            provenance=Provenance(
                source_url=ev.source_url,
                source_type=ev.source_type,
                retrieved_at=now,
                original_reference=ev.original_reference,
                evidence_ids=(ev.id,),
                confidence=1,
                extraction_method=ExtractionMethod.ANALYST,
                entity_ids=(belief_id,),
            ),
        )
    )
    run = DeterministicScoringService(repository).compute_all(as_of=now)
    for score in run.scores:
        assert score.value == 0
        assert score.coverage["gaps"]
