"""Database models. Every tenant-owned table carries tenant_id so multi-tenancy can be added later."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base

DEFAULT_TENANT_ID = 1

ROLES = ("admin", "editor_in_chief", "editor", "staff")


def utcnow() -> datetime:
    return datetime.now(UTC)


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class User(Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("tenant_id", "email", name="uq_users_tenant_email"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True, default=DEFAULT_TENANT_ID)
    email: Mapped[str] = mapped_column(String(320))
    display_name: Mapped[str] = mapped_column(String(200))
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    role: Mapped[str] = mapped_column(String(32), default="staff")
    auth_provider: Mapped[str] = mapped_column(String(32), default="local")  # local | entra
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    language: Mapped[str] = mapped_column(String(8), default="en")
    theme: Mapped[str] = mapped_column(String(8), default="system")  # system | light | dark
    totp_secret: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    sessions: Mapped[list[UserSession]] = relationship(back_populates="user", cascade="all, delete-orphan")


class UserSession(Base):
    __tablename__ = "user_sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # sha256 of the cookie token
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    csrf_token: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(400), nullable=True)

    user: Mapped[User] = relationship(back_populates="sessions")


class SetupToken(Base):
    """One-time link to create the first admin account (printed by the installer)."""

    __tablename__ = "setup_tokens"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # sha256 of token
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), default=DEFAULT_TENANT_ID)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Setting(Base):
    __tablename__ = "settings"

    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), primary_key=True)
    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[Any] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True, default=DEFAULT_TENANT_ID)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    action: Mapped[str] = mapped_column(String(100))
    detail: Mapped[Any] = mapped_column(JSON, default=dict)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class BackupTarget(Base):
    __tablename__ = "backup_targets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True, default=DEFAULT_TENANT_ID)
    name: Mapped[str] = mapped_column(String(100))
    kind: Mapped[str] = mapped_column(String(16))  # ftp | ftps | sftp (scp)
    host: Mapped[str] = mapped_column(String(255))
    port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    username: Mapped[str] = mapped_column(String(255))
    secret_enc: Mapped[str | None] = mapped_column(Text, nullable=True)  # password or private key (encrypted)
    auth_method: Mapped[str] = mapped_column(String(16), default="password")  # password | key
    path: Mapped[str] = mapped_column(String(500), default="stats-collector")
    ftps_mode: Mapped[str] = mapped_column(String(16), default="explicit")  # explicit | implicit
    verify_tls: Mapped[bool] = mapped_column(Boolean, default=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class OpsJob(Base):
    """Privileged jobs (update, backup, restore) executed by the root-owned ops runner."""

    __tablename__ = "ops_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), default=DEFAULT_TENANT_ID)
    kind: Mapped[str] = mapped_column(String(32))  # update | backup | restore
    params: Mapped[Any] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)
    log: Mapped[str] = mapped_column(Text, default="")
    result: Mapped[Any] = mapped_column(JSON, default=dict)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class BackupRecord(Base):
    __tablename__ = "backup_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), default=DEFAULT_TENANT_ID)
    label: Mapped[str] = mapped_column(String(100), unique=True)
    kind: Mapped[str] = mapped_column(String(8))  # full | incr
    base_label: Mapped[str | None] = mapped_column(String(100), nullable=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    targets: Mapped[Any] = mapped_column(JSON, default=list)
    app_version: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# --- Data collection (phase 1) -------------------------------------------------------------

BIGID = BigInteger().with_variant(Integer, "sqlite")

SOURCE_KINDS = ("icecast", "owncast", "wordpress", "youtube", "facebook", "instagram", "threads", "bluesky", "mastodon")

# Canonical categories every platform metric is mapped to, so channels can be stacked.
CATEGORIES = ("live_audience", "reach", "views", "interactions", "watch_time", "followers")


class Source(Base):
    """A configured connector instance, e.g. one Icecast server or one Owncast server."""

    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True, default=DEFAULT_TENANT_ID)
    kind: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(200))
    config: Mapped[Any] = mapped_column(JSON, default=dict)  # url, mounts, ...
    secret_enc: Mapped[str | None] = mapped_column(Text, nullable=True)  # encrypted JSON with passwords/tokens
    webhook_token: Mapped[str | None] = mapped_column(String(64), nullable=True)
    poll_seconds: Mapped[int] = mapped_column(Integer, default=30)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_poll_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_ok_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_error_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ContentItem(Base):
    """Something numbers belong to: a mount, a broadcast, a post, a video or an article."""

    __tablename__ = "content_items"
    __table_args__ = (UniqueConstraint("source_id", "external_id", name="uq_items_source_external"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True, default=DEFAULT_TENANT_ID)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(32))  # mount | broadcast | post | video | article
    external_id: Mapped[str] = mapped_column(String(255))
    title: Mapped[str] = mapped_column(String(500), default="")
    url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    category: Mapped[str | None] = mapped_column(String(200), nullable=True)
    tags: Mapped[Any] = mapped_column(JSON, default=list)
    meta: Mapped[Any] = mapped_column(JSON, default=dict)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Person(Base):
    """An editor or creator; linked to a WordPress user and optionally an app user."""

    __tablename__ = "people"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True, default=DEFAULT_TENANT_ID)
    display_name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    external_ids: Mapped[Any] = mapped_column(JSON, default=dict)  # e.g. {"wordpress:3": 12}
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ItemPerson(Base):
    __tablename__ = "item_people"
    __table_args__ = (Index("ix_item_people_person", "person_id"),)

    item_id: Mapped[int] = mapped_column(ForeignKey("content_items.id", ondelete="CASCADE"), primary_key=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("people.id", ondelete="CASCADE"), primary_key=True)
    role: Mapped[str] = mapped_column(String(32), primary_key=True, default="author")  # author | coauthor | presenter


class ItemLink(Base):
    """Links items across platforms, e.g. a Facebook post pointing to an article."""

    __tablename__ = "item_links"

    from_item_id: Mapped[int] = mapped_column(ForeignKey("content_items.id", ondelete="CASCADE"), primary_key=True)
    to_item_id: Mapped[int] = mapped_column(ForeignKey("content_items.id", ondelete="CASCADE"), primary_key=True)
    method: Mapped[str] = mapped_column(String(16), default="url")  # url | tracking | manual
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class MetricDefinition(Base):
    __tablename__ = "metric_definitions"
    __table_args__ = (UniqueConstraint("platform", "key", name="uq_metric_platform_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    platform: Mapped[str] = mapped_column(String(32))
    key: Mapped[str] = mapped_column(String(100))
    unit: Mapped[str] = mapped_column(String(16), default="count")  # count | minutes | seconds
    aggregation: Mapped[str] = mapped_column(String(8), default="sum")  # sum | avg | max | gauge
    category: Mapped[str] = mapped_column(String(32))
    label_en: Mapped[str] = mapped_column(String(200))
    label_nl: Mapped[str] = mapped_column(String(200))


class StreamSample(Base):
    """Raw Owncast/Icecast sample (every poll, ~30 s). Kept for one year."""

    __tablename__ = "stream_samples"
    __table_args__ = (Index("ix_samples_source_ts", "source_id", "ts"),)

    id: Mapped[int] = mapped_column(BIGID, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), default=DEFAULT_TENANT_ID)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id", ondelete="CASCADE"))
    item_id: Mapped[int | None] = mapped_column(ForeignKey("content_items.id", ondelete="SET NULL"), nullable=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    online: Mapped[bool] = mapped_column(Boolean, default=True)
    value: Mapped[float] = mapped_column(Float, default=0)  # listeners or viewers at ts
    extra: Mapped[Any] = mapped_column(JSON, default=dict)


class MetricPoint(Base):
    """Aggregated values per time bucket (hour/day/month). Kept forever."""

    __tablename__ = "metric_points"
    __table_args__ = (
        Index("ix_points_lookup", "tenant_id", "metric", "granularity", "bucket"),
        Index("ix_points_source", "source_id", "granularity", "bucket"),
        Index("ix_points_item", "item_id", "granularity", "bucket"),
    )

    id: Mapped[int] = mapped_column(BIGID, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), default=DEFAULT_TENANT_ID)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id", ondelete="CASCADE"))
    item_id: Mapped[int | None] = mapped_column(ForeignKey("content_items.id", ondelete="CASCADE"), nullable=True)
    metric: Mapped[str] = mapped_column(String(100))
    granularity: Mapped[str] = mapped_column(String(8))  # hour | day | month
    bucket: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    value: Mapped[float] = mapped_column(Float, default=0)


class DimensionPoint(Base):
    """Daily breakdowns that do not fit one number: referrer domains, device types.

    One row per source, item (None = whole site), day, dimension and key.
    """

    __tablename__ = "dimension_points"
    __table_args__ = (Index("ix_dims_lookup", "source_id", "dimension", "bucket"),)

    id: Mapped[int] = mapped_column(BIGID, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), default=DEFAULT_TENANT_ID)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id", ondelete="CASCADE"))
    item_id: Mapped[int | None] = mapped_column(ForeignKey("content_items.id", ondelete="CASCADE"), nullable=True)
    dimension: Mapped[str] = mapped_column(String(32))  # referrer | device
    key: Mapped[str] = mapped_column(String(255))
    bucket: Mapped[datetime] = mapped_column(DateTime(timezone=True))  # local day start, as UTC
    value: Mapped[float] = mapped_column(Float, default=0)


class Goal(Base):
    """A target on a metric, e.g. 5,000 Facebook followers or 1 million reach this quarter."""

    __tablename__ = "goals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True, default=DEFAULT_TENANT_ID)
    name: Mapped[str] = mapped_column(String(200))
    metric: Mapped[str] = mapped_column(String(32))  # followers | views | reach | interactions | watch_minutes
    source_ids: Mapped[Any] = mapped_column(JSON, default=list)  # empty = all sources
    target: Mapped[float] = mapped_column(Float)
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    notify: Mapped[bool] = mapped_column(Boolean, default=False)
    notify_emails: Mapped[Any] = mapped_column(JSON, default=list)
    reached_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    behind_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Dashboard(Base):
    """A saved dashboard: a name and a list of widgets (see api/dashboards.py for their fields)."""

    __tablename__ = "dashboards"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True, default=DEFAULT_TENANT_ID)
    name: Mapped[str] = mapped_column(String(200))
    widgets: Mapped[Any] = mapped_column(JSON, default=list)
    shared: Mapped[bool] = mapped_column(Boolean, default=False)  # visible to everyone
    position: Mapped[int] = mapped_column(Integer, default=0)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class LiveWall(Base):
    """A read-only screen for the newsroom, served on its own port at /w/<token> (see livewall/)."""

    __tablename__ = "live_walls"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True, default=DEFAULT_TENANT_ID)
    name: Mapped[str] = mapped_column(String(200))
    title: Mapped[str] = mapped_column(String(200), default="")
    source_ids: Mapped[Any] = mapped_column(JSON, default=list)  # empty = every live source
    token_enc: Mapped[str] = mapped_column(Text)  # encrypted; the link is /w/<token>
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)  # sha256 of the token: the snapshot key
    allow_ips: Mapped[str] = mapped_column(String(1000), default="")  # comma-separated IPs or networks
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class GoalRevision(Base):
    """Every target a goal has had, so reports show what the target was at the time."""

    __tablename__ = "goal_revisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    goal_id: Mapped[int] = mapped_column(ForeignKey("goals.id", ondelete="CASCADE"), index=True)
    target: Mapped[float] = mapped_column(Float)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    note: Mapped[str] = mapped_column(String(500), default="")
    changed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
