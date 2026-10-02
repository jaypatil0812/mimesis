"""Create an isolated cross-market review workspace; optional bounded public collection.

Never changes the preview database or marks an assistant review as human approval.
Run with --collect to execute one bounded scan per non-AI question. Provider
reasoning/extraction calls are disabled for this preparation run.
"""
import argparse
import asyncio
import json
from pathlib import Path
from memesis.config import settings
from memesis.db.session import make_engine, initialize_schema, make_session_factory
from memesis.graph.sql_repository import SqlGraphRepository
from memesis.investigations.contracts import InvestigationConfig
from memesis.investigations.store import InvestigationStore
from memesis.investigations.templates import templates
from memesis.investigations.worker import InvestigationWorker


async def prepare(output_dir, collect):
    directory = Path(output_dir).resolve()
    directory.mkdir(parents=True, exist_ok=False)
    database = directory / "review.sqlite3"
    settings.model_api_key = settings.typesafe_api_key = settings.openrouter_api_key = None
    settings.decision_engine = "heuristic"
    engine = make_engine("sqlite:///" + database.as_posix())
    try:
        initialize_schema(engine)
        repository = SqlGraphRepository(make_session_factory(engine))
        store = InvestigationStore(repository.session_factory)
        watches = []
        for config in templates():
            config.update(page_size=5, max_pages_per_source=1, max_evidence_per_tick=20,
                          max_followups_per_cycle=0, max_investigation_rounds=0, enabled=False)
            record = store.create(InvestigationConfig.model_validate(config))
            watches.append(record)
            if collect and config["sources"]:
                store.request_run(record["id"])
        receipt = await InvestigationWorker(repository, store).tick() if collect else None
        bundle = {"human_review_status": "pending", "customer_validation": None,
            "provider_reasoning": "disabled_for_preparation", "database": str(database),
            "collection_receipt": receipt, "investigations": [{**store.get(w["id"]),
                "snapshots": store.history(w["id"]), "runs": store.runs(w["id"])} for w in watches]}
        (directory / "investigations.json").write_text(json.dumps(bundle, indent=2, default=str), encoding="utf-8")
        (directory / "reviews.json").write_text(json.dumps({"status": "pending", "reviews": [
            {"investigation_id": watch["id"], "reviewer": None, "decision_before": "", "decision_after": "",
             "extraction": "pending", "counterevidence": "pending", "reasoning_support": "pending",
             "usefulness": "pending", "note": ""} for watch in watches]}, indent=2), encoding="utf-8")
        print(json.dumps({"output_dir": str(directory), "watchlists": len(watches), "human_review_status": "pending",
            "collection_status": receipt["status"] if receipt else "not_requested",
            "jobs": [{"status": r["status"], "failures": r["failures"]} for r in (receipt or {}).get("jobs", [])]}, indent=2))
    finally:
        engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--collect", action="store_true")
    args = parser.parse_args()
    asyncio.run(prepare(args.output_dir, args.collect))
