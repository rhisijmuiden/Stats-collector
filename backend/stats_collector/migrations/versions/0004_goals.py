"""Goals and their revisions

Revision ID: 0004
Revises: 0003
"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "goals",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("metric", sa.String(length=32), nullable=False),
        sa.Column("source_ids", sa.JSON(), nullable=False),
        sa.Column("target", sa.Float(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("notify", sa.Boolean(), nullable=False),
        sa.Column("notify_emails", sa.JSON(), nullable=False),
        sa.Column("reached_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("behind_notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("goals", schema=None) as batch_op:
        batch_op.create_index("ix_goals_tenant_id", ["tenant_id"], unique=False)
    op.create_table(
        "goal_revisions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("goal_id", sa.Integer(), nullable=False),
        sa.Column("target", sa.Float(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("note", sa.String(length=500), nullable=False),
        sa.Column("changed_by", sa.Integer(), nullable=True),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["changed_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["goal_id"], ["goals.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("goal_revisions", schema=None) as batch_op:
        batch_op.create_index("ix_goal_revisions_goal_id", ["goal_id"], unique=False)


def downgrade() -> None:
    op.drop_table("goal_revisions")
    op.drop_table("goals")
