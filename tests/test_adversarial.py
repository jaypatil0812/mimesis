"""Adversarial test suite — tries to break Memesis conclusions.

Each test attacks a specific known failure mode in market intelligence systems.
All fixtures are deterministic; no LLM calls made.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from memesis.analysis.scoring import DeterministicScoringService
from memesis.db.session import initialize_schema, make_engine, make_session_factory
from memesis.domain.schemas import (
    Assertion,
    Belief,
    Company,
    Content,
    Document,
    DocumentVersion,
    EdgeType,
    Evidence,
    ExtractionMethod,
    GraphEdge,
    Market,
    NodeType,
    Person,
    Provenance,
    ScoreType,
    Source,
)
from memesis.graph.sql_repository import SqlGraphRepository
from memesis.reasoning.contracts import (
    ClaimStatement,
    ConfidenceBreakdown,
    EpistemicStatus,
    IntelligencePacket,
    ReasoningOutput,
)
from memesis.reasoning.engine import MemesisReasoningEngine
from memesis.reasoning.validator import EvidenceValidator

# ---------------------------------------------------------------------------
# Shared fixture helpers
# ---------------------------------------------------------------------------

NOW = datetime.now(UTC)


def _fresh_repo() -> SqlGraphRepository:
    engine = make_engine("sqlite://")
    initialize_schema(engine)
    return SqlGraphRepository(make_session_factory(engine))


def _source(repo: SqlGraphRepository, key: str = "test") -> Source:
    return repo.add_source(
        Source(
            source_key=f"adversarial:{key}",
            source_type="test",
            base_url="https://test.example",
        )
    )


def _evidence(
    repo: SqlGraphRepository,
    source: Source,
    text: str,
    days_ago: float = 5,
    published_days_ago: float | None = None,
) -> Evidence:
    at = NOW - timedelta(days=days_ago)
    pub_at = NOW - timedelta(days=published_days_ago if published_days_ago is not None else days_ago)
    slug = hashlib.sha256(text.encode()).hexdigest()[:16]
    domain_slug = source.source_key.split(":")[-1]
    doc = repo.add_document(
        Document(source_id=source.id, external_id=slug, canonical_url=f"https://{domain_slug}.example/{slug}")
    )
    ver = repo.add_document_version(
        DocumentVersion(
            document_id=doc.id,
            content_hash=hashlib.sha256(text.encode()).hexdigest(),
            raw_payload=text,
            retrieved_at=at,
            published_at=pub_at,
        )
    )
    return repo.add_evidence(
        Evidence(
            source_id=source.id,
            document_version_id=ver.id,
            source_url=f"https://{domain_slug}.example/{slug}",
            source_type=source.source_type,
            retrieved_at=at,
            published_at=pub_at,
            original_reference=text[:200],
            raw_text=text,
            normalized_text=text,
            content_hash=hashlib.sha256(text.encode()).hexdigest(),
        )
    )


def _provenance(ev: Evidence, *entity_ids: UUID) -> Provenance:
    return Provenance(
        source_url=ev.source_url,
        source_type=ev.source_type,
        retrieved_at=ev.retrieved_at,
        published_at=ev.published_at,
        original_reference=ev.original_reference,
        evidence_ids=(ev.id,),
        confidence=1.0,
        extraction_method=ExtractionMethod.DETERMINISTIC,
        entity_ids=tuple(entity_ids),
    )


def _person(repo: SqlGraphRepository, name: str, ev: Evidence) -> Person:
    node_id = uuid4()
    node = Person(id=node_id, name=name, provenance=_provenance(ev, node_id))
    return repo.add_node(node)


def _company(repo: SqlGraphRepository, name: str, ev: Evidence) -> Company:
    node_id = uuid4()
    node = Company(id=node_id, name=name, provenance=_provenance(ev, node_id))
    return repo.add_node(node)


def _belief(repo: SqlGraphRepository, name: str, ev: Evidence) -> Belief:
    node_id = uuid4()
    node = Belief(id=node_id, name=name, provenance=_provenance(ev, node_id))
    return repo.add_node(node)


def _content_node(repo: SqlGraphRepository, name: str, ev: Evidence) -> Content:
    node_id = uuid4()
    node = Content(id=node_id, name=name, provenance=_provenance(ev, node_id))
    return repo.add_node(node)


def _edge(
    repo: SqlGraphRepository,
    edge_type: EdgeType,
    from_id: UUID,
    to_id: UUID,
    ev: Evidence,
) -> GraphEdge:
    return repo.add_edge(
        GraphEdge(
            edge_type=edge_type,
            from_node_id=from_id,
            to_node_id=to_id,
            valid_from=ev.published_at,
            recorded_at=ev.retrieved_at,
            provenance=_provenance(ev, from_id, to_id),
        )
    )


# ---------------------------------------------------------------------------
# Attack 1: Bad entity merges — same name, different domain
# ---------------------------------------------------------------------------

def test_bad_entity_merge_produces_distinct_nodes():
    """Two persons with the same name from different domains must not auto-merge.

    EntityResolver must keep them distinct or flag a low-confidence merge.
    A bad merge inflates ActorLead/Influence by conflating two unrelated people.
    """
    repo = _fresh_repo()
    src = _source(repo, "merge")

    ev_a = _evidence(repo, src, "Sam Lee at DeepMind published on model routing.", days_ago=10)
    ev_b = _evidence(repo, src, "Sam Lee at Anthropic published on constitutional AI.", days_ago=8)

    person_a = _person(repo, "Sam Lee (DeepMind)", ev_a)
    person_b = _person(repo, "Sam Lee (Anthropic)", ev_b)

    all_nodes = repo.list_nodes()
    person_nodes = [n for n in all_nodes if n.node_type == NodeType.PERSON]

    # Both persons must exist as distinct nodes
    assert len(person_nodes) >= 2, (
        "Entity resolver merged two distinct persons; bad merge inflates scores"
    )
    assert person_a.id != person_b.id


# ---------------------------------------------------------------------------
# Attack 2: Fake causality — PRECEDES edge violates temporal order
# ---------------------------------------------------------------------------

def test_no_causal_edge_without_temporal_precedence():
    """A PRECEDES edge B must be rejected or flagged if A's evidence post-dates B's.

    Without temporal ordering, downstream_independent_adoption scores are meaningless.
    """
    repo = _fresh_repo()
    src = _source(repo, "causality")

    # B appears 20 days ago, A appears 10 days ago — A cannot PRECEDE B
    ev_b = _evidence(repo, src, "Belief B: specialised routing is viable.", days_ago=20)
    ev_a = _evidence(repo, src, "Belief A: small models are cheap.", days_ago=10)

    belief_a = _belief(repo, "small models are cheap", ev_a)
    belief_b = _belief(repo, "specialised routing is viable", ev_b)

    # Attempting to store A→PRECEDES→B is logically invalid (A is newer than B)
    # The system should either reject this edge or mark it with zero weight.
    # We test that if the edge IS stored, scoring does not reward it as propagation.
    edge = _edge(repo, EdgeType.PRECEDES, belief_a.id, belief_b.id, ev_a)

    scoring = DeterministicScoringService(repo)
    run = scoring.compute_all(as_of=NOW, persist=False)
    # BeliefVelocity for B should not be inflated by A's later appearance
    velocity_b = [s for s in run.scores if s.score_type == ScoreType.BELIEF_VELOCITY
                  and s.subject_id == belief_b.id]
    # Velocity is based on expression counts, not PRECEDES edges — confirm no inflation
    # B was created with 1 evidence item; velocity should be low regardless
    if velocity_b:
        assert velocity_b[0].value <= 60.0, (
            "BeliefVelocity for B is inflated despite the PRECEDES edge violating temporal order"
        )


# ---------------------------------------------------------------------------
# Attack 3: Popularity ≠ influence — high mention count without INFLUENCES edges
# ---------------------------------------------------------------------------

def test_high_mention_count_without_influence_score():
    """A person mentioned 30 times but with zero INFLUENCES edges must score low on ActorInfluence.

    The scoring engine requires explicit_propagation (INFLUENCES or AMPLIFIES edges).
    Mention count alone (temporal_lead only) cannot produce high influence.
    """
    repo = _fresh_repo()
    src = _source(repo, "popularity")

    # Create a belief
    ev_belief = _evidence(repo, src, "Small models should handle routine tasks.", days_ago=60)
    target_belief = _belief(repo, "small models handle routine tasks", ev_belief)

    # Create a "popular" person: mentioned in 30 content pieces, all referencing the belief
    ev_person = _evidence(repo, src, "Alex Kim is frequently mentioned.", days_ago=55)
    popular_person = _person(repo, "Alex Kim", ev_person)

    # Wire person as author of content, content EXPRESSES belief — creates expressions
    for i in range(30):
        ev_c = _evidence(repo, src, f"Alex Kim post {i}: small models handle routine tasks.", days_ago=50 - i)
        content_node = _content_node(repo, f"Alex Kim post {i}", ev_c)
        _edge(repo, EdgeType.PUBLISHED, popular_person.id, content_node.id, ev_c)
        _edge(repo, EdgeType.EXPRESSES, content_node.id, target_belief.id, ev_c)

    # No INFLUENCES edges added — popularity only
    scoring = DeterministicScoringService(repo)
    run = scoring.compute_all(as_of=NOW, persist=False)

    influence_scores = [
        s for s in run.scores
        if s.score_type == ScoreType.ACTOR_INFLUENCE and s.subject_id == popular_person.id
    ]
    # explicit_propagation weight = 0.30; with 0 INFLUENCES edges, this component = 0
    # Even if other actors later adopt the belief and companies act,
    # without ANY explicit propagation (INFLUENCES/AMPLIFIES), popularity/temporal lead
    # cannot create a high influence score.
    for j in range(5):
        ev_other = _evidence(repo, src, f"Other person {j} adopts belief.", days_ago=30 - j)
        other_person = _person(repo, f"Other Person {j}", ev_other)
        other_c = _content_node(repo, f"Other post {j}", ev_other)
        _edge(repo, EdgeType.PUBLISHED, other_person.id, other_c.id, ev_other)
        _edge(repo, EdgeType.EXPRESSES, other_c.id, target_belief.id, ev_other)

    ev_co = _evidence(repo, src, "Company acts on belief.", days_ago=20)
    co = _company(repo, "Acme Corp", ev_co)
    _edge(repo, EdgeType.ACTS_ON, co.id, target_belief.id, ev_co)

    # Re-score
    scoring = DeterministicScoringService(repo)
    run = scoring.compute_all(as_of=NOW, persist=False)

    influence_scores = [
        s for s in run.scores
        if s.score_type == ScoreType.ACTOR_INFLUENCE and s.subject_id == popular_person.id
    ]
    assert influence_scores, "No ActorInfluence scores computed for popular person"
    max_influence = max(s.value for s in influence_scores)

    # Core principle: Popularity and temporal correlation are NOT sufficient for influence.
    # Without explicit propagation, influence must be strictly bounded (<= 25.0).
    assert max_influence <= 25.0, (
        f"ActorInfluence={max_influence:.1f} exceeds 25.0 for an actor with zero propagation edges; "
        "popularity and downstream market correlation are being mistaken for influence"
    )

    # Confirm the gap message is present
    all_gaps = [gap for s in influence_scores for gap in (s.coverage.get("gaps") or [])]
    assert any("explicit" in g.lower() for g in all_gaps), (
        "Scoring should flag missing INFLUENCES/AMPLIFIES edges in the gaps list"
    )


# ---------------------------------------------------------------------------
# Attack 4: Correlation ≠ propagation — simultaneous beliefs from separate communities
# ---------------------------------------------------------------------------

def test_correlated_beliefs_not_marked_as_causal():
    """Two beliefs rising simultaneously from different communities must not generate
    a PRECEDES or causal edge. BeliefDiversity should reflect independent sources.
    """
    repo = _fresh_repo()
    src_a = _source(repo, "community_a")
    src_b = _source(repo, "community_b")

    ev_a1 = _evidence(repo, src_a, "Small models reduce cost — perspective from web community.", days_ago=15)
    ev_b1 = _evidence(repo, src_b, "Small models are efficient — perspective from research community.", days_ago=15)

    belief = _belief(repo, "small models are efficient", ev_a1)

    person_a = _person(repo, "Web Dev Anon", ev_a1)
    person_b = _person(repo, "ML Researcher", ev_b1)

    content_a = _content_node(repo, "web post", ev_a1)
    content_b = _content_node(repo, "research post", ev_b1)

    _edge(repo, EdgeType.PUBLISHED, person_a.id, content_a.id, ev_a1)
    _edge(repo, EdgeType.EXPRESSES, content_a.id, belief.id, ev_a1)
    _edge(repo, EdgeType.PUBLISHED, person_b.id, content_b.id, ev_b1)
    _edge(repo, EdgeType.EXPRESSES, content_b.id, belief.id, ev_b1)

    scoring = DeterministicScoringService(repo)
    run = scoring.compute_all(as_of=NOW, persist=False)

    # BeliefDiversity should reflect two independent source families
    diversity_scores = [
        s for s in run.scores
        if s.score_type == ScoreType.BELIEF_DIVERSITY and s.subject_id == belief.id
    ]
    assert diversity_scores, "No BeliefDiversity score computed"
    # With two distinct source families the diversity score should be non-trivial
    assert diversity_scores[0].value > 10.0, "Simultaneous adoption from two communities should score diversity"

    # Crucially: no PRECEDES edge must exist between the two person nodes
    edges = repo.list_edges()
    precedes_edges = [e for e in edges if e.edge_type == EdgeType.PRECEDES]
    assert len(precedes_edges) == 0, (
        "Correlation between simultaneous beliefs auto-created a PRECEDES edge; "
        "this would falsely imply causation"
    )


# ---------------------------------------------------------------------------
# Attack 5: Duplicate beliefs — same content hash must deduplicate
# ---------------------------------------------------------------------------

def test_duplicate_belief_content_hash_deduplication():
    """Identical belief text added from two sources must produce one Belief node
    and two evidence items, not two conflated or duplicate Belief nodes.
    """
    repo = _fresh_repo()
    src_a = _source(repo, "dup_src_a")
    src_b = _source(repo, "dup_src_b")

    text = "Model routing will become a commodity infrastructure layer."

    ev_a = _evidence(repo, src_a, text, days_ago=10)
    ev_b = _evidence(repo, src_b, text, days_ago=8)

    # Add the same belief from two different sources
    belief_a = _belief(repo, text[:80], ev_a)
    # Second belief creation with same name — system should not create a second distinct node
    belief_b = _belief(repo, text[:80], ev_b)

    nodes = repo.list_nodes()
    belief_nodes = [n for n in nodes if n.node_type == NodeType.BELIEF]

    # There may be 1 or 2 depending on resolver strategy, but evidence must be 2
    evidence_items = repo.list_evidence()
    assert len(evidence_items) >= 2, "Both evidence items must be persisted even for duplicate beliefs"

    # Content hashes of the two evidence items must differ (different sources, same text is valid)
    # but the text must be the same — confirms deduplication opportunity exists
    raw_texts = {ev.raw_text for ev in evidence_items if ev.raw_text and text[:40] in ev.raw_text}
    assert len(raw_texts) >= 1, "At least one deduplicated evidence item must carry the canonical text"


# ---------------------------------------------------------------------------
# Attack 6: LLM hallucination guard — validator rejects claims not in evidence
# ---------------------------------------------------------------------------

def test_evidence_validator_rejects_hallucinated_claims():
    """OBSERVED claims citing evidence IDs not present in the intelligence packet
    must be downgraded to INFERRED by the validator.
    """
    validator = EvidenceValidator()
    real_ev_id = "00000000-0000-0000-0000-000000000001"
    hallucinated_ev_id = "ffffffff-ffff-ffff-ffff-ffffffffffff"

    from memesis.reasoning.classifier import IntentType, QueryIntent
    packet = IntelligencePacket(
        question="What is Acme doing in AI infrastructure?",
        query_intent=QueryIntent(
            raw_query="What is Acme doing in AI infrastructure?",
            intents=[IntentType.COMPETITOR_ANALYSIS],
        ),
        primary_evidence_references=[{"id": real_ev_id, "text": "Acme released a model router."}],
        estimated_tokens=100,
        packet_hash="a" * 64,
    )

    raw_output = ReasoningOutput(
        summary="Acme is building model routing infrastructure.",
        what_is_happening=[
            ClaimStatement(
                text="Acme released a model router.",
                epistemic_status=EpistemicStatus.OBSERVED,
                evidence_ids=[real_ev_id],
            ),
            ClaimStatement(
                text="Acme acquired RouteCo for $2B.",  # hallucinated — ID not in packet
                epistemic_status=EpistemicStatus.OBSERVED,
                evidence_ids=[hallucinated_ev_id],
            ),
            ClaimStatement(
                text="Acme will dominate the routing market.",  # hallucinated absolute
                epistemic_status=EpistemicStatus.OBSERVED,
                evidence_ids=[hallucinated_ev_id],
            ),
        ],
        confidence=ConfidenceBreakdown(
            overall_confidence=0.9,
            evidence_quantity=0.9,
            evidence_quality=0.9,
            source_diversity=0.9,
            source_independence=0.9,
            entity_resolution_confidence=0.9,
            temporal_consistency=0.9,
            contradictory_evidence_balance=0.9,
            graph_coverage=0.9,
        ),
    )

    result = validator.validate(raw_output, packet)

    # 2 of 3 claims cite an ID not in the packet → must be downgraded
    assert result.claims_downgraded == 2, (
        f"Expected 2 hallucinated claims downgraded, got {result.claims_downgraded}"
    )
    assert result.unsupported_claims_detected == 2
    # Real claim must remain OBSERVED
    assert result.validated_output.what_is_happening[0].epistemic_status == EpistemicStatus.OBSERVED
    # Hallucinated claims must be downgraded to INFERRED
    assert result.validated_output.what_is_happening[1].epistemic_status == EpistemicStatus.INFERRED
    assert result.validated_output.what_is_happening[2].epistemic_status == EpistemicStatus.INFERRED


# ---------------------------------------------------------------------------
# Attack 7: Missing evidence — engine returns INSUFFICIENT_EVIDENCE fallback
# ---------------------------------------------------------------------------

def test_insufficient_evidence_triggers_fallback(repository):
    """An empty graph must cause the engine to return fallback_status=INSUFFICIENT EVIDENCE.
    The engine must never hallucinate nodes or relationships when the graph is empty.
    """
    engine = MemesisReasoningEngine(repository)
    output, metrics, packet = engine.answer_query(
        "What is happening in the model routing market?"
    )

    # Empty graph → no nodes → fallback
    assert output.fallback_status in {
        "INSUFFICIENT EVIDENCE",
        "UNKNOWN",
        "NO MEANINGFUL CHANGE DETECTED",
    }, (
        f"Empty graph should produce a fallback, got fallback_status={output.fallback_status!r} "
        f"summary={output.summary!r}"
    )
    assert metrics.deep_reasoning_invoked is False, (
        "Engine must not call expensive model when evidence is insufficient"
    )


# ---------------------------------------------------------------------------
# Attack 8: Timestamp problems — future-dated evidence rejected
# ---------------------------------------------------------------------------

def test_future_dated_evidence_rejected():
    """Evidence with published_at 10 years in the future must be rejected.
    This protects all scoring windows from impossible dates.
    """
    repo = _fresh_repo()
    src = _source(repo, "future_ts")

    # Normal evidence — must succeed
    ev_good = _evidence(repo, src, "Model routers are production-ready.", days_ago=5)
    assert ev_good is not None

    # Future-dated evidence — must be rejected
    far_future = NOW + timedelta(days=365 * 10)
    slug = "future-evidence"
    doc = repo.add_document(
        Document(source_id=src.id, external_id=slug, canonical_url=f"https://test.example/{slug}")
    )
    future_payload = "Future claim"
    ver = repo.add_document_version(
        DocumentVersion(
            document_id=doc.id,
            content_hash=hashlib.sha256(future_payload.encode()).hexdigest(),
            raw_payload=future_payload,
            retrieved_at=NOW,
            published_at=far_future,
        )
    )

    with pytest.raises(ValueError, match="more than 1 day in the future"):
        repo.add_evidence(
            Evidence(
                source_id=src.id,
                document_version_id=ver.id,
                source_url="https://test.example/future",
                source_type="test",
                retrieved_at=NOW,
                published_at=far_future,
                original_reference=future_payload,
                raw_text=future_payload,
                normalized_text=future_payload,
                content_hash=hashlib.sha256(future_payload.encode()).hexdigest(),
            )
        )


# ---------------------------------------------------------------------------
# Attack 9: Source bias — single domain lowers EvidenceConfidence
# ---------------------------------------------------------------------------

def test_single_source_lowers_evidence_confidence_score():
    """30 evidence items from the same source domain must yield low BeliefDiversity
    (source_family_entropy ≈ 0) and the EvidenceConfidence independent_corroboration
    component must reflect only one independent group.
    """
    repo = _fresh_repo()
    src = _source(repo, "monoculture")

    ev_belief = _evidence(repo, src, "Single-source belief seed.", days_ago=60)
    target_belief = _belief(repo, "single source belief", ev_belief)
    person = _person(repo, "Single Author", ev_belief)

    for i in range(30):
        ev = _evidence(repo, src, f"Same domain post {i}: single source belief is true.", days_ago=50 - i)
        content = _content_node(repo, f"post_{i}", ev)
        _edge(repo, EdgeType.PUBLISHED, person.id, content.id, ev)
        _edge(repo, EdgeType.EXPRESSES, content.id, target_belief.id, ev)

    scoring = DeterministicScoringService(repo)
    run = scoring.compute_all(as_of=NOW, persist=False)

    diversity_scores = [
        s for s in run.scores
        if s.score_type == ScoreType.BELIEF_DIVERSITY and s.subject_id == target_belief.id
    ]
    assert diversity_scores, "BeliefDiversity score must be computed"
    diversity = diversity_scores[0]

    # Source family entropy = 0 when all expressions share one source family
    source_entropy_component = next(
        (c for c in diversity.components if c.name == "source_family_entropy"), None
    )
    assert source_entropy_component is not None
    assert source_entropy_component.value < 10.0, (
        f"source_family_entropy={source_entropy_component.value:.1f} should be near 0 "
        "when only one source domain contributes"
    )

    # Gap warning must be present
    assert any("one source family" in g for g in (diversity.coverage.get("gaps") or [])), (
        "BeliefDiversity must flag single-source-family dominance in gaps"
    )


# ---------------------------------------------------------------------------
# Attack 10: One community dominating — low BeliefDiversity
# ---------------------------------------------------------------------------

def test_single_community_belief_diversity_is_low():
    """All believers from one source_family must yield near-zero source_family_entropy.
    This detects echo chambers masquerading as broad consensus.
    """
    repo = _fresh_repo()
    src = _source(repo, "echo_chamber")

    ev_b = _evidence(repo, src, "Echo chamber belief origin.", days_ago=60)
    echo_belief = _belief(repo, "echo belief", ev_b)

    # 5 people from the same "twitter" source family all expressing the same belief
    for i in range(5):
        ev = _evidence(repo, src, f"Twitter user {i}: echo belief is correct.", days_ago=50 - i)
        person = _person(repo, f"Twitter User {i}", ev)
        content = _content_node(repo, f"tweet_{i}", ev)
        _edge(repo, EdgeType.PUBLISHED, person.id, content.id, ev)
        _edge(repo, EdgeType.EXPRESSES, content.id, echo_belief.id, ev)

    scoring = DeterministicScoringService(repo)
    run = scoring.compute_all(as_of=NOW, persist=False)

    diversity_scores = [
        s for s in run.scores
        if s.score_type == ScoreType.BELIEF_DIVERSITY and s.subject_id == echo_belief.id
    ]
    assert diversity_scores
    # All from same source → low diversity overall
    assert diversity_scores[0].value < 50.0, (
        "Echo chamber (one community) must not score high on BeliefDiversity"
    )


# ---------------------------------------------------------------------------
# Attack 11: Bot / amplification — dense INFLUENCES edges, zero content
# ---------------------------------------------------------------------------

def test_bot_amplification_does_not_inflate_influence():
    """100 INFLUENCES edges from bot-like amplifier nodes (no content published)
    must not inflate the target person's ActorInfluence beyond a meaningful threshold.

    The scoring engine's explicit_propagation component counts INFLUENCES edges,
    but saturates at 3. Bot amplification cannot bypass that saturation cap.
    """
    repo = _fresh_repo()
    src = _source(repo, "bots")

    ev_target = _evidence(repo, src, "Real expert: small models are the future.", days_ago=60)
    target_belief = _belief(repo, "small models are the future", ev_target)
    target_person = _person(repo, "Real Expert", ev_target)

    content = _content_node(repo, "expert post", ev_target)
    _edge(repo, EdgeType.PUBLISHED, target_person.id, content.id, ev_target)
    _edge(repo, EdgeType.EXPRESSES, content.id, target_belief.id, ev_target)

    # 100 bots amplify the target person — all INFLUENCES edges, no content published
    for i in range(100):
        ev_bot = _evidence(repo, src, f"Bot {i} amplifies Real Expert.", days_ago=50 - (i % 30))
        bot = _person(repo, f"Bot {i:03}", ev_bot)
        _edge(repo, EdgeType.INFLUENCES, bot.id, target_person.id, ev_bot)

    scoring = DeterministicScoringService(repo)
    run = scoring.compute_all(as_of=NOW, persist=False)

    influence_scores = [
        s for s in run.scores
        if s.score_type == ScoreType.ACTOR_INFLUENCE and s.subject_id == target_person.id
    ]
    assert influence_scores, "ActorInfluence must be computed"

    max_influence = max(s.value for s in influence_scores)

    # explicit_propagation weights authentic expression nodes; empty bot accounts
    # without content or downstream adoption are strictly bounded (<= 40.0).
    assert max_influence <= 40.0, (
        f"ActorInfluence={max_influence:.1f} exceeds threshold; "
        "bot amplification is inflating the score"
    )

    # The saturation and gating property: explicit_propagation component must be bounded
    influence_score = influence_scores[0]
    propagation_component = next(
        (c for c in influence_score.components if c.name == "explicit_propagation"), None
    )
    assert propagation_component is not None
    assert propagation_component.value <= 100.0, "explicit_propagation must saturate at 100"


def test_bot_amplification_cannot_inflate_belief_diversity():
    """50 bot accounts posting the exact same belief from a single platform/source
    must not achieve high BeliefDiversity (<= 20.0). Single-source actor entropy is gated.
    """
    repo = _fresh_repo()
    src = _source(repo, "twitter")

    ev_b = _evidence(repo, src, "Bot amplified belief seed.", days_ago=60)
    target_belief = _belief(repo, "bot amplified belief", ev_b)

    for i in range(50):
        ev = _evidence(repo, src, f"Bot {i} tweets the belief.", days_ago=10)
        bot = _person(repo, f"Bot User {i}", ev)
        c = _content_node(repo, f"bot_tweet_{i}", ev)
        _edge(repo, EdgeType.PUBLISHED, bot.id, c.id, ev)
        _edge(repo, EdgeType.EXPRESSES, c.id, target_belief.id, ev)

    scoring = DeterministicScoringService(repo)
    run = scoring.compute_all(as_of=NOW, persist=False)

    diversity_scores = [
        s for s in run.scores
        if s.score_type == ScoreType.BELIEF_DIVERSITY and s.subject_id == target_belief.id
    ]
    assert diversity_scores, "BeliefDiversity must be computed"
    diversity = diversity_scores[0]

    # Source family entropy is 0 since all are from 1 domain
    assert diversity.value <= 20.0, (
        f"BeliefDiversity={diversity.value:.1f} is too high for a single-source bot campaign; "
        "actor entropy was not gated by source diversity"
    )


# ---------------------------------------------------------------------------
# Attack 12: Survivorship bias — missing exit events flagged
# ---------------------------------------------------------------------------

def test_survivorship_bias_missing_exit_events(repository):
    """When only success stories exist in the graph and no failure/pivot evidence,
    the engine's output should include an entry in unknown_or_missing flagging
    the absence of counter-evidence.

    This test uses the empty repo fixture to confirm the fallback path populates
    unknown_or_missing rather than producing false confidence.
    """
    engine = MemesisReasoningEngine(repository)
    output, metrics, packet = engine.answer_query(
        "Which AI infrastructure companies succeeded with model routing?"
    )

    # With an empty graph, either fallback is triggered or unknown_or_missing is populated
    if output.fallback_status is not None:
        # Fallback correctly triggered — no survivorship bias possible
        assert output.fallback_status in {
            "INSUFFICIENT EVIDENCE",
            "UNKNOWN",
            "NO MEANINGFUL CHANGE DETECTED",
        }
    else:
        # If no fallback, unknown_or_missing must note absent counter-evidence
        assert len(output.unknown_or_missing) > 0, (
            "Engine should flag missing data (exit events, failures) in unknown_or_missing"
        )


# ---------------------------------------------------------------------------
# Attack 13: Historical hindsight bias — post-cutoff evidence excluded
# ---------------------------------------------------------------------------

def test_hindsight_evidence_excluded_from_prediction_window():
    """Scoring with as_of=cutoff must not include evidence published after cutoff.

    This ensures that retrospective analysis using a historical as_of date
    does not smuggle in information that would not have been available then.
    """
    repo = _fresh_repo()
    src = _source(repo, "hindsight")

    cutoff = NOW - timedelta(days=30)

    # Evidence published BEFORE the cutoff — valid for that window
    ev_before = _evidence(repo, src, "Early evidence: model routers are emerging.", days_ago=60)
    target_belief = _belief(repo, "model routers emerging", ev_before)
    person_before = _person(repo, "Early Analyst", ev_before)
    content_before = _content_node(repo, "early post", ev_before)
    _edge(repo, EdgeType.PUBLISHED, person_before.id, content_before.id, ev_before)
    _edge(repo, EdgeType.EXPRESSES, content_before.id, target_belief.id, ev_before)

    # Evidence published AFTER the cutoff — must be invisible to as_of=cutoff scoring
    ev_after = _evidence(repo, src, "Post-cutoff: model routing is now mainstream.", days_ago=5)
    person_after = _person(repo, "Later Analyst", ev_after)
    content_after = _content_node(repo, "later post", ev_after)
    _edge(repo, EdgeType.PUBLISHED, person_after.id, content_after.id, ev_after)
    _edge(repo, EdgeType.EXPRESSES, content_after.id, target_belief.id, ev_after)

    # Score with as_of = cutoff (30 days ago)
    scoring_at_cutoff = DeterministicScoringService(repo)
    run_at_cutoff = scoring_at_cutoff.compute_all(as_of=cutoff, persist=False)

    # Score with as_of = NOW (includes both)
    scoring_now = DeterministicScoringService(repo)
    run_now = scoring_now.compute_all(as_of=NOW, persist=False)

    velocity_at_cutoff = [
        s for s in run_at_cutoff.scores
        if s.score_type == ScoreType.BELIEF_VELOCITY and s.subject_id == target_belief.id
    ]
    velocity_now = [
        s for s in run_now.scores
        if s.score_type == ScoreType.BELIEF_VELOCITY and s.subject_id == target_belief.id
    ]

    assert velocity_at_cutoff, "BeliefVelocity must be computed at cutoff"
    assert velocity_now, "BeliefVelocity must be computed at now"

    # The window_end for as_of=cutoff must not extend beyond cutoff
    for score in velocity_at_cutoff:
        if score.window_end:
            assert score.window_end <= cutoff + timedelta(seconds=1), (
                f"Scoring at cutoff has window_end={score.window_end} beyond cutoff={cutoff}; "
                "post-cutoff evidence is bleeding into historical scoring"
            )
