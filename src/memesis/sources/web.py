"""Policy-gated normal web-page collection via Crawl4AI."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser
from uuid import UUID

from crawl4ai import AsyncWebCrawler, BrowserConfig, CacheMode, CrawlerRunConfig

from memesis.domain.schemas import Source, SourcePolicy
from memesis.ingestion.contracts import CollectedDocument, CollectionBatch
from memesis.ingestion.http import ResilientHttpClient
from memesis.ingestion.normalizer import normalize_text, sha256_text


class WebPageAdapter:
    """Fetch one user-approved URL after a robots.txt allow check.

    Crawl4AI owns rendering/extraction. The ordinary HTTP client is used only
    for robots.txt, so standard HTTP page content is never silently substituted
    for a browser-rendered Crawl4AI result.
    """

    def __init__(self, http: ResilientHttpClient, url: str) -> None:
        self._http = http
        self._url = url
        parsed = urlsplit(url)
        self._origin = f"{parsed.scheme}://{parsed.netloc}"
        self._source = Source(
            source_key=f"web:{parsed.netloc}",
            source_type="web",
            base_url=self._origin,
            metadata={"robots_required": True, "collector": "crawl4ai"},
        )

    @property
    def source(self) -> Source:
        return self._source

    def source_policy(self, source_id: UUID) -> SourcePolicy:
        return SourcePolicy(
            source_id=source_id,
            terms_url=urljoin(self._origin, "/robots.txt"),
            reviewed_at=datetime.now(UTC),
            active=True,
            policy={
                "access_method": "crawl4ai_after_robots_allow",
                "robots_required": True,
                "rate_limit_per_minute": 10,
                "collection": "public_page_text_only",
                "llm_collection": False,
            },
        )

    async def collect(self, query: str, *, cursor: str | None, limit: int) -> CollectionBatch:
        # A URL checkpoint never means the page will remain unchanged. The
        # worker schedules revisits; legacy URL hashes are deliberately ignored.
        allowed, request_count, cache_hits = await self._robots_allows()
        if not allowed:
            return CollectionBatch(
                [],
                cursor,
                request_count,
                cache_hits,
                [{"source": self._url, "error": "robots_disallow"}],
            )
        # Browser-level caching avoids repeat rendering. Content hashing at
        # the ledger boundary independently prevents repeat normalization.
        config = CrawlerRunConfig(cache_mode=CacheMode.BYPASS)
        browser = BrowserConfig(headless=True)
        async with AsyncWebCrawler(config=browser) as crawler:
            result = await crawler.arun(url=self._url, config=config)
        if not result.success:
            return CollectionBatch(
                [],
                cursor,
                request_count,
                cache_hits,
                [{"source": self._url, "error": str(result.error_message or "crawl_failed")}],
            )
        markdown = getattr(result, "markdown", "")
        if not isinstance(markdown, str):
            markdown = getattr(markdown, "raw_markdown", "") or str(markdown)
        text = normalize_text(markdown)
        if not text:
            return CollectionBatch(
                [],
                cursor,
                request_count,
                cache_hits,
                [{"source": self._url, "error": "empty_crawl"}],
            )
        raw = json.dumps({"url": self._url, "markdown": markdown}, sort_keys=True)
        document = CollectedDocument(
            external_id=self._url,
            canonical_url=self._url,
            source_url=self._url,
            source_type="web",
            raw_payload=raw,
            text=text,
            original_reference=text[:280],
            retrieved_at=datetime.now(UTC),
            content_type="text/markdown",
            metadata={"collector": "crawl4ai", "query": query, "robots_allowed": True,
                      "fresh_browser_fetch": True, "checked_at": datetime.now(UTC).isoformat()},
        )
        checkpoint = json.dumps({"version": "web-content-v1", "url": self._url,
            "content_hash": sha256_text(text), "checked_at": datetime.now(UTC).isoformat()}, sort_keys=True)
        return CollectionBatch([document], checkpoint, request_count + 1, cache_hits,
            coverage_notes=["Fresh rendered page fetch; ledger content hashes suppress unchanged processing. Only the configured URL was checked."])

    async def _robots_allows(self) -> tuple[bool, int, int]:
        robots_url = urljoin(self._origin, "/robots.txt")
        try:
            response = await self._http.get(
                robots_url, min_interval_seconds=1.0, cache_ttl_seconds=3600
            )
        except Exception as e:
            # 404 on robots.txt means no restrictions exist; allow crawl
            status_code = getattr(getattr(e, "response", None), "status_code", None)
            if status_code == 404:
                return True, 1, 0
            # For network connectivity errors, fail closed
            return False, 1, 0

        parser = RobotFileParser()
        parser.parse(response.body.splitlines())
        return parser.can_fetch("Memesis", self._url), response.request_count, int(response.from_cache)
