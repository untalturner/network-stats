"""Add explicit schedule customization state to scheduled jobs."""

from alembic import op
import sqlalchemy as sa


revision = "f2a6d9c14b73"
down_revision = "d17c4a9b2e61"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "scheduled_jobs",
        sa.Column(
            "schedule_is_customized",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("scheduled_jobs", "schedule_is_customized")
