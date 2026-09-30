"""Real Public Data Ingestion Runner for Phase 9: AI Inference / Small Specialized Models.

Ingests 500-2,000 real public evidence items from:
- Hacker News (Algolia API)
- OpenAlex (Scholarly Works API)
- Bluesky (Public Posts API)
- RSS Feeds (Technical blogs: Simon Willison, Hugging Face)

Then runs EvidenceGraphPipeline to extract entities, beliefs, perceptions, and build the graph.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from datetime import datetime, UTC

from memesis.config import settings
from memesis.db.session import initialize_schema, make_engine, make_session_factory
from memesis.extraction.pipeline import EvidenceGraphPipeline
from memesis.graph.sql_repository import SqlGraphRepository
from memesis.ingestion.http import ResilientHttpClient
from memesis.ingestion.service import IngestionService
from memesis.sources.bluesky import BlueskyAdapter
from memesis.sources.hackernews import HackerNewsAdapter
from memesis.sources.openalex import OpenAlexAdapter
from memesis.sources.rss import RssAdapter

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("ingest_real_corpus")

HN_QUERIES = [
    "small language models",
    "SLM inference",
    "specialized models",
    "vLLM",
    "Ollama",
    "quantized models",
    "speculative decoding",
    "local LLM",
    "Mistral 7B",
    "Phi-3",
    "Llama 3 8B",
    "model routing",
    "inference cost",
    "Together AI inference",
    "Groq LPU",
    "Fireworks AI",
    "DeepSeek-V2",
    "distillation LLM",
    "TensorRT-LLM",
    "Apple MLX",
]

OPENALEX_QUERIES = [
    "small language models inference",
    "model distillation large language models",
    "quantization inference optimization",
    "speculative decoding language models",
    "mixture of experts inference serving",
    "edge AI small models",
    "parameter efficient fine-tuning inference",
]

BLUESKY_QUERIES = [
    "small models inference",
    "local LLM",
    "vLLM",
    "Ollama",
    "quantization",
    "SLM",
]

RSS_FEEDS = [
    ("simonwillison", "https://simonwillison.net/atom/everything/"),
    ("huggingface", "https://huggingface.co/blog/feed.xml"),
]


async def run_ingestion():
    logger.info("Initializing database and repository...")
    engine = make_engine(settings.database_url)
    initialize_schema(engine)
    session_factory = make_session_factory(engine)
    repo = SqlGraphRepository(session_factory)
    http = ResilientHttpClient(repo, settings)
    service = IngestionService(repo)

    total_persisted = 0
    breakdown: dict[str, int] = {}

    try:
        # 1. Hacker News
        logger.info("Starting Hacker News collection...")
        hn_adapter = HackerNewsAdapter(http)
        hn_count = 0
        for q in HN_QUERIES:
            try:
                report = await service.collect(hn_adapter, q, limit=40)
                hn_count += report.documents_persisted
                logger.info(f"HN query '{q}': fetched {report.documents_fetched}, persisted {report.documents_persisted}")
            except Exception as e:
                logger.warning(f"Failed HN query '{q}': {e}")
        breakdown["hackernews"] = hn_count
        total_persisted += hn_count

        # 2. OpenAlex
        logger.info("Starting OpenAlex collection...")
        oa_adapter = OpenAlexAdapter(http, settings=settings)
        oa_count = 0
        for q in OPENALEX_QUERIES:
            try:
                report = await service.collect(oa_adapter, q, limit=25)
                oa_count += report.documents_persisted
                logger.info(f"OpenAlex query '{q}': fetched {report.documents_fetched}, persisted {report.documents_persisted}")
            except Exception as e:
                logger.warning(f"Failed OpenAlex query '{q}': {e}")
        breakdown["openalex"] = oa_count
        total_persisted += oa_count

        # 3. Bluesky
        logger.info("Starting Bluesky collection...")
        bsky_adapter = BlueskyAdapter(http)
        bsky_count = 0
        for q in BLUESKY_QUERIES:
            try:
                report = await service.collect(bsky_adapter, q, limit=25)
                bsky_count += report.documents_persisted
                logger.info(f"Bluesky query '{q}': fetched {report.documents_fetched}, persisted {report.documents_persisted}")
            except Exception as e:
                logger.warning(f"Failed Bluesky query '{q}': {e}")
        breakdown["bluesky"] = bsky_count
        total_persisted += bsky_count

        # 4. RSS Feeds
        logger.info("Starting RSS collection...")
        rss_count = 0
        for key, feed_url in RSS_FEEDS:
            try:
                rss_adapter = RssAdapter(http, feed_url=feed_url)
                report = await service.collect(rss_adapter, f"feed:{key}", limit=30)
                rss_count += report.documents_persisted
                logger.info(f"RSS feed '{key}': fetched {report.documents_fetched}, persisted {report.documents_persisted}")
            except Exception as e:
                logger.warning(f"Failed RSS feed '{key}': {e}")
        breakdown["rss"] = rss_count
        total_persisted += rss_count

        logger.info(f"Ingestion complete. Total new evidence persisted: {total_persisted}")
        logger.info(f"Source breakdown: {breakdown}")

        # Check total evidence in database
        total_in_db = len(repo.list_evidence())
        logger.info(f"Total evidence in database: {total_in_db}")

        # 5. Graph Extraction & Projection
        logger.info("Running EvidenceGraphPipeline to extract entities, beliefs, perceptions, and project graph...")
        pipeline = EvidenceGraphPipeline(repo)
        graph_report = await pipeline.run(limit=None)
        logger.info(
            f"Graph Pipeline complete: processed {graph_report.evidence_processed} items, "
            f"entities resolved: {graph_report.entities_resolved}, "
            f"beliefs resolved: {graph_report.beliefs_resolved}, "
            f"assertions: {graph_report.assertions_written}, "
            f"edges: {graph_report.edges_written}"
        )

        # Count perceptions
        perceptions = repo.list_perceptions()
        logger.info(f"Total perceptions in database: {len(perceptions)}")

    finally:
        await http.aclose()


if __name__ == "__main__":
    asyncio.run(run_ingestion())
