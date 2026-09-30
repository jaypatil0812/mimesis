"""Persistent investigations, immutable analysis snapshots, reviews and worker lease."""
from alembic import op
from memesis.db.models import Base
revision = "0006_investigations"
down_revision = "0005_decision_and_reasoning"
branch_labels = depends_on = None
TABLES = ("investigation", "investigation_run", "investigation_snapshot", "pattern_review", "worker_lease")
def upgrade():
    for name in TABLES:
        Base.metadata.tables[name].create(op.get_bind(), checkfirst=True)
def downgrade():
    for name in reversed(TABLES):
        Base.metadata.tables[name].drop(op.get_bind(), checkfirst=True)
