"""Watchlist administration; request work, never start collection in the web process."""
from datetime import UTC, datetime
from uuid import UUID
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from typing import Literal
from memesis.domain.schemas import NodeType
from memesis.investigations.contracts import InvestigationConfig
from memesis.investigations.store import InvestigationStore

router = APIRouter(prefix="/api", tags=["investigations"])

def store(request):
    return InvestigationStore(request.app.state.repository.session_factory)

def require(request, key):
    record = store(request).get(key)
    if record is None:
        raise HTTPException(404, "Investigation not found")
    return record

def validate_scope(request, config):
    if config.scope.market_id:
        node = request.app.state.repository.get_node(config.scope.market_id)
        if node is None or node.node_type != NodeType.MARKET:
            raise HTTPException(422, "Market scope must reference an existing market")

def lag(record):
    record = {**record, "state": dict(record["state"])}
    health = []
    for value in record["state"].get("source_health", {}).values():
        timestamp = value.get("last_completed_scan_at")
        health.append({**value, "collection_lag_seconds": (datetime.now(UTC) - datetime.fromisoformat(timestamp)).total_seconds() if timestamp else None})
    record["collection_health"] = health
    record["freshness_semantics"] = "Lag measures completion of configured searches, not completeness of market coverage."
    return record

@router.get("/investigations")
def list_investigations(request: Request):
    return {"investigations": [lag(r) for r in store(request).list()], "worker": store(request).health()}


@router.get("/investigations/templates")
def research_templates():
    from memesis.investigations.templates import templates
    return {"templates": templates(), "human_review_status": "pending",
            "semantics": "Draft questions; no customer validation or market conclusions established."}

@router.get("/markets/{market_id}/investigations")
def market_investigations(request: Request, market_id: UUID):
    return {"investigations": [lag(r) for r in store(request).list() if r["config"]["scope"].get("market_id") == str(market_id)],
            "worker": store(request).health()}

@router.post("/investigations", status_code=201)
def create(request: Request, config: InvestigationConfig):
    validate_scope(request, config)
    return store(request).create(config)

class UpdateRequest(BaseModel):
    config: InvestigationConfig
    expected_revision: int = Field(ge=1)

@router.put("/investigations/{key}")
def configure(request: Request, key: UUID, body: UpdateRequest):
    require(request, key)
    validate_scope(request, body.config)
    try:
        return store(request).configure(key, body.config, body.expected_revision)
    except ValueError as error:
        raise HTTPException(409, str(error)) from error

@router.get("/investigations/{key}")
def detail(request: Request, key: UUID):
    return {**lag(require(request, key)), "snapshots": store(request).history(key),
            "runs": store(request).runs(key), "pattern_reviews": store(request).reviews(key), "worker": store(request).health()}

@router.post("/investigations/{key}/run", status_code=202)
def enqueue(request: Request, key: UUID):
    require(request, key)
    try:
        store(request).request_run(key)
    except ValueError as error:
        raise HTTPException(409, str(error)) from error
    return {"status": "queued", "collection_started_by_api": False, "worker": store(request).health()}

class ReviewRequest(BaseModel):
    state: Literal["proposed", "reviewed", "rejected"]
    reviewer: str = Field(min_length=1, max_length=200)
    note: str = Field(min_length=1, max_length=4000)

@router.post("/investigations/{key}/patterns/{pattern_id}/review")
def review(request: Request, key: UUID, pattern_id: str, body: ReviewRequest):
    require(request, key)
    try:
        store(request).review(key, pattern_id, body.state, body.reviewer, body.note)
    except KeyError as error:
        raise HTTPException(404, "Pattern not found") from error
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    return {"status": body.state, "graph_assertions_promoted": False, "review_history": store(request).reviews(key)}
