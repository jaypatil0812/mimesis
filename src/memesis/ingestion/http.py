"""Bounded HTTP client with rate limiting, retry/backoff, and durable cache hooks."""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

import httpx

from memesis.config import Settings
from memesis.graph.repository import GraphRepository


@dataclass(frozen=True)
class HttpResult:
    body: str
    status_code: int
    headers: dict[str, str]
    from_cache: bool
    request_count: int


class HostRateLimiter:
    """A small per-process host limiter; no queue/cache service is required in Phase 2."""

    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Lock] = {}
        self._last_request: dict[str, float] = {}

    async def wait(self, url: str, minimum_interval_seconds: float) -> None:
        host = urlsplit(url).netloc
        lock = self._locks.setdefault(host, asyncio.Lock())
        async with lock:
            now = asyncio.get_running_loop().time()
            delay = self._last_request.get(host, 0.0) + minimum_interval_seconds - now
            if delay > 0:
                await asyncio.sleep(delay)
            self._last_request[host] = asyncio.get_running_loop().time()


class ResilientHttpClient:
    def __init__(self, repository: GraphRepository, settings: Settings) -> None:
        self._repository = repository
        self._settings = settings
        self._limiter = HostRateLimiter()
        self._client = httpx.AsyncClient(
            timeout=settings.ingestion_request_timeout_seconds,
            headers={"User-Agent": settings.ingestion_user_agent},
            follow_redirects=True,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def get(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        min_interval_seconds: float = 0.25,
        cache_ttl_seconds: int | None = None,
    ) -> HttpResult:
        key_payload = json.dumps({"url": url, "params": params or {}}, sort_keys=True)
        cache_key = hashlib.sha256(key_payload.encode()).hexdigest()
        cached = self._repository.get_fetch_cache(cache_key)
        now = datetime.now(UTC)
        # SQLite returns stored datetimes without timezone information while
        # PostgreSQL preserves it. Treat legacy/SQLite values as UTC so the
        # durable response cache behaves identically in both supported local
        # development modes.
        cached_expires_at = cached and self._as_utc(cached["expires_at"])
        if cached and cached_expires_at and cached_expires_at > now:
            return HttpResult(
                body=str(cached["body"]),
                status_code=int(cached["status_code"]),
                headers={str(k): str(v) for k, v in dict(cached["headers"]).items()},
                from_cache=True,
                request_count=0,
            )

        conditional_headers = dict(headers or {})
        if cached:
            cached_headers = dict(cached["headers"])
            if cached_headers.get("etag"):
                conditional_headers["If-None-Match"] = str(cached_headers["etag"])
            if cached_headers.get("last-modified"):
                conditional_headers["If-Modified-Since"] = str(cached_headers["last-modified"])

        attempts = self._settings.ingestion_max_retries + 1
        for attempt in range(attempts):
            await self._limiter.wait(url, min_interval_seconds)
            try:
                response = await self._client.get(url, params=params, headers=conditional_headers)
                if response.status_code == 304 and cached:
                    expires_at = now + timedelta(
                        seconds=cache_ttl_seconds or self._settings.ingestion_cache_ttl_seconds
                    )
                    self._repository.save_fetch_cache(
                        cache_key,
                        status_code=int(cached["status_code"]),
                        body=str(cached["body"]),
                        headers=dict(cached["headers"]),
                        fetched_at=now,
                        expires_at=expires_at,
                    )
                    return HttpResult(
                        str(cached["body"]),
                        int(cached["status_code"]),
                        dict(cached["headers"]),
                        True,
                        1,
                    )
                if response.status_code == 429 or response.status_code >= 500:
                    response.raise_for_status()
                response.raise_for_status()
                headers_to_store = {
                    key.lower(): value
                    for key, value in response.headers.items()
                    if key.lower() in {"etag", "last-modified", "content-type"}
                }
                body = response.text
                self._repository.save_fetch_cache(
                    cache_key,
                    status_code=response.status_code,
                    body=body,
                    headers=headers_to_store,
                    fetched_at=now,
                    expires_at=now
                    + timedelta(
                        seconds=cache_ttl_seconds or self._settings.ingestion_cache_ttl_seconds
                    ),
                )
                return HttpResult(body, response.status_code, headers_to_store, False, 1)
            except (httpx.HTTPError, httpx.TimeoutException):
                if attempt == attempts - 1:
                    raise
                await asyncio.sleep(self._settings.ingestion_retry_backoff_seconds * (2**attempt))
        raise AssertionError("unreachable")

    @staticmethod
    def _as_utc(value: object) -> datetime:
        if not isinstance(value, datetime):
            raise TypeError("fetch cache expiry must be a datetime")
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
