"""Initial control plane; diagnostic jobs precede the ML run matrix."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "experiments",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("spec", postgresql.JSONB(), nullable=False),
        sa.Column("config_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("cancel_requested_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "idempotency_records",
        sa.Column("key", sa.String(128), primary_key=True),
        sa.Column("config_hash", sa.String(64), nullable=False),
        sa.Column("experiment_id", sa.Uuid(), sa.ForeignKey("experiments.id"), nullable=False),
    )
    op.create_table(
        "jobs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "experiment_id", sa.Uuid(), sa.ForeignKey("experiments.id"), nullable=False, unique=True
        ),
        sa.Column("state", sa.String(24), nullable=False),
        sa.Column("owner", sa.String(64)),
        sa.Column("token", sa.Integer(), nullable=False),
        sa.Column("lease_until", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_jobs_state_created", "jobs", ["state", "created_at"])
    op.create_table(
        "attempts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("job_id", sa.Uuid(), sa.ForeignKey("jobs.id"), nullable=False),
        sa.Column("token", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("error_code", sa.Text()),
        sa.Column("result", postgresql.JSONB()),
        sa.UniqueConstraint("job_id", "token"),
    )
    op.create_table(
        "benchmark_slots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("state", sa.String(24), nullable=False),
        sa.Column("job_id", sa.Uuid(), sa.ForeignKey("jobs.id")),
        sa.Column("token", sa.Integer()),
    )
    op.execute("INSERT INTO benchmark_slots(id, state) VALUES (1, 'available')")


def downgrade():
    for table in ("benchmark_slots", "attempts", "jobs", "idempotency_records", "experiments"):
        op.drop_table(table)
