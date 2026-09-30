"""One scheduled worker: collect, process, investigate, bounded follow-up and retry."""
import asyncio
import json
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4
from memesis.config import settings
from memesis.extraction.pipeline import EvidenceGraphReport
from memesis.extraction.rebuild import rebuild_evidence
from memesis.extraction.model import OpenAICompatibleStructuredExtractor
from memesis.extraction.contracts import EXTRACT_PROMPT_VERSION, AMBIGUITY_PROMPT_VERSION, DETERMINISTIC_VERSION
from memesis.ingestion.http import ResilientHttpClient
from memesis.ingestion.service import IngestionService, IngestionReport
from memesis.investigations.contracts import InvestigationConfig
from memesis.investigations.service import InvestigationService, digest, seal_packet
from memesis.sources.bluesky import BlueskyAdapter
from memesis.sources.hackernews import HackerNewsAdapter
from memesis.sources.openalex import OpenAlexAdapter, RESOURCE_TYPES
from memesis.sources.rss import RssAdapter
from memesis.sources.github import GitHubAdapter

class InvestigationWorker:
    def __init__(self, repository, store, *, adapter_factory=None, service=None):
        self.repository, self.store = repository, store
        self.owner = str(uuid4())
        self.http = None
        self.adapter_factory = adapter_factory or self.make_adapter
        self.service = service or InvestigationService(repository)

    def make_adapter(self, source):
        if source.source == "github":
            return GitHubAdapter(self.http)
        if source.source == "hackernews":
            return HackerNewsAdapter(self.http)
        if source.source == "bluesky":
            return BlueskyAdapter(self.http)
        if source.source == "openalex":
            return OpenAlexAdapter(self.http, settings)
        return RssAdapter(self.http, str(source.feed_url))

    @staticmethod
    def extraction_models():
        def configured(name, prompt):
            return OpenAICompatibleStructuredExtractor(base_url=settings.model_api_base_url,
                api_key=settings.model_api_key, model_name=name, prompt_version=prompt,
                timeout_seconds=settings.ingestion_request_timeout_seconds) if name and settings.model_api_key else None
        return (configured(settings.extract_small_model, EXTRACT_PROMPT_VERSION),
                configured(settings.resolve_small_model, AMBIGUITY_PROMPT_VERSION))

    async def heartbeat(self):
        while True:
            await asyncio.sleep(20)
            if not self.store.renew(self.owner):
                raise RuntimeError("Worker lease lost")

    async def tick(self):
        if not self.store.acquire(self.owner):
            return {"status": "another_worker_active", "jobs": []}
        pulse = asyncio.create_task(self.heartbeat())
        receipts = []
        self.http = ResilientHttpClient(self.repository, settings)
        try:
            # Oldest due jobs go first; a large watchlist cannot make one tick
            # unbounded or let recent jobs starve overdue investigations.
            for record in sorted(self.store.list(), key=lambda r: r["next_due_at"]):
                if len(receipts) >= 8:
                    break
                watch = self.store.claim(self.owner, record["id"])
                if watch is not None:
                    if pulse.done():
                        pulse.result()
                    receipts.append(await self.run_watch(watch))
            return {"status": "completed", "jobs": receipts}
        finally:
            pulse.cancel()
            await asyncio.gather(pulse, return_exceptions=True)
            await self.http.aclose()
            self.store.release(self.owner)

    async def collect_source(self, watch, source, config, namespace=""):
        cutoff = datetime.now(UTC) - timedelta(days=config.initial_lookback_days)
        initial = (str(int(cutoff.timestamp())) if source.source == "hackernews" else
                   cutoff.isoformat() if source.source == "bluesky" else
                   cutoff.strftime("%Y-%m-%dT%H:%M:%SZ") if source.source == "github" else
                   json.dumps({r: cutoff.date().isoformat() for r in RESOURCE_TYPES}) if source.source == "openalex" else None)
        adapter = self.adapter_factory(source)
        try:
            report = await IngestionService(self.repository).collect(adapter, source.query,
                limit=config.page_size, max_pages=config.max_pages_per_source,
                namespace=f"watch:{watch['id']}:{namespace}", initial_cursor=initial, lease_owner=self.owner)
        except Exception as error:
            report = IngestionReport(source_key=adapter.source.source_key, query=source.query,
                failures=[{"source": source.source, "error": type(error).__name__}])
        return {**report.as_metrics(), "source": source.source, "query": source.query}

    async def run_watch(self, watch):
        config = InvestigationConfig.model_validate(watch["config"])
        state = dict(watch["state"])
        state.pop("manual_requested", None)
        receipt = {"investigation_id": watch["id"], "status": "completed", "collection": [],
                   "followup_collection": [], "failures": [], "processing_version": config.processing_version}
        snapshot = None
        pending = list(state.get("pending_evidence_ids", []))
        tracked = list(state.get("tracked_evidence_ids", []))
        health = dict(state.get("source_health", {}))
        receipt_cursor = datetime.now(UTC).isoformat()
        for recovered in self.repository.collection_receipts(f"watch:{watch['id']}:", state.get("receipt_cursor")):
            for eid in recovered.get("evidence_ids", []):
                if eid not in tracked:
                    tracked.append(eid)
                    pending.append(eid)
        try:
            # Drain a growing backlog before collecting another batch; no IDs
            # disappear because an extraction budget was reached.
            if not pending:
                for source in config.sources:
                    key = digest(source.model_dump(mode="json"))
                    previous = health.get(key, {})
                    retry_at = previous.get("retry_at")
                    if retry_at and datetime.fromisoformat(retry_at) > datetime.now(UTC):
                        continue
                    report = await self.collect_source(watch, source, config)
                    receipt["collection"].append(report)
                    for eid in report["evidence_ids"]:
                        if eid not in tracked:
                            tracked.append(eid)
                            pending.append(eid)
                    attempts = previous.get("consecutive_failures", 0) + 1 if report["failures"] else 0
                    health[key] = {"source": source.source, "query": source.query,
                        "last_attempt_at": datetime.now(UTC).isoformat(), "consecutive_failures": attempts,
                        "last_completed_scan_at": datetime.now(UTC).isoformat() if report["pagination_complete"] and not report["failures"] else previous.get("last_completed_scan_at"),
                        "pagination_complete": report["pagination_complete"], "failures": report["failures"],
                        "coverage_notes": report["coverage_notes"],
                        "retry_at": (datetime.now(UTC) + timedelta(seconds=min(30 * 2 ** min(attempts, 5), config.interval_seconds))).isoformat() if attempts else None}
                    receipt["failures"].extend(report["failures"])
            if state.get("extractor_version") != DETERMINISTIC_VERSION:
                pending = list(dict.fromkeys(pending + tracked))
                state["extractor_version"] = DETERMINISTIC_VERSION
            processing_ids = list(dict.fromkeys(pending))[:config.max_evidence_per_tick]
            cheap, resolver = self.extraction_models()
            receipt["processing_models"] = [m.model_name for m in (cheap, resolver) if m is not None]
            def fence(atomic):
                with atomic.session_factory() as session:
                    self.store.fenced(session, self.owner)
            rebuilt = await rebuild_evidence(self.repository, [UUID(eid) for eid in processing_ids],
                interpretation_version=config.processing_version, cheap_model=cheap,
                ambiguity_model=resolver, fence_record=fence)
            receipt["memory_rebuild"] = rebuilt
            processed = EvidenceGraphReport()
            for item in rebuilt["records"]:
                if item["status"] == "failed":
                    processed.failures.append({"evidence_id": item["evidence_id"], "error": item["error"]})
                else:
                    for key, value in item.get("processing", {}).items():
                        if key != "failures":
                            setattr(processed, key, getattr(processed, key) + value)
            failed_ids = {f["evidence_id"] for f in processed.failures}
            dead = dict(state.get("dead_letters", {}))
            attempts = dict(state.get("extraction_attempts", {}))
            for eid in failed_ids:
                attempts[eid] = attempts.get(eid, 0) + 1
                if attempts[eid] >= 3:
                    dead[eid] = {"attempts": attempts[eid], "processing_version": config.processing_version,
                                 "error": next(f["error"] for f in processed.failures if f["evidence_id"] == eid)}
            completed = set(processing_ids) - failed_ids
            pending = [eid for eid in pending if eid not in completed and eid not in dead]
            receipt["extraction"] = processed.as_metrics()
            receipt["failures"].extend(processed.failures)
            seed_budget = config.max_evidence_per_tick * 4
            packet = await asyncio.to_thread(self.service.context, config, tracked[-seed_budget:] if config.sources else None)
            packet.coverage["tracked_collection_evidence_count"] = len(tracked)
            packet.coverage["research_seed_budget"] = seed_budget
            if len(tracked) > seed_budget:
                packet.missing_information.append(f"Research roots retained the latest {seed_budget} of {len(tracked)} collected records; older evidence is reachable only through bounded graph paths.")
            seal_packet(packet)
            fingerprint = self.service.fingerprint(packet, config)
            previous = self.store.history(watch["id"], 1)
            if fingerprint != state.get("last_fingerprint"):
                snapshot = await asyncio.to_thread(self.service.investigate, config, packet, previous[0] if previous else None)
                state["last_fingerprint"] = fingerprint
                state["last_analysis_at"] = datetime.now(UTC).isoformat()
                state["last_patterns"] = snapshot["patterns"]
                if not previous or any(r["normalized_evidence_emitted"] for r in receipt["collection"]):
                    state["rounds_remaining"] = config.max_investigation_rounds
            else:
                receipt["analysis"] = "unchanged_scoped_evidence_and_interpretation; previous snapshot retained"
            # Follow-ups are an explicit finite cycle. Source list is an
            # allowlist; model recommendations cannot introduce new adapters.
            executed = list(state.get("executed_followups", []))
            latest_reviews = {r["pattern_id"]: r["state"] for r in self.store.reviews(watch["id"])}
            rounds = state.get("rounds_remaining", 0)
            if rounds > 0 and not pending:
                for pattern in state.get("last_patterns", []):
                    step = pattern.get("next_investigation")
                    if not step or pattern["id"] in executed or latest_reviews.get(pattern["id"]) == "rejected":
                        continue
                    sources = [s for s in config.sources if s.source == step["source"]]
                    if not sources:
                        continue
                    if len(receipt["followup_collection"]) >= config.max_followups_per_cycle:
                        break
                    source = sources[0].model_copy(update={"query": step["query"]})
                    report = await self.collect_source(watch, source, config, namespace="followup:" + pattern["id"] + ":")
                    receipt["followup_collection"].append({**report, "pattern_id": pattern["id"], "question": step["question"]})
                    for eid in report["evidence_ids"]:
                        if eid not in tracked:
                            tracked.append(eid)
                            pending.append(eid)
                    receipt["failures"].extend(report["failures"])
                    if report["pagination_complete"] and not report["failures"]:
                        executed.append(pattern["id"])
                state["rounds_remaining"] = rounds - 1
            scoped = {e["id"] for e in packet.primary_evidence_references}
            receipt["collected_outside_retained_scope"] = len(set(tracked) - scoped)
            receipt["followup_rounds_remaining"] = state.get("rounds_remaining", 0)
            receipt["followup_budget_exhausted"] = state.get("rounds_remaining", 0) == 0
            receipt["scope_semantics"] = "Search results are research candidates. Collection does not automatically assign them to a market."
            if state.get("projection_review_required"):
                receipt["projection_review_required"] = True
                receipt["rebuild_semantics"] = "Re-extraction preserves previous assertions; obsolete accepted projections require review, not silent replacement."
            if receipt["failures"] or dead:
                receipt["status"] = "partial"
            elif any(not report["pagination_complete"] for report in receipt["collection"] + receipt["followup_collection"]):
                receipt["status"] = "continuing"
            if snapshot:
                receipt["reasoning_execution"] = snapshot["reasoning_execution"]
                if snapshot["reasoning_execution"].get("status") in {"provider_failed", "invalid_response", "packet_too_large"}:
                    receipt["status"] = "partial"
                    # Failed reasoning should be retried even if data stays stable.
                    state.pop("last_fingerprint", None)
            state.update(pending_evidence_ids=pending, tracked_evidence_ids=tracked, source_health=health,
                         receipt_cursor=receipt_cursor,
                         extraction_attempts=attempts, dead_letters=dead, executed_followups=executed,
                         last_run_at=datetime.now(UTC).isoformat(), last_run_status=receipt["status"])
        except Exception as error:
            receipt["status"] = "failed"
            receipt["failures"].append({"error": type(error).__name__})
            state.update(pending_evidence_ids=pending, tracked_evidence_ids=tracked, source_health=health,
                         last_run_at=datetime.now(UTC).isoformat(), last_run_status="failed")
        delay = 60 if pending or state.get("rounds_remaining", 0) > 0 or any(not h.get("pagination_complete") for h in health.values()) else config.interval_seconds
        if receipt["status"] in {"partial", "failed"}:
            count = state.get("job_retry_count", 0) + 1
            state["job_retry_count"] = count
            delay = min(60 * 2 ** min(count, 6), config.interval_seconds)
        else:
            state["job_retry_count"] = 0
        self.store.complete(self.owner, watch, state, receipt, snapshot, delay)
        return receipt

    async def serve(self, poll_seconds=30):
        while True:
            await self.tick()
            await asyncio.sleep(poll_seconds)
