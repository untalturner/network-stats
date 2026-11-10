"""Add per-job execution timeout.

Revision ID: d9a2f6c81b34
Revises: c4f81a2b9d63
"""

from alembic import op
import sqlalchemy as sa


revision = "d9a2f6c81b34"
down_revision = "c4f81a2b9d63"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "scheduled_jobs",
        sa.Column(
            "execution_timeout_seconds",
            sa.Float(),
            server_default=sa.text("300"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("scheduled_jobs", "execution_timeout_seconds")
