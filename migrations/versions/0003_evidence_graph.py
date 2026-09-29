"""Add Phase 3 extraction lineage and identity indexes."""

from alembic import op
from sqlalchemy import Column, String, inspect

from memesis.db.models import Base

revision = "0003_evidence_graph"
down_revision = "0002_evidence_ingestion"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    for name in (
        "entity_alias",
        "entity_external_identifier",
        "extraction_cache",
        "evidence_graph_projection",
    ):
        Base.metadata.tables[name].create(bind=bind, checkfirst=True)
    columns = {column["name"] for column in inspect(bind).get_columns("assertion")}
    if "prompt_version" not in columns:
        op.add_column("assertion", Column("prompt_version", String(120), nullable=True))
    if "schema_version" not in columns:
        op.add_column(
            "assertion",
            Column("schema_version", String(80), nullable=False, server_default="phase3-v1"),
        )


def downgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in inspect(bind).get_columns("assertion")}
    if "schema_version" in columns:
        op.drop_column("assertion", "schema_version")
    if "prompt_version" in columns:
        op.drop_column("assertion", "prompt_version")
    for name in (
        "evidence_graph_projection",
        "extraction_cache",
        "entity_external_identifier",
        "entity_alias",
    ):
        Base.metadata.tables[name].drop(bind=bind, checkfirst=True)
