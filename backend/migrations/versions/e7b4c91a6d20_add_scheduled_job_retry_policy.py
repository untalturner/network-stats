"""Add retry policy and attempt details to scheduled jobs.

Revision ID: e7b4c91a6d20
Revises: d9a2f6c81b34
"""

from alembic import op
import sqlalchemy as sa


revision = "e7b4c91a6d20"
down_revision = "d9a2f6c81b34"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "scheduled_jobs",
        sa.Column(
            "max_retries",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
    )
    op.add_column(
        "scheduled_jobs",
        sa.Column(
            "retry_delay_seconds",
            sa.Float(),
            server_default=sa.text("5"),
            nullable=False,
        ),
    )
    op.add_column(
        "job_executions",
        sa.Column(
            "attempt_count",
            sa.Integer(),
            server_default=sa.text("1"),
            nullable=False,
        ),
    )
    op.add_column(
        "job_executions",
        sa.Column(
            "attempt_errors",
            sa.JSON(),
            server_default=sa.text("'[]'"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("job_executions", "attempt_errors")
    op.drop_column("job_executions", "attempt_count")
    op.drop_column("scheduled_jobs", "retry_delay_seconds")
    op.drop_column("scheduled_jobs", "max_retries")
