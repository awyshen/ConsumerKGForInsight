"""Persist research conversations, analysis runs and evidence-grounded artifacts."""
from alembic import op
import sqlalchemy as sa

revision = "0002_analysis_agent"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade():
    # Initial V4 metadata bootstrap may already have created these on a fresh install.
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())
    if "analysis_sessions" not in existing:
        op.create_table("analysis_sessions",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("tenant_id", sa.String(80), nullable=False, index=True),
            sa.Column("title", sa.String(240), nullable=False),
            sa.Column("messages", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False))
    if "analysis_runs" not in existing:
        op.create_table("analysis_runs",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("tenant_id", sa.String(80), nullable=False, index=True),
            sa.Column("session_id", sa.String(36), sa.ForeignKey("analysis_sessions.id"), nullable=False, index=True),
            sa.Column("request_id", sa.String(80), nullable=False),
            sa.Column("question", sa.Text(), nullable=False),
            sa.Column("status", sa.String(20), nullable=False, index=True),
            sa.Column("trace", sa.JSON(), nullable=False),
            sa.Column("answer", sa.Text()), sa.Column("error", sa.Text()),
            sa.Column("model", sa.String(160), nullable=False),
            sa.Column("usage", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("finished_at", sa.DateTime(timezone=True)),
            sa.UniqueConstraint("session_id", "request_id"))
    if "insight_artifacts" not in existing:
        op.create_table("insight_artifacts",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("tenant_id", sa.String(80), nullable=False, index=True),
            sa.Column("session_id", sa.String(36), sa.ForeignKey("analysis_sessions.id"), nullable=False, index=True),
            sa.Column("run_id", sa.String(36), sa.ForeignKey("analysis_runs.id"), nullable=False, unique=True),
            sa.Column("title", sa.String(240), nullable=False),
            sa.Column("content", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))


def downgrade():
    for table in ("insight_artifacts", "analysis_runs", "analysis_sessions"):
        op.drop_table(table)
