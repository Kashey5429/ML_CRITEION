"""File sources and reusable column selections; existing snapshots stay unchanged."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "file_imports",
        sa.Column("id", UUID(), primary_key=True),
        sa.Column("dataset_id", UUID(), sa.ForeignKey("datasets.id"), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("profile", JSONB()),
        sa.Column("error_code", sa.Text()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.add_column("jobs", sa.Column("import_id", UUID(), sa.ForeignKey("file_imports.id")))
    op.add_column("dataset_versions", sa.Column("selection", JSONB()))


def downgrade():
    op.drop_column("dataset_versions", "selection")
    op.drop_column("jobs", "import_id")
    op.drop_table("file_imports")
