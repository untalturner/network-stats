"""add persistent monitoring job history

Revision ID: 8f97d4c25d9b
Revises: c8cbe47e9ea4
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "8f97d4c25d9b"
down_revision: Union[str, Sequence[str], None] = "c8cbe47e9ea4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "job_executions",
        sa.Column("job_name", sa.String(length=150), nullable=True),
    )

    with op.batch_alter_table("scheduled_jobs") as batch_op:
        batch_op.add_column(
            sa.Column(
                "target_id",
                sa.Integer(),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column(
                "updated_at",
                sa.DateTime(),
                nullable=True,
            )
        )
        batch_op.create_unique_constraint(
            "uq_scheduled_jobs_target_id",
            ["target_id"],
        )
        batch_op.create_foreign_key(
            "fk_scheduled_jobs_target_id_monitoring_targets",
            "monitoring_targets",
            ["target_id"],
            ["id"],
            ondelete="SET NULL",
        )

    op.execute(
        "UPDATE scheduled_jobs SET updated_at = CURRENT_TIMESTAMP "
        "WHERE updated_at IS NULL"
    )

    with op.batch_alter_table("scheduled_jobs") as batch_op:
        batch_op.alter_column(
            "updated_at",
            existing_type=sa.DateTime(),
            nullable=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("scheduled_jobs") as batch_op:
        batch_op.drop_constraint(
            "fk_scheduled_jobs_target_id_monitoring_targets",
            type_="foreignkey",
        )
        batch_op.drop_constraint(
            "uq_scheduled_jobs_target_id",
            type_="unique",
        )
        batch_op.drop_column("updated_at")
        batch_op.drop_column("target_id")

    op.drop_column("job_executions", "job_name")
