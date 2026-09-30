"""Clean JSON API router for Memesis product frontend."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from memesis.domain.schemas import (
    EdgeType,
    NodeType,
    ScoreType,
)
from memesis.graph.repository import GraphRepository
from memesis.reasoning.engine import MemesisReasoningEngine
from memesis.retrieval.scope import QueryScope, ScopeOptions, ScopedGraphRepository, utc

api_router = APIRouter(prefix="/api")


class AskRequest(ScopeOptions):
    question: str


def _claim_response(claim, evidence_by_id: dict[str, dict[str, Any]], section: str) -> dict[str, Any]:
    evidence_ids = [str(evidence_id) for evidence_id in claim.evidence_ids]
    return {
        "section": section,
        "text": claim.text,
        "status": claim.epistemic_status.value,
        "evidence_ids": evidence_ids,
        "evidence_link_status": claim.evidence_link_status,
        "evidence_support_status": claim.evidence_support_status,
        "evidence_support_note": claim.evidence_support_note,
        "downgraded_reason": claim.downgraded_reason,
        "evidence": [
            {
                **evidence_by_id[evidence_id],
                "relation": "counterevidence" if section == "contradictory_evidence" else "candidate_support",
            }
            for evidence_id in evidence_ids
            if evidence_id in evidence_by_id
        ],
    }


def _get_repo(request: Request) -> GraphRepository:
    return request.app.state.repository


def _scope_options(
    start_at: datetime | None = None,
    as_of: datetime | None = None,
    time_basis: Literal["published_at", "known_at"] = "published_at",
    graph_hops: int = Query(default=3, ge=1, le=6),
    include_adjacent_markets: bool = True,
) -> ScopeOptions:
    try:
        return ScopeOptions(
            start_at=start_at, as_of=as_of or datetime.now(UTC), time_basis=time_basis,
            graph_hops=graph_hops, include_adjacent_markets=include_adjacent_markets,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _market_view(repo: GraphRepository, market_id: UUID, options: ScopeOptions) -> ScopedGraphRepository:
    market = repo.get_node(market_id)
    if market is None or market.node_type != NodeType.MARKET:
        raise HTTPException(status_code=404, detail=f"Market {market_id} not found")
    return ScopedGraphRepository(repo, QueryScope(market_id=market_id, **options.model_dump()))


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
def list_markets(request: Request, options: ScopeOptions = Depends(_scope_options)) -> list[dict[str, Any]]:
    repo = _get_repo(request)
    markets = [n for n in repo.list_nodes() if n.node_type == NodeType.MARKET]
    result = []
    for m in sorted(markets, key=lambda n: n.name):
        view = _market_view(repo, m.id, options)
        result.append({
            "id": str(m.id),
            "name": m.name,
            "node_count": len(view.nodes),
            "evidence_count": len(view.evidence),
            "query_scope": view.scope_metadata(),
            "coverage": view.coverage,
        })
    return result


@api_router.get("/markets/{market_id}")
def get_market_workspace(
    request: Request, market_id: UUID, options: ScopeOptions = Depends(_scope_options),
) -> dict[str, Any]:
    repo = _get_repo(request)
    view = _market_view(repo, market_id, options)
    nodes, edges, evidence = _load_graph(view)
    market = nodes[market_id]

    # Compute deterministic scores
    scores = view.compute_scores()

    lead_map = _score_map(scores, ScoreType.ACTOR_LEAD)
    inf_map = _score_map(scores, ScoreType.ACTOR_INFLUENCE)
    vel_map = _score_map(scores, ScoreType.BELIEF_VELOCITY)
    div_map = _score_map(scores, ScoreType.BELIEF_DIVERSITY)

    relevant_nodes = list(nodes.values())
    relevant_edges = edges
    people_nodes = [n for n in relevant_nodes if n.node_type == NodeType.PERSON]
    belief_nodes = [n for n in relevant_nodes if n.node_type == NodeType.BELIEF]
    company_nodes = [n for n in relevant_nodes if n.node_type == NodeType.COMPANY]
    adjacent_nodes = [
        nodes[e.to_node_id] for e in edges
        if e.from_node_id == market_id and e.edge_type == EdgeType.ADJACENT_TO and e.to_node_id in nodes
    ] + [
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
            "velocity_available": b.id in vel_map,
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
    for ev in sorted(timeline_evidence, key=lambda e: utc(e.published_at or e.retrieved_at), reverse=True):
        timeline_data.append({
            "id": str(ev.id),
            "published_at": ev.published_at.isoformat() if ev.published_at else None,
            "source_type": ev.source_type,
            "source_url": str(ev.source_url) if ev.source_url else "",
            "text": ev.normalized_text or ev.raw_text or "",
            "scope_membership": view.evidence_membership.get(str(ev.id)),
        })

    # Graph visualization payload
    display_nodes = relevant_nodes
    display_node_ids = {n.id for n in display_nodes}
    display_edges = [e for e in edges if e.from_node_id in display_node_ids and e.to_node_id in display_node_ids]

    graph_data = {
        "nodes": [
            {
                "id": str(n.id),
                "name": n.name,
                "type": n.node_type.value,
                "market_distance": view.node_distances.get(n.id),
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
        "query_scope": view.scope_metadata(),
        "coverage": {**view.coverage, "timeline_returned": min(len(timeline_data), 100)},
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
    scope = QueryScope(market_id=market_id, **req.model_dump(exclude={"question"}))
    output, metrics, packet = engine.answer_query(
        req.question, client_context=market.name, scope=scope,
    )

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

    # Expose the packet's evidence directly so every claim can link to the exact
    # source record that was available during this answer run.
    evidence_by_id: dict[str, dict[str, Any]] = {}
    for ref in packet.primary_evidence_references:
        evidence_id = str(ref.get("id", ""))
        if not evidence_id:
            continue
        evidence_by_id[evidence_id] = {
            "id": evidence_id,
            "text": ref.get("text", ""),
            "source_url": str(ref.get("source_url") or ""),
            "source_type": ref.get("source_type", "unknown"),
            "published_at": ref.get("published_at"),
            "retrieved_at": ref.get("retrieved_at"),
            "scope_membership": ref.get("scope_membership"),
        }

    claim_sections = (
        ("what_is_happening", output.what_is_happening),
        ("who_matters", output.who_matters),
        ("what_they_believe", output.what_they_believe),
        ("company_actions", output.company_actions),
        ("perception", output.perception),
        ("what_changed", output.what_changed),
        ("adjacent_markets", output.adjacent_markets),
        ("possible_implications", output.possible_implications),
        ("contradictory_evidence", output.contradictory_evidence),
    )
    claims = [
        _claim_response(claim, evidence_by_id, section)
        for section, section_claims in claim_sections
        for claim in section_claims
    ]

    primary_citations = list(evidence_by_id.values())

    # Analogues
    analogues_data = [
        {
            "analogue": a.analogue,
            "time_lag_observed": a.time_lag_observed,
            "similarity_confidence": round(a.similarity_confidence, 2),
            "similarity_semantics": "heuristic structural match score; not a probability of historical equivalence",
            "similarities": a.similarities,
            "differences": a.differences,
            "current_evidence_ids": [
                evidence_id
                for evidence_id in a.current_evidence_ids
                if evidence_id in evidence_by_id
            ],
            "current_evidence": [
                {
                    **evidence_by_id[evidence_id],
                    "relation": "basis_for_current_side_of_analogy",
                }
                for evidence_id in a.current_evidence_ids
                if evidence_id in evidence_by_id
            ],
            "historical_basis_status": "curated_analogy_template_not_independently_sourced",
        }
        for a in output.historical_analogues
    ]

    return {
        "question": req.question,
        "query_scope": packet.query_scope,
        "coverage": packet.coverage,
        "summary": output.summary,
        "summary_trace": {
            "evidence_ids": output.summary_evidence_ids,
            "scope": "answer-level context; inspect individual claims for claim-level links",
        },
        "confidence": output.confidence.overall_confidence,
        "confidence_breakdown": output.confidence.model_dump(mode="json"),
        "confidence_semantics": "evidence coverage and auditability; not probability that a claim is true",
        "citation_audit": output.citation_audit or {
            "claims_checked": 0,
            "claims_with_valid_citations": 0,
            "claims_without_valid_citations": 0,
            "invalid_citations_removed": 0,
            "citation_links_are_not_semantic_support_verification": True,
            "exploratory_claims_preserved": True,
        },
        "claims": claims,
        "observed_claims": observed_claims,
        "inferred_claims": inferred_claims,
        "speculative_claims": speculative_claims,
        "who_matters": [c.text for c in output.who_matters],
        "what_they_believe": [c.text for c in output.what_they_believe],
        "what_changed": [c.text for c in output.what_changed],
        "historical_analogues": analogues_data,
        "possible_implications": [c.text for c in output.possible_implications],
        "unknown_or_missing": output.unknown_or_missing,
        "contradictory_evidence": [c.text for c in output.contradictory_evidence],
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
