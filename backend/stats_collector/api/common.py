from __future__ import annotations

from sqlalchemy.orm import Session

from ..models import AuditLog, User


def user_out(user: User) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "display_name": user.display_name,
        "role": user.role,
        "auth_provider": user.auth_provider,
        "language": user.language,
        "theme": user.theme,
        "is_active": user.is_active,
        "totp_enabled": bool(user.totp_secret),
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
    }


def audit(db: Session, user: User | None, action: str, detail: dict | None = None) -> None:
    db.add(AuditLog(user_id=user.id if user else None, action=action, detail=detail or {}))
    db.commit()
