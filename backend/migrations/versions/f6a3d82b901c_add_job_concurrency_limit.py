"""Add per-job concurrency limit.

Revision ID: f6a3d82b901c
Revises: e7b4c91a6d20
"""

from alembic import op
import sqlalchemy as sa


revision = "f6a3d82b901c"
down_revision = "e7b4c91a6d20"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "scheduled_jobs",
        sa.Column(
            "max_concurrent_runs",
            sa.Integer(),
            server_default=sa.text("1"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("scheduled_jobs", "max_concurrent_runs")
