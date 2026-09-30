"""Public GitHub issue/PR text as attributable evidence, not adoption proof."""
import json
from datetime import UTC, datetime
from uuid import UUID
from memesis.domain.schemas import Source, SourcePolicy
from memesis.ingestion.contracts import CollectedDocument, CollectionBatch
from memesis.ingestion.normalizer import normalize_text
from memesis.sources.base import active_api_policy


class GitHubAdapter:
    def __init__(self, http):
        self._http = http
        self._source = Source(source_key="github:public-issues", source_type="github",
            base_url="https://api.github.com", terms_url="https://docs.github.com/en/rest/search/search",
            metadata={"collection": "issue_and_pr_title_body", "comments_collected": False})

    @property
    def source(self):
        return self._source

    def source_policy(self, source_id: UUID) -> SourcePolicy:
        return active_api_policy(source_id, self.source.terms_url, rate_limit=10)

    async def collect(self, query, *, cursor, limit):
        # Require a public repository boundary; the worker never uses local gh
        # credentials or broadens collection to a user's private repositories.
        if "repo:" not in query:
            raise ValueError("GitHub collection requires a repo:owner/name boundary")
        state = json.loads(cursor) if cursor and cursor.startswith("{") else {
            "since": cursor or "1970-01-01T00:00:00Z", "until": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), "page": 1}
        size = min(limit, 100)
        result = await self._http.get("https://api.github.com/search/issues",
            params={"q": f"{query} updated:{state['since']}..{state['until']}",
                "sort": "updated", "order": "asc", "per_page": size, "page": state["page"]},
            headers={"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"},
            min_interval_seconds=6.5)
        payload = json.loads(result.body)
        documents = []
        for item in payload.get("items", []):
            if not item.get("id") or not item.get("html_url"):
                continue
            author = item.get("user") or {}
            text = normalize_text(f"{item.get('title', '')}\n{item.get('body') or ''}")
            documents.append(CollectedDocument(external_id=str(item["id"]), canonical_url=item["html_url"],
                source_url=item["html_url"], source_type="github", raw_payload=json.dumps(item, sort_keys=True),
                text=text, original_reference=item.get("title", ""), retrieved_at=datetime.now(UTC),
                published_at=datetime.fromisoformat(item["created_at"].replace("Z", "+00:00")),
                updated_at=datetime.fromisoformat(item["updated_at"].replace("Z", "+00:00")), content_type="application/json",
                metadata={"query": query, "repository_url": item.get("repository_url"),
                    "github_issue_id": item["id"], "number": item.get("number"), "state": item.get("state"),
                    "author_handle": author.get("login"), "author_github_id": author.get("id"),
                    "author_profile_url": author.get("html_url"), "is_pull_request": "pull_request" in item,
                    "comments_count": item.get("comments"), "comments_collected": False}))
        total = int(payload.get("total_count", 0))
        complete = state["page"] * size >= total or not payload.get("items")
        failures = []
        if payload.get("incomplete_results") or total > 1000:
            failures.append({"source": "github", "error": "incomplete_or_capped_search; narrow repository/query/date window"})
        state["page"] += 1
        return CollectionBatch(documents, state["until"], result.request_count, int(result.from_cache), failures,
            complete=complete, continuation_cursor=json.dumps(state),
            coverage_notes=["Only issue/PR titles and bodies are collected; comments and releases are not included.",
                "Search results can shift during pagination; inclusive overlap and hashes absorb duplicates but do not prove completeness.",
                "Issue reports are attributable experiences or requests, not representative demand or verified defects."])
