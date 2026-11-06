"""Add ICMP measurements to discovery results."""

from alembic import op
import sqlalchemy as sa


revision = "91c4e8a72b6d"
down_revision = "b7a2c91e4d63"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("discovery_results") as batch_op:
        batch_op.add_column(sa.Column("icmp_latency_ms", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("icmp_is_available", sa.Boolean(), nullable=True))
        batch_op.add_column(sa.Column("icmp_error", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("discovery_results") as batch_op:
        batch_op.drop_column("icmp_error")
        batch_op.drop_column("icmp_is_available")
        batch_op.drop_column("icmp_latency_ms")
