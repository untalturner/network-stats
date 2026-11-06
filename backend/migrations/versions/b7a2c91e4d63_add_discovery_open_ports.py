"""add open ports to discovery results

Revision ID: b7a2c91e4d63
Revises: edf390ffb308
Create Date: 2026-11-06
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b7a2c91e4d63"
down_revision: Union[str, Sequence[str], None] = "edf390ffb308"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "discovery_results",
        sa.Column(
            "open_ports",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
    )


def downgrade() -> None:
    with op.batch_alter_table("discovery_results") as batch_op:
        batch_op.drop_column("open_ports")
