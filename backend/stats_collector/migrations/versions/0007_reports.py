"""Reports

Revision ID: 0007
Revises: 0006
"""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "reports",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("intro", sa.Text(), nullable=False),
        sa.Column("blocks", sa.JSON(), nullable=False),
        sa.Column("period", sa.String(length=20), nullable=False),
        sa.Column("language", sa.String(length=5), nullable=False),
        sa.Column("schedule", sa.String(length=10), nullable=False),
        sa.Column("send_time", sa.String(length=5), nullable=False),
        sa.Column("weekday", sa.Integer(), nullable=False),
        sa.Column("monthday", sa.Integer(), nullable=False),
        sa.Column("recipient_users", sa.JSON(), nullable=False),
        sa.Column("recipient_emails", sa.JSON(), nullable=False),
        sa.Column("attach_pdf", sa.Boolean(), nullable=False),
        sa.Column("link_days", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("reports", schema=None) as batch_op:
        batch_op.create_index("ix_reports_tenant_id", ["tenant_id"], unique=False)
        batch_op.create_index("ix_reports_next_run_at", ["next_run_at"], unique=False)
    op.create_table(
        "report_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("report_id", sa.Integer(), nullable=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("token_enc", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("trigger", sa.String(length=10), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("recipients", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("error", sa.String(length=500), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["report_id"], ["reports.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    with op.batch_alter_table("report_runs", schema=None) as batch_op:
        batch_op.create_index("ix_report_runs_report_id", ["report_id"], unique=False)


def downgrade() -> None:
    op.drop_table("report_runs")
    op.drop_table("reports")
