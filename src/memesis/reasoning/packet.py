"""Builder for compact, provenance-backed IntelligencePacket objects."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from memesis.domain.schemas import EdgeType, NodeType, ScoreRecord
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

        # 1. Key Beliefs
        key_beliefs: list[dict[str, Any]] = []
        for n in subgraph.nodes:
            if n.node_type == NodeType.BELIEF:
                key_beliefs.append({
                    "id": str(n.id),
                    "name": n.name,
                    "evidence_ids": [str(eid) for eid in n.provenance.evidence_ids],
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
                    "score_summary": f"Score: {sub_score.value:.1f}" if sub_score else "Active speaker",
                    "evidence_ids": [str(eid) for eid in n.provenance.evidence_ids],
                })

        # 3. Key Companies
        key_companies: list[dict[str, Any]] = []
        for n in subgraph.nodes:
            if n.node_type == NodeType.COMPANY:
                key_companies.append({
                    "id": str(n.id),
                    "name": n.name,
                    "evidence_ids": [str(eid) for eid in n.provenance.evidence_ids],
                })

        # 4. Competitor Actions / Events
        competitor_actions: list[dict[str, Any]] = []
        for n in subgraph.nodes:
            if n.node_type == NodeType.EVENT:
                competitor_actions.append({
                    "id": str(n.id),
                    "name": n.name,
                    "subtype": n.attributes.get("subtype", "event"),
                    "evidence_ids": [str(eid) for eid in n.provenance.evidence_ids],
                })

        # 5. Customer / Public Perception
        customer_perception: list[dict[str, Any]] = []
        contradictory_evidence: list[dict[str, Any]] = []
        evidence_by_id = {ev.id: ev for ev in subgraph.evidence}

        for edge in subgraph.edges:
            if edge.edge_type == EdgeType.EXPRESSES:
                stance = edge.qualifiers.get("stance")
                ev_ids = [str(eid) for eid in edge.provenance.evidence_ids]
                target_ev = evidence_by_id.get(edge.provenance.evidence_ids[0]) if edge.provenance.evidence_ids else None
                text_snippet = target_ev.raw_text if target_ev else ""

                if stance == "opposes" or any(w in text_snippet.lower() for w in ["will not", "cannot replace", "not replace"]):
                    contradictory_evidence.append({
                        "edge_id": str(edge.id),
                        "statement": text_snippet,
                        "stance": "opposes",
                        "evidence_ids": ev_ids,
                    })
                elif any(w in text_snippet.lower() for w in ["cost", "latency", "pain", "dislike", "expensive"]):
                    customer_perception.append({
                        "edge_id": str(edge.id),
                        "statement": text_snippet,
                        "category": "developer_pain",
                        "evidence_ids": ev_ids,
                    })

        # 6. Market Relationships (Adjacent / Depends)
        market_relationships: list[dict[str, Any]] = []
        node_names = {n.id: n.name for n in subgraph.nodes}
        for edge in subgraph.edges:
            if edge.edge_type in {EdgeType.ADJACENT_TO, EdgeType.DEPENDS_ON, EdgeType.SERVES}:
                market_relationships.append({
                    "type": edge.edge_type.value,
                    "from": node_names.get(edge.from_node_id, str(edge.from_node_id)),
                    "to": node_names.get(edge.to_node_id, str(edge.to_node_id)),
                    "evidence_ids": [str(eid) for eid in edge.provenance.evidence_ids],
                })

        # 7. Memesis Scores
        memesis_scores: list[dict[str, Any]] = []
        for s in scores:
            memesis_scores.append({
                "type": s.score_type.value,
                "subject": node_names.get(s.subject_id, str(s.subject_id)),
                "value": round(s.value, 1),
                "formula": s.formula,
            })

        # 8. Recent Changes
        recent_changes: list[dict[str, Any]] = []
        for ev in subgraph.evidence:
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
            })

        # 10. Missing Information
        missing_info: list[str] = [
            "Customer churn data comparing general vs specialized models is unobserved in public sources",
            "Hardware margin and ASIC cost structures remain non-public proprietary estimates",
        ]

        # Calculate Token Count and Packet Hash
        serializable_body = {
            "question": question,
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
            "evidence": evidence_refs[:25],
            "missing": missing_info,
        }
        body_json = json.dumps(serializable_body, sort_keys=True)
        packet_hash = hashlib.sha256(body_json.encode()).hexdigest()
        # ~4 chars per token approximation
        estimated_tokens = max(len(body_json) // 4, 1)

        return IntelligencePacket(
            question=question,
            client_context=client_context,
            query_intent=intent,
            key_beliefs=key_beliefs,
            key_actors=key_actors,
            key_companies=key_companies,
            customer_public_perception=customer_perception,
            competitor_actions=competitor_actions,
            market_relationships=market_relationships,
            memesis_scores=memesis_scores,
            recent_changes=recent_changes[:10],
            historical_analogues=analogues,
            contradictory_evidence=contradictory_evidence,
            primary_evidence_references=evidence_refs,
            missing_information=missing_info,
            estimated_tokens=estimated_tokens,
            packet_hash=packet_hash,
        )
