"""Add replayable deterministic score records."""

from alembic import op

from memesis.db.models import Base

revision = "0004_deterministic_scores"
down_revision = "0003_evidence_graph"
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.tables["score_record"].create(bind=op.get_bind(), checkfirst=True)


def downgrade() -> None:
    Base.metadata.tables["score_record"].drop(bind=op.get_bind(), checkfirst=True)
