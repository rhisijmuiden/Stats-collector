"""Typed access to the key/value settings table, with defaults."""

from __future__ import annotations

import copy
from typing import Any

from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import DEFAULT_TENANT_ID, Setting

DEFAULTS: dict[str, dict[str, Any]] = {
    # Live walls: the address screens use (when the wall service has its own reverse proxy) and
    # extra proxy addresses the wall service trusts for X-Forwarded-For.
    "livewall": {"public_url": "", "trusted_proxies": ""},
    # Weekly summary per editor (services/digest.py); last_week is the ISO week last sent.
    "digest": {
        "enabled": False,
        "weekday": 0,
        "time": "08:00",
        "ranking": True,
        "excluded_person_ids": [],
        "last_week": "",
    },
    "general": {
        "organization": "Stats Collector",
        "default_language": "en",
        "timezone": "Europe/Amsterdam",
    },
    "updates": {
        "channel": None,  # filled from config default_channel
        "auto_check": True,
    },
    "email": {
        "enabled": False,
        "host": "",
        "port": 587,
        "security": "starttls",  # starttls | ssl | none
        "auth": "password",  # password | xoauth2 | none
        "username": "",
        "password_enc": None,
        "oauth_token_url": "",
        "oauth_client_id": "",
        "oauth_client_secret_enc": None,
        "oauth_scope": "https://outlook.office365.com/.default",
        "from_address": "",
        "from_name": "Stats Collector",
        "reply_to": "",
        "verify_tls": True,
        "timeout": 20,
        # Microsoft 365: send through Graph from one mailbox; the SMTP server above is then the fallback.
        "transport": "smtp",  # smtp | graph
        "graph_tenant_id": "",
        "graph_client_id": "",
        "graph_client_secret_enc": None,
        "graph_mailbox": "",
    },
    "sso": {
        "enabled": False,
        "tenant_id": "",
        "client_id": "",
        "client_secret_enc": None,
        "allow_local_login": True,
        "group_roles": {"admin": "", "editor_in_chief": "", "editor": "", "staff": ""},
        "default_role": "staff",
    },
    "backup": {
        "schedule_enabled": False,
        "full_every": "weekly",  # daily | weekly | monthly
        "full_weekday": 6,  # 0 = Monday
        "incremental_every_hours": 24,
        "time": "02:30",
        "retention_full": 4,
        "encryption_passphrase_enc": None,
        "include_uploads": True,
    },
    "branding": {
        "overrides": {},  # partial theme.json overrides (colors, fonts, channels)
        "logo_light": None,  # file name in uploads/branding
        "logo_dark": None,
        "favicon": None,
        "app_name": "Stats Collector",
    },
}

SECRET_FIELDS = {
    "email": ["password_enc", "oauth_client_secret_enc", "graph_client_secret_enc"],
    "sso": ["client_secret_enc"],
    "backup": ["encryption_passphrase_enc"],
}


def _defaults(key: str) -> dict[str, Any]:
    value = copy.deepcopy(DEFAULTS[key])
    if key == "updates" and value["channel"] is None:
        value["channel"] = get_settings().default_channel
    return value


def get_section(db: Session, key: str, tenant_id: int = DEFAULT_TENANT_ID) -> dict[str, Any]:
    value = _defaults(key)
    row = db.get(Setting, (tenant_id, key))
    if row is not None and isinstance(row.value, dict):
        for k, v in row.value.items():
            if isinstance(v, dict) and isinstance(value.get(k), dict):
                value[k] = {**value[k], **v}
            else:
                value[k] = v
    return value


def set_section(db: Session, key: str, value: dict[str, Any], tenant_id: int = DEFAULT_TENANT_ID) -> None:
    row = db.get(Setting, (tenant_id, key))
    if row is None:
        db.add(Setting(tenant_id=tenant_id, key=key, value=value))
    else:
        row.value = value
    db.commit()


def update_section(db: Session, key: str, changes: dict[str, Any], tenant_id: int = DEFAULT_TENANT_ID) -> dict:
    current = get_section(db, key, tenant_id)
    current.update(changes)
    set_section(db, key, current, tenant_id)
    return current


def public_view(key: str, value: dict[str, Any]) -> dict[str, Any]:
    """Remove encrypted secrets; replace them with *_set booleans."""
    out = dict(value)
    for field in SECRET_FIELDS.get(key, []):
        out[field.removesuffix("_enc") + "_set"] = bool(out.pop(field, None))
    return out
