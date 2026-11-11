"""Insights: outlier alerts, stories over all channels, goals per week or month

Revision ID: 0009
Revises: 0008
"""

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("goals", schema=None) as batch_op:
        batch_op.add_column(sa.Column("period", sa.String(length=8), nullable=False, server_default="none"))
        batch_op.add_column(sa.Column("show_on_wall", sa.Boolean(), nullable=False, server_default=sa.true()))

    op.create_table(
        "alert_rules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("scope", sa.String(length=16), nullable=False),
        sa.Column("source_ids", sa.JSON(), nullable=False),
        sa.Column("factor", sa.Float(), nullable=False),
        sa.Column("min_value", sa.Float(), nullable=False),
        sa.Column("teams_webhook_enc", sa.Text(), nullable=True),
        sa.Column("emails", sa.JSON(), nullable=False),
        sa.Column("language", sa.String(length=5), nullable=False),
        sa.Column("quiet_start", sa.String(length=5), nullable=False),
        sa.Column("quiet_end", sa.String(length=5), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_alert_rules_tenant_id", "alert_rules", ["tenant_id"])

    op.create_table(
        "alert_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("rule_id", sa.Integer(), sa.ForeignKey("alert_rules.id", ondelete="CASCADE"), nullable=True),
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("source_id", sa.Integer(), sa.ForeignKey("sources.id", ondelete="CASCADE"), nullable=True),
        sa.Column("item_id", sa.Integer(), sa.ForeignKey("content_items.id", ondelete="CASCADE"), nullable=True),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("measure", sa.String(length=32), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("usual", sa.Float(), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("delivered", sa.JSON(), nullable=False),
        sa.Column("error", sa.String(length=500), nullable=False),
        sa.UniqueConstraint("rule_id", "key", name="uq_alert_events_rule_key"),
    )
    op.create_index("ix_alert_events_tenant_id", "alert_events", ["tenant_id"])
    op.create_index("ix_alert_events_at", "alert_events", ["at"])

    op.create_table(
        "stories",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("item_ids", sa.JSON(), nullable=False),
        sa.Column("excluded_ids", sa.JSON(), nullable=False),
        sa.Column("keywords", sa.JSON(), nullable=False),
        sa.Column("radio", sa.JSON(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_stories_tenant_id", "stories", ["tenant_id"])


def downgrade() -> None:
    op.drop_table("stories")
    op.drop_table("alert_events")
    op.drop_table("alert_rules")
    with op.batch_alter_table("goals", schema=None) as batch_op:
        batch_op.drop_column("show_on_wall")
        batch_op.drop_column("period")
