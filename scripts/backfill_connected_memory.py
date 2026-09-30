"""Add reviewable memory candidates to stored evidence, retaining the original ledger."""

import json
from pathlib import Path

from memesis.config import settings
from memesis.db.session import make_engine, make_session_factory
from memesis.graph.sql_repository import SqlGraphRepository
from memesis.knowledge.memory import ConnectedMarketMemory


def main():
    repository = SqlGraphRepository(make_session_factory(make_engine(settings.database_url)))
    before = len(repository.list_memory_assertions())
    receipt = ConnectedMarketMemory(repository).backfill()
    receipt["observations_before"] = before
    receipt["observations_after"] = len(repository.list_memory_assertions())
    receipt["observations_added"] = receipt["observations_after"] - before
    destination = Path("data/evaluation/connected_memory_backfill.json")
    destination.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
