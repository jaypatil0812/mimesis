import asyncio
import json

import httpx
from alembic import command
from alembic.config import Config
from sqlalchemy import create_mock_engine, inspect

from memesis.app import create_app
from memesis.cli import main
from memesis.config import settings
from memesis.db.models import Base
from memesis.db.session import make_engine


def test_health_endpoint_checks_database(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'health.sqlite3'}"
    engine = make_engine(database_url)
    from memesis.db.session import initialize_schema

    initialize_schema(engine)

    async def get_health():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(database_url)),
            base_url="http://test",
        ) as client:
            return await client.get("/healthz")

    response = asyncio.run(get_health())
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    engine.dispose()


def test_initial_migration_creates_phase_one_tables(tmp_path, monkeypatch):
    database_url = f"sqlite:///{tmp_path / 'migration.sqlite3'}"
    monkeypatch.setattr(settings, "database_url", database_url)
    config = Config("alembic.ini")
    command.upgrade(config, "head")
    engine = make_engine(database_url)
    tables = set(inspect(engine).get_table_names())
    assert {
        "source",
        "source_policy",
        "document",
        "document_version",
        "normalized_document",
        "evidence",
        "evidence_span",
        "assertion",
        "graph_node",
        "graph_edge",
        "merge_decision",
        "tombstone",
        "entity_alias",
        "entity_external_identifier",
        "extraction_cache",
        "evidence_graph_projection",
        "score_record",
    } <= tables
    engine.dispose()


def test_postgresql_ddl_compiles_without_a_server():
    statements = []
    engine = create_mock_engine(
        "postgresql+psycopg://",
        lambda statement, *args, **kwargs: statements.append(
            str(statement.compile(dialect=engine.dialect))
        ),
    )
    Base.metadata.create_all(engine)
    assert any("CREATE TABLE graph_edge" in statement for statement in statements)
    assert any("CREATE TABLE evidence" in statement for statement in statements)


def test_cli_demo_creates_and_retrieves_provenance_graph(tmp_path, monkeypatch, capsys):
    database_url = f"sqlite:///{tmp_path / 'demo.sqlite3'}"
    monkeypatch.setattr("sys.argv", ["memesis", "demo", "--database-url", database_url])
    main()
    result = json.loads(capsys.readouterr().out)
    assert result["provenance_round_trip"] is True
    assert {node["node_type"] for node in result["subgraph"]["nodes"]} == {
        "Person",
        "Belief",
        "Content",
    }
    assert {edge["edge_type"] for edge in result["subgraph"]["edges"]} == {
        "PUBLISHED",
        "EXPRESSES",
    }
    assert result["subgraph"]["evidence"][0]["source_url"].startswith("https://")
