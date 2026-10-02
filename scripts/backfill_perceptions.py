"""Rebuild preserved evidence into reviewable perception candidates, not facts."""
import asyncio
import json
from memesis.config import settings
from memesis.db.session import make_engine, make_session_factory
from memesis.graph.sql_repository import SqlGraphRepository
from memesis.extraction.rebuild import rebuild_evidence
from memesis.investigations.store import InvestigationStore
from memesis.investigations.worker import InvestigationWorker


def backfill():
    engine = make_engine(settings.database_url)
    try:
        repo = SqlGraphRepository(make_session_factory(engine))
        small, strong = InvestigationWorker.extraction_models()
        receipt = asyncio.run(rebuild_evidence(repo, [e.id for e in repo.list_evidence()],
            cheap_model=small, ambiguity_model=strong))
        changed = [r["evidence_id"] for r in receipt["records"] if r["status"] == "rebuilt"]
        receipt["affected_investigations"] = InvestigationStore(repo.session_factory).invalidate_evidence(changed, receipt["id"])
        print(json.dumps(receipt, indent=2, default=str))
    finally:
        engine.dispose()


if __name__ == "__main__":
    backfill()
