"""Versioned datasets and benchmark matrix."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "datasets",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("spec", JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_table(
        "dataset_versions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("dataset_id", sa.Uuid(), sa.ForeignKey("datasets.id"), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("manifest", JSONB()),
        sa.Column("error_code", sa.Text()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_table(
        "comparison_cases",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("experiment_id", sa.Uuid(), sa.ForeignKey("experiments.id"), nullable=False),
        sa.Column("case_index", sa.Integer(), nullable=False),
        sa.Column("config", JSONB(), nullable=False),
        sa.Column("prepared", JSONB()),
        sa.UniqueConstraint("experiment_id", "case_index"),
    )
    op.create_table(
        "runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("case_id", sa.Uuid(), sa.ForeignKey("comparison_cases.id"), nullable=False),
        sa.Column("backend", sa.String(16), nullable=False),
        sa.Column("repeat_index", sa.Integer(), nullable=False),
        sa.Column("warmup", sa.Boolean(), nullable=False),
        sa.Column("pair_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("result", JSONB()),
        sa.UniqueConstraint("case_id", "backend", "repeat_index", "warmup"),
    )
    op.drop_constraint("jobs_experiment_id_key", "jobs", type_="unique")
    op.alter_column("jobs", "experiment_id", nullable=True)
    op.add_column("jobs", sa.Column("version_id", sa.Uuid(), sa.ForeignKey("dataset_versions.id")))
    op.add_column("jobs", sa.Column("run_id", sa.Uuid(), sa.ForeignKey("runs.id")))
    op.create_unique_constraint("jobs_run_id_key", "jobs", ["run_id"])
    op.add_column(
        "jobs", sa.Column("kind", sa.String(24), nullable=False, server_default="diagnostic")
    )
    op.add_column("jobs", sa.Column("payload", JSONB(), nullable=False, server_default="{}"))
    op.add_column("jobs", sa.Column("sequence", sa.Integer(), nullable=False, server_default="0"))


def downgrade():
    # A downgrade cannot represent multiple jobs per experiment; refuse if such data exists.
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM jobs WHERE kind <> 'diagnostic') "
        "THEN RAISE EXCEPTION 'Remove benchmark/version jobs before downgrade'; END IF; END $$"
    )
    for col in ("sequence", "payload", "kind", "run_id", "version_id"):
        op.drop_column("jobs", col)
    op.alter_column("jobs", "experiment_id", nullable=False)
    op.create_unique_constraint("jobs_experiment_id_key", "jobs", ["experiment_id"])
    for table in ("runs", "comparison_cases", "dataset_versions", "datasets"):
        op.drop_table(table)
