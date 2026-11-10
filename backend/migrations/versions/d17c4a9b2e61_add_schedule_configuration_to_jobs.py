"""Add configurable schedule definitions to scheduled jobs."""

from alembic import op
import sqlalchemy as sa


revision = "d17c4a9b2e61"
down_revision = "a4d9e6b21c70"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("scheduled_jobs") as batch_op:
        batch_op.add_column(
            sa.Column(
                "schedule_type",
                sa.String(length=20),
                nullable=False,
                server_default="interval",
            )
        )
        batch_op.add_column(
            sa.Column("cron_expression", sa.String(length=120), nullable=True)
        )
        batch_op.add_column(
            sa.Column(
                "timezone",
                sa.String(length=64),
                nullable=False,
                server_default="UTC",
            )
        )
        batch_op.add_column(sa.Column("start_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("end_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("scheduled_jobs") as batch_op:
        batch_op.drop_column("end_at")
        batch_op.drop_column("start_at")
        batch_op.drop_column("timezone")
        batch_op.drop_column("cron_expression")
        batch_op.drop_column("schedule_type")
