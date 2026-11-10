"""Add persisted skip-next state to scheduled jobs."""

from alembic import op
import sqlalchemy as sa


revision = "b7e9c2d4a631"
down_revision = "f2a6d9c14b73"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "scheduled_jobs",
        sa.Column(
            "skip_next_run",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("scheduled_jobs", "skip_next_run")
