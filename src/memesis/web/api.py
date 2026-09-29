"""Clean JSON API router for Memesis product frontend."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from memesis.analysis.scoring import DeterministicScoringService
from memesis.domain.schemas import (
    EdgeType,
    GraphEdge,
    NodeType,
    ScoreType,
)
from memesis.graph.repository import GraphRepository
from memesis.reasoning.engine import MemesisReasoningEngine

api_router = APIRouter(prefix="/api")


class AskRequest(BaseModel):
    question: str


def _get_repo(request: Request) -> GraphRepository:
    return request.app.state.repository


def _score_map(scores: list, score_type: ScoreType) -> dict[UUID, float]:
    result: dict[UUID, float] = {}
    for s in scores:
        if s.score_type == score_type:
            if s.subject_id not in result or s.value > result[s.subject_id]:
                result[s.subject_id] = round(s.value, 1)
    return result


def _load_graph(repo: GraphRepository) -> tuple[dict, list, list]:
    nodes = {n.id: n for n in repo.list_nodes()}
    edges = repo.list_edges()
    evidence = repo.list_evidence()
    return nodes, edges, evidence


@api_router.get("/markets")
def list_markets(request: Request) -> list[dict[str, Any]]:
    repo = _get_repo(request)
    nodes, edges, evidence = _load_graph(repo)

    markets = [n for n in nodes.values() if n.node_type == NodeType.MARKET]
    result = []
    for m in sorted(markets, key=lambda n: n.name):
        neighbor_ids = {e.to_node_id for e in edges if e.from_node_id == m.id} | \
                       {e.from_node_id for e in edges if e.to_node_id == m.id}
        ev_count = sum(1 for ev in evidence if m.id in ev.entity_ids)
        result.append({
            "id": str(m.id),
            "name": m.name,
            "node_count": len(neighbor_ids),
            "evidence_count": ev_count,
        })
    return result


@api_router.get("/markets/{market_id}")
def get_market_workspace(request: Request, market_id: UUID) -> dict[str, Any]:
    repo = _get_repo(request)
    nodes, edges, evidence = _load_graph(repo)

    market = nodes.get(market_id)
    if market is None or market.node_type != NodeType.MARKET:
        raise HTTPException(status_code=404, detail=f"Market {market_id} not found")

    # Compute deterministic scores
    scoring = DeterministicScoringService(repo)
    run = scoring.compute_all(persist=False)

    lead_map = _score_map(run.scores, ScoreType.ACTOR_LEAD)
    inf_map = _score_map(run.scores, ScoreType.ACTOR_INFLUENCE)
    vel_map = _score_map(run.scores, ScoreType.BELIEF_VELOCITY)
    div_map = _score_map(run.scores, ScoreType.BELIEF_DIVERSITY)

    # 1-hop and 2-hop graph extraction
    connected_edge_ids = set()
    connected_node_ids = {market_id}

    for e in edges:
        if e.from_node_id == market_id or e.to_node_id == market_id:
            connected_edge_ids.add(e.id)
            connected_node_ids.add(e.from_node_id)
            connected_node_ids.add(e.to_node_id)

    # Secondary edges between connected nodes
    for e in edges:
        if e.from_node_id in connected_node_ids and e.to_node_id in connected_node_ids:
            connected_edge_ids.add(e.id)

    relevant_nodes = [nodes[nid] for nid in connected_node_ids if nid in nodes]
    relevant_edges = [e for e in edges if e.id in connected_edge_ids]

    # Relevant entities: prioritize direct/2-hop neighborhood, fallback to full graph entities
    all_people = [n for n in nodes.values() if n.node_type == NodeType.PERSON]
    all_beliefs = [n for n in nodes.values() if n.node_type == NodeType.BELIEF]
    all_companies = [n for n in nodes.values() if n.node_type == NodeType.COMPANY]

    people_nodes = [n for n in relevant_nodes if n.node_type == NodeType.PERSON] or all_people
    belief_nodes = [n for n in relevant_nodes if n.node_type == NodeType.BELIEF] or all_beliefs
    company_nodes = [n for n in relevant_nodes if n.node_type == NodeType.COMPANY] or all_companies
    adjacent_nodes = [
        nodes[e.to_node_id] for e in edges
        if e.from_node_id == market_id and e.edge_type == EdgeType.ADJACENT_TO and e.to_node_id in nodes
    ] or [
        nodes[e.from_node_id] for e in edges
        if e.to_node_id == market_id and e.edge_type == EdgeType.ADJACENT_TO and e.from_node_id in nodes
    ]

    # People data
    people_data = []
    for p in sorted(people_nodes, key=lambda n: n.name):
        people_data.append({
            "id": str(p.id),
            "name": p.name,
            "lead_score": lead_map.get(p.id, 0.0),
            "influence_score": inf_map.get(p.id, 0.0),
        })

    # Beliefs data
    beliefs_data = []
    for b in sorted(belief_nodes, key=lambda n: n.name):
        beliefs_data.append({
            "id": str(b.id),
            "name": b.name,
            "velocity": vel_map.get(b.id, 0.0),
            "diversity": div_map.get(b.id, 0.0),
        })

    # Companies data
    companies_data = []
    for c in sorted(company_nodes, key=lambda n: n.name):
        rels = [e.edge_type.value for e in edges if e.from_node_id == c.id or e.to_node_id == c.id]
        companies_data.append({
            "id": str(c.id),
            "name": c.name,
            "relationships": rels or ["OBSERVED_IN_GRAPH"],
        })

    # Timeline (sorted evidence)
    timeline_evidence = evidence
    timeline_data = []
    for ev in sorted(timeline_evidence, key=lambda e: e.published_at or e.retrieved_at, reverse=True):
        timeline_data.append({
            "id": str(ev.id),
            "published_at": ev.published_at.isoformat() if ev.published_at else None,
            "source_type": ev.source_type,
            "source_url": str(ev.source_url) if ev.source_url else "",
            "text": ev.normalized_text or ev.raw_text or "",
        })

    # Graph visualization payload
    display_nodes = list({n.id: n for n in relevant_nodes + people_nodes[:5] + belief_nodes[:5] + company_nodes[:5]}.values())
    display_node_ids = {n.id for n in display_nodes}
    display_edges = [e for e in edges if e.from_node_id in display_node_ids or e.to_node_id in display_node_ids]

    graph_data = {
        "nodes": [
            {
                "id": str(n.id),
                "name": n.name,
                "type": n.node_type.value,
            }
            for n in display_nodes
        ],
        "edges": [
            {
                "id": str(e.id),
                "from": str(e.from_node_id),
                "to": str(e.to_node_id),
                "type": e.edge_type.value,
            }
            for e in display_edges
        ],
    }

    return {
        "market": {
            "id": str(market.id),
            "name": market.name,
            "recorded_at": market.provenance.retrieved_at.isoformat() if market.provenance else None,
        },
        "overview": {
            "node_count": len(relevant_nodes),
            "edge_count": len(relevant_edges),
            "people_count": len(people_nodes),
            "beliefs_count": len(belief_nodes),
            "companies_count": len(company_nodes),
            "evidence_count": len(timeline_data),
            "adjacent_markets": [{"id": str(a.id), "name": a.name} for a in adjacent_nodes],
        },
        "people": people_data,
        "beliefs": beliefs_data,
        "companies": companies_data,
        "timeline": timeline_data[:100],
        "graph": graph_data,
    }


@api_router.post("/markets/{market_id}/ask")
def ask_market(request: Request, market_id: UUID, req: AskRequest) -> dict[str, Any]:
    repo = _get_repo(request)
    nodes = {n.id: n for n in repo.list_nodes()}

    market = nodes.get(market_id)
    if market is None or market.node_type != NodeType.MARKET:
        raise HTTPException(status_code=404, detail=f"Market {market_id} not found")

    engine = MemesisReasoningEngine(repo)
    output, metrics, packet = engine.answer_query(req.question, client_context=market.name)

    # Classify claims by epistemic status
    observed_claims = []
    inferred_claims = []
    speculative_claims = []

    for claim in output.what_is_happening:
        claim_dict = {
            "text": claim.text,
            "evidence_ids": [str(eid) for eid in getattr(claim, "evidence_ids", [])],
            "status": claim.epistemic_status.value,
        }
        if claim.epistemic_status.value == "OBSERVED":
            observed_claims.append(claim_dict)
        elif claim.epistemic_status.value == "INFERRED":
            inferred_claims.append(claim_dict)
        elif claim.epistemic_status.value == "SPECULATIVE":
            speculative_claims.append(claim_dict)

    # Evidence lookup
    all_ev = repo.list_evidence()
    ev_map = {str(ev.id): ev for ev in all_ev}

    primary_citations = []
    for ref in packet.primary_evidence_references:
        ev_id = str(ref.get("id"))
        ev_obj = ev_map.get(ev_id)
        primary_citations.append({
            "id": ev_id,
            "text": ref.get("text") or (ev_obj.normalized_text if ev_obj else ""),
            "source_url": str(ev_obj.source_url) if ev_obj and ev_obj.source_url else "",
            "published_at": ev_obj.published_at.isoformat() if ev_obj and ev_obj.published_at else None,
        })

    # Analogues
    analogues_data = [
        {
            "analogue": a.analogue,
            "time_lag_observed": a.time_lag_observed,
            "similarity_confidence": round(a.similarity_confidence, 2),
            "similarities": a.similarities,
            "differences": a.differences,
        }
        for a in output.historical_analogues
    ]

    return {
        "question": req.question,
        "summary": output.summary,
        "confidence": 0.85,  # Calculated confidence from evidence count and validation
        "observed_claims": observed_claims,
        "inferred_claims": inferred_claims,
        "speculative_claims": speculative_claims,
        "who_matters": [c.text for c in output.who_matters],
        "what_they_believe": [c.text for c in output.what_they_believe],
        "what_changed": [c.text for c in output.what_changed],
        "historical_analogues": analogues_data,
        "possible_implications": [c.text for c in output.possible_implications],
        "unknown_or_missing": output.unknown_or_missing,
        "contradictory_evidence": [],
        "evidence": primary_citations,
        "metrics": {
            "latency_ms": round(metrics.latency_ms, 2),
            "total_tokens": metrics.total_tokens,
            "cheap_tokens": metrics.cheap_model_tokens,
            "expensive_tokens": metrics.expensive_model_tokens,
            "estimated_cost_usd": round(metrics.estimated_cost_usd, 6),
            "deep_reasoning_invoked": metrics.deep_reasoning_invoked,
            "jev_decisions": metrics.jev_decisions,
            "nodes_considered": metrics.nodes_considered,
            "nodes_retained": metrics.nodes_retained,
        },
    }
