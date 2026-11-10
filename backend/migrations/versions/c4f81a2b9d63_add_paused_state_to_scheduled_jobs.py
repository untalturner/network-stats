"""Add persisted pause state to scheduled jobs."""

from alembic import op
import sqlalchemy as sa


revision = "c4f81a2b9d63"
down_revision = "b7e9c2d4a631"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "scheduled_jobs",
        sa.Column(
            "is_paused",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("scheduled_jobs", "is_paused")
