"""website: daily breakdowns (referrers, devices) and lookups by person

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-10 14:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "dimension_points",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("item_id", sa.Integer(), nullable=True),
        sa.Column("dimension", sa.String(length=32), nullable=False),
        sa.Column("key", sa.String(length=255), nullable=False),
        sa.Column("bucket", sa.DateTime(timezone=True), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(["item_id"], ["content_items.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("dimension_points", schema=None) as batch_op:
        batch_op.create_index("ix_dims_lookup", ["source_id", "dimension", "bucket"], unique=False)
    with op.batch_alter_table("item_people", schema=None) as batch_op:
        batch_op.create_index("ix_item_people_person", ["person_id"], unique=False)
    with op.batch_alter_table("metric_points", schema=None) as batch_op:
        batch_op.create_index("ix_points_item", ["item_id", "granularity", "bucket"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("metric_points", schema=None) as batch_op:
        batch_op.drop_index("ix_points_item")
    with op.batch_alter_table("item_people", schema=None) as batch_op:
        batch_op.drop_index("ix_item_people_person")
    with op.batch_alter_table("dimension_points", schema=None) as batch_op:
        batch_op.drop_index("ix_dims_lookup")
    op.drop_table("dimension_points")
