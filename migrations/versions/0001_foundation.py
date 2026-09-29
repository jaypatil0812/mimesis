"""Create Memesis evidence and graph foundation."""

from alembic import op

from memesis.db.models import Base

revision = "0001_foundation"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Keep the first migration bounded even as later model classes are added.
    for name in (
        "source",
        "source_policy",
        "document",
        "document_version",
        "normalized_document",
        "evidence_span",
        "assertion",
        "merge_decision",
        "tombstone",
        "evidence",
        "graph_node",
        "graph_edge",
        "graph_revision",
    ):
        Base.metadata.tables[name].create(bind=op.get_bind(), checkfirst=True)


def downgrade() -> None:
    for name in (
        "graph_revision",
        "graph_edge",
        "graph_node",
        "evidence",
        "tombstone",
        "merge_decision",
        "assertion",
        "evidence_span",
        "normalized_document",
        "document_version",
        "document",
        "source_policy",
        "source",
    ):
        Base.metadata.tables[name].drop(bind=op.get_bind(), checkfirst=True)
