"""Wall Designer: a design of blocks and screens per live wall, with a draft and versions

Revision ID: 0010
Revises: 0009
"""

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("live_walls", schema=None) as batch_op:
        batch_op.add_column(sa.Column("design", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("design_draft", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("design_version", sa.Integer(), nullable=False, server_default="0"))

    op.create_table(
        "live_wall_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("wall_id", sa.Integer(), sa.ForeignKey("live_walls.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("design", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_live_wall_versions_wall_id", "live_wall_versions", ["wall_id"])


def downgrade() -> None:
    op.drop_index("ix_live_wall_versions_wall_id", table_name="live_wall_versions")
    op.drop_table("live_wall_versions")
    with op.batch_alter_table("live_walls", schema=None) as batch_op:
        batch_op.drop_column("design_version")
        batch_op.drop_column("design_draft")
        batch_op.drop_column("design")
