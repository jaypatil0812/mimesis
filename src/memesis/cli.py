"""Small developer CLI for graph creation and provenance round trips."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from alembic import command
from alembic.config import Config

from memesis.analysis.scoring import DeterministicScoringService
from memesis.config import settings
from memesis.db.session import initialize_schema, make_engine, make_session_factory
from memesis.domain.schemas import (
    CanonicalNode,
    Document,
    DocumentVersion,
    Evidence,
    NodeType,
    Source,
)
from memesis.extraction.evaluation import evaluate_phase3_sync
from memesis.extraction.model import OpenAICompatibleStructuredExtractor
from memesis.extraction.pipeline import EvidenceGraphPipeline
from memesis.graph.sql_repository import SqlGraphRepository
from memesis.ingestion.http import ResilientHttpClient
from memesis.ingestion.service import IngestionService
from memesis.knowledge.service import KnowledgeService
from memesis.logging_config import configure_logging
from memesis.reasoning.engine import MemesisReasoningEngine
from memesis.reasoning.evaluation import evaluate_phase5, seed_phase5_fixture
from memesis.retrieval.service import RetrievalService
from memesis.sources import (
    BlueskyAdapter,
    HackerNewsAdapter,
    OpenAlexAdapter,
    RssAdapter,
    WebPageAdapter,
)

logger = logging.getLogger("memesis.cli")
REPO_ROOT = Path(__file__).resolve().parents[2]


def _repository(database_url: str | None, *, initialize: bool = False) -> SqlGraphRepository:
    engine = make_engine(database_url or settings.database_url)
    if initialize:
        initialize_schema(engine)
    return SqlGraphRepository(make_session_factory(engine))


def _create_record(
    repository: SqlGraphRepository,
    *,
    node_type: str,
    name: str,
    source_url: str,
    text_content: str,
    source_type: str = "manual",
    published_at: datetime | None = None,
) -> tuple[CanonicalNode, Evidence]:
    now = datetime.now(UTC)
    source_key = f"{source_type}:{source_url}"
    source = repository.add_source(
        Source(source_key=source_key, source_type=source_type, base_url=source_url)
    )
    document = repository.add_document(
        Document(source_id=source.id, external_id=source_url, canonical_url=source_url)
    )
    version = repository.add_document_version(
        DocumentVersion(
            document_id=document.id,
            content_hash=hashlib.sha256(text_content.encode()).hexdigest(),
            raw_payload=text_content,
            retrieved_at=now,
            published_at=published_at,
        )
    )
    evidence = repository.add_evidence(
        Evidence(
            source_id=source.id,
            document_version_id=version.id,
            source_url=source_url,
            source_type=source_type,
            retrieved_at=now,
            published_at=published_at,
            original_reference=text_content[:200],
            raw_text=text_content,
            normalized_text=text_content,
            content_hash=hashlib.sha256(text_content.encode()).hexdigest(),
        )
    )
    node = KnowledgeService(repository).create_node(NodeType(node_type), name, evidence.id)
    return node, evidence


def _jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    return value


def _print(value: Any) -> None:
    print(json.dumps(_jsonable(value), indent=2, sort_keys=True))


def _configured_extraction_models():
    if not settings.model_api_key:
        return None, None
    cheap = (
        OpenAICompatibleStructuredExtractor(
            base_url=settings.model_api_base_url,
            api_key=settings.model_api_key,
            model_name=settings.extract_small_model,
            prompt_version="evidence-graph-extract-v1",
            timeout_seconds=settings.ingestion_request_timeout_seconds,
        )
        if settings.extract_small_model
        else None
    )
    strong = (
        OpenAICompatibleStructuredExtractor(
            base_url=settings.model_api_base_url,
            api_key=settings.model_api_key,
            model_name=settings.reason_strong_model,
            prompt_version="evidence-graph-ambiguity-v1",
            timeout_seconds=settings.ingestion_request_timeout_seconds,
        )
        if settings.reason_strong_model
        else None
    )
    return cheap, strong


def _demo(database_url: str) -> dict[str, Any]:
    repository = _repository(database_url, initialize=True)
    sample = json.loads((REPO_ROOT / "data" / "demo.json").read_text())
    person, _person_evidence = _create_record(
        repository,
        node_type="Person",
        name=sample["person"],
        source_url=sample["source_url"],
        text_content=sample["source_text"],
        source_type=sample["source_type"],
    )
    belief, _belief_evidence = _create_record(
        repository,
        node_type="Belief",
        name=sample["belief"],
        source_url=sample["source_url"],
        text_content=sample["source_text"],
        source_type=sample["source_type"],
    )
    content, content_evidence = _create_record(
        repository,
        node_type="Content",
        name=sample["content"],
        source_url=sample["source_url"],
        text_content=sample["source_text"],
        source_type=sample["source_type"],
    )
    knowledge = KnowledgeService(repository)
    published = knowledge.publish(person.id, content.id, content_evidence.id)
    expresses = knowledge.express(content.id, belief.id, content_evidence.id)
    graph = RetrievalService(repository).subgraph([person.id], hops=2)
    retrieved_evidence = [
        repository.get_evidence(ref)
        for edge in graph["edges"]
        for ref in edge.provenance.evidence_ids
    ]
    round_trip = bool(retrieved_evidence) and all(
        item is not None and item.source_url == content_evidence.source_url
        for item in retrieved_evidence
    )
    return {
        "created_ids": {
            "person": str(person.id),
            "belief": str(belief.id),
            "content": str(content.id),
            "published_edge": str(published.id),
            "expresses_edge": str(expresses.id),
        },
        "subgraph": graph,
        "provenance_round_trip": round_trip,
    }


async def _ingest(
    database_url: str, query: str, *, web_url: str, rss_url: str, limit: int
) -> dict[str, Any]:
    repository = _repository(database_url, initialize=True)
    client = ResilientHttpClient(repository, settings)
    service = IngestionService(repository)
    adapters = [
        WebPageAdapter(client, web_url),
        HackerNewsAdapter(client),
        BlueskyAdapter(client),
        OpenAlexAdapter(client, settings),
        RssAdapter(client, rss_url),
    ]
    try:
        reports = [await service.collect(adapter, query, limit=limit) for adapter in adapters]
    finally:
        await client.aclose()
    return {
        "query": query,
        "sources": [report.as_metrics() for report in reports],
        "totals": {
            "documents_collected": sum(report.documents_fetched for report in reports),
            "documents_persisted": sum(report.documents_persisted for report in reports),
            "duplicates_removed": sum(report.duplicates_removed for report in reports),
            "failures": sum(len(report.failures) for report in reports),
            "external_api_requests": sum(report.external_api_requests for report in reports),
            "cache_hits": sum(report.cache_hits for report in reports),
            "llm_calls": 0,
            "estimated_cost_usd": 0.0,
            "runtime_seconds": sum(report.runtime_seconds for report in reports),
            "storage": repository.storage_metrics(),
        },
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="memesis", description="Memesis evidence and graph tools")
    parser.add_argument("--database-url", help="override MEMESIS_DATABASE_URL")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("health", help="check database connectivity")
    commands.add_parser("db-upgrade", help="apply Alembic migrations")
    demo = commands.add_parser("demo", help="create and retrieve a provenance-backed demo graph")
    demo.add_argument("--database-url", dest="demo_database_url", help=argparse.SUPPRESS)
    ingest = commands.add_parser(
        "ingest", help="collect a bounded evidence batch without any LLM calls"
    )
    ingest.add_argument("--query", default="AI infrastructure")
    ingest.add_argument("--limit", type=int, default=3)
    ingest.add_argument("--web-url", default="https://www.anthropic.com/news/claude-3-5-sonnet")
    ingest.add_argument("--rss-url", default="https://huggingface.co/blog/feed.xml")
    graph = commands.add_parser(
        "build-graph", help="project normalized evidence into a provenance-backed graph"
    )
    graph.add_argument("--limit", type=int)
    commands.add_parser("evaluate-phase3", help="run the 30-example Evidence-to-Graph evaluation")
    scores = commands.add_parser(
        "compute-scores", help="compute transparent historical scores without an LLM"
    )
    scores.add_argument("--as-of", help="historical cutoff as an ISO-8601 timestamp (default: now)")
    scores.add_argument("--window-days", type=int, default=30)
    explain = commands.add_parser("explain-score", help="show every component behind a score")
    explain.add_argument("--score-id", required=True, type=UUID)

    for name in ("create-person", "create-belief", "create-content"):
        create = commands.add_parser(name, help=f"create a {name.removeprefix('create-')} record")
        create.add_argument("--name", required=True)
        create.add_argument("--source-url", required=True)
        create.add_argument("--text", required=True)
        create.add_argument("--source-type", default="manual")

    connect = commands.add_parser("connect", help="add PUBLISHED or EXPRESSES with evidence")
    connect.add_argument("edge_type", choices=("PUBLISHED", "EXPRESSES"))
    connect.add_argument("--from-id", required=True, type=UUID)
    connect.add_argument("--to-id", required=True, type=UUID)
    connect.add_argument("--evidence-id", required=True, type=UUID)

    retrieve = commands.add_parser("retrieve", help="retrieve a bounded graph subgraph")
    retrieve.add_argument("--seed-id", required=True, type=UUID, action="append")
    retrieve.add_argument("--hops", type=int, default=2)

    ask = commands.add_parser("ask", help="answer a strategic market question using Phase 5 engine")
    ask.add_argument("question", help="the user question")
    ask.add_argument("--client-context", help="optional client context")
    ask.add_argument("--full-context", action="store_true", help="force full-context unconstrained pipeline A")

    profile = commands.add_parser(
        "profile",
        help="profile the end-to-end pipeline and report bottlenecks",
    )
    profile.add_argument("question", help="the question to profile")
    profile.add_argument("--json", dest="json_output", action="store_true", help="output JSON")
    profile.add_argument("--optimize", action="store_true", help="also run optimizer and show savings")

    eval5 = commands.add_parser("evaluate-phase5", help="evaluate Phase 5 reasoning engine across 10 queries")
    eval5.add_argument("--output", default="data/evaluation/phase5_report.json", help="path to save evaluation report")
    return parser


def main() -> None:
    configure_logging(settings.log_level)
    args = _parser().parse_args()
    if args.database_url:
        settings.database_url = args.database_url
    if args.command == "db-upgrade":
        config = Config(str(REPO_ROOT / "alembic.ini"))
        command.upgrade(config, "head")
        print("Database schema upgraded to head")
        return
    if args.command == "demo":
        result = _demo(args.demo_database_url or args.database_url or settings.database_url)
        _print(result)
        return
    if args.command == "ingest":
        _print(
            asyncio.run(
                _ingest(
                    args.database_url or settings.database_url,
                    args.query,
                    web_url=args.web_url,
                    rss_url=args.rss_url,
                    limit=args.limit,
                )
            )
        )
        return
    if args.command == "build-graph":
        repository = _repository(args.database_url, initialize=True)
        cheap, strong = _configured_extraction_models()
        report = asyncio.run(
            EvidenceGraphPipeline(repository, cheap_model=cheap, ambiguity_model=strong).run(
                limit=args.limit
            )
        )
        _print({"report": report.as_metrics(), "storage": repository.storage_metrics()})
        return
    if args.command == "evaluate-phase3":
        _print(evaluate_phase3_sync(REPO_ROOT / "data" / "evaluation" / "phase3_examples.json"))
        return
    if args.command == "compute-scores":
        repository = _repository(args.database_url, initialize=True)
        as_of = datetime.fromisoformat(args.as_of.replace("Z", "+00:00")) if args.as_of else None
        run = DeterministicScoringService(repository).compute_all(
            as_of=as_of, window_days=args.window_days
        )
        _print(
            {
                "report": run.as_metrics(),
                "scores": run.scores,
                "storage": repository.storage_metrics(),
            }
        )
        return
    if args.command == "explain-score":
        repository = _repository(args.database_url)
        _print(DeterministicScoringService(repository).explain(args.score_id))
        return
    if args.command == "ask":
        repository = _repository(args.database_url, initialize=True)
        seed_phase5_fixture(repository)
        engine = MemesisReasoningEngine(repository)
        output, metrics, packet = engine.answer_query(
            args.question,
            client_context=args.client_context,
            force_full_context=args.full_context,
        )
        _print({
            "question": args.question,
            "pipeline": "pipeline_a_full_context" if args.full_context else "pipeline_b_memesis",
            "answer": output,
            "metrics": metrics,
            "packet_summary": {
                "hash": packet.packet_hash,
                "estimated_tokens": packet.estimated_tokens,
                "primary_evidence_count": len(packet.primary_evidence_references),
            },
        })
        return
    if args.command == "profile":
        from memesis.profiler.optimizer import PipelineOptimizer
        from memesis.profiler.pipeline_profiler import PipelineProfiler
        repository = _repository(args.database_url, initialize=True)
        seed_phase5_fixture(repository)
        profiler = PipelineProfiler(repository)
        print(f"Profiling: {args.question!r}")
        report = profiler.profile(args.question)
        if args.json_output:
            print(report.as_json())
        else:
            print(report.summary_table())
        if args.optimize:
            print("\nRunning optimizer comparison...")
            optimizer = PipelineOptimizer(repository)
            opt_report = optimizer.run(args.question)
            if args.json_output:
                print(opt_report.as_json())
            else:
                print(opt_report.summary())
        return
    if args.command == "evaluate-phase5":
        repository = _repository(args.database_url, initialize=True)
        report = evaluate_phase5(repository, output_path=REPO_ROOT / args.output)
        _print(report)
        return
    repository = _repository(args.database_url)

    if args.command == "health":
        _print(repository.health())
    elif args.command.startswith("create-"):
        node_type = {
            "create-person": "Person",
            "create-belief": "Belief",
            "create-content": "Content",
        }[args.command]
        node, evidence = _create_record(
            repository,
            node_type=node_type,
            name=args.name,
            source_url=args.source_url,
            text_content=args.text,
            source_type=args.source_type,
        )
        _print({"node": node, "evidence": evidence})
    elif args.command == "connect":
        evidence = repository.get_evidence(args.evidence_id)
        if evidence is None:
            raise SystemExit(f"unknown evidence id: {args.evidence_id}")
        knowledge = KnowledgeService(repository)
        edge = (
            knowledge.publish(args.from_id, args.to_id, evidence.id)
            if args.edge_type == "PUBLISHED"
            else knowledge.express(args.from_id, args.to_id, evidence.id)
        )
        _print(edge)
    elif args.command == "retrieve":
        _print(repository.retrieve_subgraph(args.seed_id, max_hops=args.hops))


if __name__ == "__main__":
    main()
