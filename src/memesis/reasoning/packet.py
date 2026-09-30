"""Builder for compact, provenance-backed IntelligencePacket objects."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from memesis.domain.schemas import EdgeType, NodeType, ScoreRecord
from memesis.extraction.meaning import source_family
from memesis.reasoning.classifier import QueryIntent
from memesis.reasoning.contracts import IntelligencePacket
from memesis.reasoning.historical_analogues import HistoricalAnalogue
from memesis.reasoning.market_motion import MarketMotion
from memesis.retrieval.context_builder import MinimumSufficientSubgraph


class IntelligencePacketBuilder:
    """Assembles a compact, bounded intelligence package for reasoning."""

    @staticmethod
    def build_packet(
        question: str,
        intent: QueryIntent,
        subgraph: MinimumSufficientSubgraph,
        market_motion: MarketMotion | None,
        analogues: list[HistoricalAnalogue],
        scores: list[ScoreRecord] | None = None,
        client_context: str | None = None,
    ) -> IntelligencePacket:
        scores = scores or []
        available_evidence_ids = {ev.id for ev in subgraph.evidence}
        incident_evidence_ids: dict[UUID, set[UUID]] = {}
        for edge in subgraph.edges:
            for node_id in (edge.from_node_id, edge.to_node_id):
                incident_evidence_ids.setdefault(node_id, set()).update(edge.provenance.evidence_ids)

        def citation_ids(record) -> list[str]:
            ids = set(record.provenance.evidence_ids) | incident_evidence_ids.get(record.id, set())
            return sorted(str(eid) for eid in ids if eid in available_evidence_ids)

        # 1. Key Beliefs
        key_beliefs: list[dict[str, Any]] = []
        for n in subgraph.nodes:
            if n.node_type == NodeType.BELIEF:
                key_beliefs.append({
                    "id": str(n.id),
                    "name": n.name,
                    "evidence_ids": citation_ids(n),
                })

        # 2. Key Actors
        key_actors: list[dict[str, Any]] = []
        actor_scores = {s.subject_id: s for s in scores if s.score_type.value in {"actor_lead", "actor_influence"}}
        for n in subgraph.nodes:
            if n.node_type == NodeType.PERSON:
                sub_score = actor_scores.get(n.id)
                key_actors.append({
                    "id": str(n.id),
                    "name": n.name,
                    "attributes": n.attributes,
                    "score_summary": f"Score: {sub_score.value:.1f}" if sub_score else "No actor score available",
                    "evidence_ids": citation_ids(n),
                })

        # 3. Key Companies
        key_companies: list[dict[str, Any]] = []
        for n in subgraph.nodes:
            if n.node_type == NodeType.COMPANY:
                key_companies.append({
                    "id": str(n.id),
                    "name": n.name,
                    "evidence_ids": citation_ids(n),
                })

        # 4. Competitor Actions / Events
        competitor_actions: list[dict[str, Any]] = []
        for n in subgraph.nodes:
            if n.node_type == NodeType.EVENT and any(
                e.edge_type == EdgeType.PARTICIPATED_IN and e.to_node_id == n.id
                and any(c.id == e.from_node_id and c.node_type == NodeType.COMPANY for c in subgraph.nodes)
                for e in subgraph.edges
            ):
                competitor_actions.append({
                    "id": str(n.id),
                    "name": n.name,
                    "subtype": n.attributes.get("subtype", "event"),
                    "attributes": n.attributes,
                    "qualification": "Company participation recorded; inspect event and source before interpreting as commercial execution.",
                    "evidence_ids": citation_ids(n),
                })

        # 5. Customer / Public Perception
        customer_perception: list[dict[str, Any]] = []
        contradictory_evidence: list[dict[str, Any]] = []
        evidence_by_id = {ev.id: ev for ev in subgraph.evidence}

        for edge in subgraph.edges:
            if edge.edge_type == EdgeType.EXPRESSES:
                stance = edge.qualifiers.get("stance")
                ev_ids = citation_ids(edge)
                target_ev = next((evidence_by_id[eid] for eid in edge.provenance.evidence_ids if eid in evidence_by_id), None)
                text_snippet = target_ev.raw_text if target_ev else ""

                if stance == "opposes":
                    contradictory_evidence.append({
                        "edge_id": str(edge.id),
                        "statement": text_snippet,
                        "stance": "opposes",
                        "evidence_ids": ev_ids,
                    })
        customer_perception.extend(subgraph.perception_observations)
        graph_relationships = [{
            "id": str(e.id), "type": e.edge_type.value,
            "from_id": str(e.from_node_id), "to_id": str(e.to_node_id),
            "from": next((n.name for n in subgraph.nodes if n.id == e.from_node_id), str(e.from_node_id)),
            "to": next((n.name for n in subgraph.nodes if n.id == e.to_node_id), str(e.to_node_id)),
            "qualifiers": e.qualifiers, "valid_from": e.valid_from.isoformat(),
            "recorded_at": e.recorded_at.isoformat(), "evidence_ids": citation_ids(e),
            "qualification": "Stored graph assertion; provenance integrity does not prove semantic correctness.",
        } for e in subgraph.edges]

        # 6. Market Relationships (Adjacent / Depends)
        market_relationships: list[dict[str, Any]] = []
        node_names = {n.id: n.name for n in subgraph.nodes}
        for edge in subgraph.edges:
            if edge.edge_type in {EdgeType.ADJACENT_TO, EdgeType.DEPENDS_ON, EdgeType.SERVES}:
                market_relationships.append({
                    "type": edge.edge_type.value,
                    "from": node_names.get(edge.from_node_id, str(edge.from_node_id)),
                    "to": node_names.get(edge.to_node_id, str(edge.to_node_id)),
                    "evidence_ids": citation_ids(edge),
                })

        # 7. Memesis Scores
        memesis_scores: list[dict[str, Any]] = []
        for s in scores:
            memesis_scores.append({
                "type": s.score_type.value,
                "subject_id": str(s.subject_id),
                "evidence_ids": [str(eid) for eid in s.evidence_ids if eid in available_evidence_ids],
                "coverage": s.coverage,
                "subject": node_names.get(s.subject_id, str(s.subject_id)),
                "value": round(s.value, 1),
                "formula": s.formula,
                "as_of": s.as_of.isoformat(),
                "window_start": s.window_start.isoformat() if s.window_start else None,
                "window_end": s.window_end.isoformat() if s.window_end else None,
            })

        # 8. Recent Changes
        recent_changes: list[dict[str, Any]] = []
        for ev in sorted(subgraph.evidence, key=lambda ev: ev.published_at or ev.retrieved_at, reverse=True):
            recent_changes.append({
                "id": str(ev.id),
                "summary": (ev.raw_text or "")[:120],
                "published_at": ev.published_at.isoformat() if ev.published_at else None,
            })

        # 9. Primary Evidence References
        evidence_refs: list[dict[str, Any]] = []
        for ev in subgraph.evidence:
            evidence_refs.append({
                "id": str(ev.id),
                "source_url": str(ev.source_url),
                "source_type": ev.source_type,
                "text": ev.raw_text,
                "published_at": ev.published_at.isoformat() if ev.published_at else None,
                "retrieved_at": ev.retrieved_at.isoformat(),
                "source_family": next((o["source_family"] for o in subgraph.memory_observations
                    if str(ev.id) in o.get("evidence_ids", []) and o.get("source_family")), source_family(ev)),
                "scope_membership": subgraph.evidence_membership.get(str(ev.id)),
            })

        # 10. Missing Information
        missing_info: list[str] = ["Records in a time window are not a measured change against a comparison baseline.",
            "Legacy graph assertions and source passages are not independently verified facts.",
            "Source families identify known copies; undiscovered syndication may remain.",
            "Independent reporting is not established by distinct actor names; confidence uses explicitly verified independence metadata only."]
        missing_info.extend(subgraph.coverage.get("limits", []))
        missing_info.append("Memory review states and perception metadata are not reconstructed historically; an earlier cutoff is not a full database replay.")
        for label, records in (("beliefs", key_beliefs), ("actors", key_actors), ("company actions", competitor_actions),
                               ("customer experiences", customer_perception), ("market relationships", market_relationships),
                               ("opposing assertions", contradictory_evidence)):
            if not records:
                missing_info.append(f"No recorded {label} retrieved in this scope; absence does not prove none exist.")
        if any(ev.published_at is None for ev in subgraph.evidence):
            missing_info.append("Some source records lack publication dates.")
        if market_motion:
            missing_info.extend(market_motion.coverage_gaps)

        # Calculate Token Count and Packet Hash
        # Candidates remain explicitly labelled; they are not observed graph facts.
        memory_observations = sorted(subgraph.memory_observations,
                                     key=lambda item: item["review_state"] != "accepted")[:40]
        missing_info.append(f"Connected memory includes {len(memory_observations)} observations in this packet; proposed records require review.")
        if len(subgraph.memory_observations) > len(memory_observations):
            missing_info.append(f"Memory observation budget retained {len(memory_observations)} of {len(subgraph.memory_observations)} scoped candidates; omitted candidates may change interpretation.")
        if subgraph.evidence_retained < subgraph.evidence_considered:
            missing_info.append(f"Retrieval retained {subgraph.evidence_retained} of {subgraph.evidence_considered} candidate source records; coverage is incomplete.")
        if subgraph.evidence_retained < subgraph.coverage.get("scoped_evidence", 0):
            missing_info.append(f"The packet contains {subgraph.evidence_retained} of {subgraph.coverage['scoped_evidence']} scoped source records; node and evidence budgets may omit relevant paths.")
        for o in memory_observations:
            if o.get("observation_type") == "company_action":
                competitor_actions.append({**o, "qualification": "Memory candidate; review state must be respected."})
            if o.get("observation_type") == "customer_experience":
                customer_perception.append({**o, "qualification": "Memory candidate; review state must be respected."})
            if o.get("meaning", {}).get("negated") or o.get("context", {}).get("stance") == "opposes":
                contradictory_evidence.append({**o, "qualification": "Potential qualification/negation; does not necessarily oppose the queried proposition."})
        missing_info = [gap for gap in missing_info if not (
            (competitor_actions and gap.startswith("No recorded company actions"))
            or (customer_perception and gap.startswith("No recorded customer experiences"))
            or (contradictory_evidence and gap.startswith("No recorded opposing assertions")))]
        serializable_body = {
            "question": question,
            "query_scope": subgraph.query_scope,
            "coverage": subgraph.coverage,
            "client_context": client_context,
            "intent": intent.model_dump(mode="json"),
            "beliefs": key_beliefs,
            "actors": key_actors,
            "companies": key_companies,
            "perception": customer_perception,
            "actions": competitor_actions,
            "relationships": market_relationships,
            "scores": memesis_scores,
            "recent_changes": recent_changes[:10],
            "analogues": [a.model_dump(mode="json") for a in analogues],
            "contradictions": contradictory_evidence,
            "evidence": evidence_refs,
            "missing": missing_info,
            "memory_observations": memory_observations,
            "graph_relationships": graph_relationships,
            "market_motion": market_motion.model_dump(mode="json") if market_motion else None,
        }
        body_json = json.dumps(serializable_body, sort_keys=True)
        packet_hash = hashlib.sha256(body_json.encode()).hexdigest()
        # ~4 chars per token approximation
        estimated_tokens = max(len(body_json) // 4, 1)

        return IntelligencePacket(
            question=question,
            query_scope=subgraph.query_scope,
            coverage=subgraph.coverage,
            client_context=client_context,
            query_intent=intent,
            key_beliefs=key_beliefs,
            key_actors=key_actors,
            key_companies=key_companies,
            customer_public_perception=customer_perception,
            competitor_actions=competitor_actions,
            market_relationships=market_relationships,
            memory_observations=memory_observations,
            graph_relationships=graph_relationships,
            market_motion=market_motion.model_dump(mode="json") if market_motion else None,
            memesis_scores=memesis_scores,
            recent_changes=recent_changes[:10],
            historical_analogues=analogues,
            contradictory_evidence=contradictory_evidence,
            primary_evidence_references=evidence_refs,
            missing_information=missing_info,
            estimated_tokens=estimated_tokens,
            packet_hash=packet_hash,
        )
