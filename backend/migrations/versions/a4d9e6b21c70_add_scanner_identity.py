"""Add scanner identity to discovery results."""

from alembic import op
import sqlalchemy as sa


revision = "a4d9e6b21c70"
down_revision = "91c4e8a72b6d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("discovery_results") as batch_op:
        batch_op.add_column(
            sa.Column(
                "is_this_device",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("discovery_results") as batch_op:
        batch_op.drop_column("is_this_device")
