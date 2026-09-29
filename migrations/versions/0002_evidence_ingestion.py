"""Add durable runs, checkpoints, and response cache for Phase 2 collection."""

from alembic import op

from memesis.db.models import Base

revision = "0002_evidence_ingestion"
down_revision = "0001_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for name in ("collection_run", "collection_cursor", "fetch_cache"):
        Base.metadata.tables[name].create(bind=op.get_bind(), checkfirst=True)


def downgrade() -> None:
    for name in ("fetch_cache", "collection_cursor", "collection_run"):
        Base.metadata.tables[name].drop(bind=op.get_bind(), checkfirst=True)
