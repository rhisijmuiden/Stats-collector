"""Live walls: layout, rotation and editor names

Revision ID: 0008
Revises: 0007
"""

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("live_walls", schema=None) as batch_op:
        batch_op.add_column(sa.Column("layout", sa.String(length=16), nullable=False, server_default="rotate"))
        batch_op.add_column(sa.Column("rotate_seconds", sa.Integer(), nullable=False, server_default="30"))
        batch_op.add_column(sa.Column("show_authors", sa.Boolean(), nullable=False, server_default=sa.true()))


def downgrade() -> None:
    with op.batch_alter_table("live_walls", schema=None) as batch_op:
        batch_op.drop_column("show_authors")
        batch_op.drop_column("rotate_seconds")
        batch_op.drop_column("layout")
