"""Backfill perception observations across all ingested real evidence items.

Extracts developer pain, pricing sensitivity, latency friction, switching intent,
and praise targeting AI companies, models, runtimes, and markets.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from uuid import uuid4

from memesis.config import settings
from memesis.db.session import make_engine, make_session_factory
from memesis.domain.schemas import (
    EdgeType,
    GraphEdge,
    NodeType,
    PerceptionDimension,
    PerceptionObservation,
    PerceptionStance,
    Provenance,
)
from memesis.graph.sql_repository import SqlGraphRepository


def backfill():
    engine = make_engine(settings.database_url)
    session_factory = make_session_factory(engine)
    repo = SqlGraphRepository(session_factory)

    evidence_list = repo.list_evidence()
    print(f"Backfilling perception across {len(evidence_list)} evidence items...")

    # Collect known target entities (companies, products, markets)
    nodes = repo.list_nodes()
    targets = [
        n for n in nodes
        if n.node_type in (NodeType.COMPANY, NodeType.PRODUCT, NodeType.MARKET)
    ]
    print(f"Found {len(targets)} candidate target entities in graph.")

    # Also map persons for attribution
    persons_by_name = {
        n.name.lower(): n
        for n in nodes
        if n.node_type == NodeType.PERSON
    }

    perceptions_added = 0
    edges_added = 0

    for ev in evidence_list:
        text = ev.raw_text or ""
        if not text:
            continue

        sentences = [s.strip() for s in re.split(r"[.!?\n]+", text) if len(s.strip()) > 15]
        for sentence in sentences:
            s_lower = sentence.lower()
            dimension = None
            stance = None

            if any(w in s_lower for w in ["expensive", "bill", "price", "token price", "cost per token", "over budget", "costly", "cut costs", "save money", "cheaper"]):
                dimension = PerceptionDimension.PRICE_SENSITIVITY
                stance = (
                    PerceptionStance.NEGATIVE
                    if any(w in s_lower for w in ["expensive", "too high", "over budget", "insane", "costly"])
                    else PerceptionStance.POSITIVE
                )
            elif any(w in s_lower for w in ["latency", "slow", "ttft", "tokens/sec", "throughput", "timeout", "delay", "blazing fast", "fast", "speed up", "performance"]):
                dimension = PerceptionDimension.PERFORMANCE
                stance = (
                    PerceptionStance.POSITIVE
                    if any(w in s_lower for w in ["fast", "quick", "sub-100ms", "low latency", "high throughput", "speed up"])
                    else PerceptionStance.NEGATIVE
                )
            elif any(w in s_lower for w in ["pain", "broken", "frustrating", "bug", "crash", "outage", "unreliable", "oom", "memory leak", "headache", "difficult"]):
                dimension = PerceptionDimension.PAIN
                stance = PerceptionStance.NEGATIVE
            elif any(w in s_lower for w in ["switched from", "migrated from", "moved to", "replaced with", "leaving", "replacing", "switch to"]):
                dimension = PerceptionDimension.SWITCHING_INTENT
                stance = PerceptionStance.MIXED
            elif any(w in s_lower for w in ["wish", "need", "please add", "support for", "missing feature", "want"]):
                dimension = PerceptionDimension.FEATURE_REQUEST
                stance = PerceptionStance.NEUTRAL
            elif any(w in s_lower for w in ["easy to use", "difficult to setup", "setup was smooth", "dx is great", "developer experience", "simple to run"]):
                dimension = PerceptionDimension.USABILITY
                stance = (
                    PerceptionStance.POSITIVE
                    if any(w in s_lower for w in ["easy", "smooth", "great", "simple"])
                    else PerceptionStance.NEGATIVE
                )
            elif any(w in s_lower for w in ["love", "amazing", "huge fan", "best model", "great job", "impressed", "impressive", "state-of-the-art"]):
                dimension = PerceptionDimension.PRAISE
                stance = PerceptionStance.POSITIVE

            if dimension and stance:
                # Find matching target entity
                matched_target = None
                for t in targets:
                    if t.name.lower() in s_lower:
                        matched_target = t
                        break

                if matched_target:
                    # Match author / person
                    author_name = ev.metadata.get("author") or ev.metadata.get("by")
                    actor = None
                    if author_name and str(author_name).lower() in persons_by_name:
                        actor = persons_by_name[str(author_name).lower()]

                    from memesis.domain.schemas import ExtractionMethod

                    provenance = Provenance(
                        source_url=ev.source_url,
                        source_type=ev.source_type,
                        retrieved_at=ev.retrieved_at,
                        published_at=ev.published_at,
                        original_reference=ev.original_reference,
                        evidence_ids=(ev.id,),
                        confidence=0.88,
                        extraction_method=ExtractionMethod.DETERMINISTIC,
                        entity_ids=(matched_target.id,) + ((actor.id,) if actor else ()),
                    )

                    obs = PerceptionObservation(
                        subject_id=matched_target.id,
                        subject_type=matched_target.node_type,
                        dimension=dimension,
                        stance=stance,
                        statement=sentence[:400],
                        evidence_ids=(ev.id,),
                        confidence=0.88,
                        actor_id=actor.id if actor else None,
                        actor_community=ev.source_type,
                        observed_at=ev.published_at or ev.retrieved_at,
                        provenance=provenance,
                    )
                    repo.add_perception(obs)
                    perceptions_added += 1

                    if actor:
                        edge = GraphEdge(
                            edge_type=EdgeType.PERCEIVES,
                            from_node_id=actor.id,
                            to_node_id=matched_target.id,
                            qualifiers={
                                "dimension": dimension.value,
                                "stance": stance.value,
                                "statement": sentence[:200],
                            },
                            valid_from=ev.published_at,
                            recorded_at=datetime.now(UTC),
                            provenance=provenance,
                        )
                        repo.add_edge(edge)
                        edges_added += 1

    print(f"Backfill complete! Added {perceptions_added} perception observations and {edges_added} PERCEIVES edges.")


if __name__ == "__main__":
    backfill()
