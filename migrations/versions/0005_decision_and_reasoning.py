"""Add decision cache and reasoning run tables."""

from alembic import op

from memesis.db.models import Base

revision = "0005_decision_and_reasoning"
down_revision = "0004_deterministic_scores"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.tables["decision_cache"].create(bind=bind, checkfirst=True)
    Base.metadata.tables["reasoning_run"].create(bind=bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.tables["reasoning_run"].drop(bind=bind, checkfirst=True)
    Base.metadata.tables["decision_cache"].drop(bind=bind, checkfirst=True)
