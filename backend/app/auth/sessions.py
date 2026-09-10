import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.config import get_settings
from app.models.org import Session as SessionRow
from app.models.org import User

SESSION_COOKIE = "tp_session"


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def issue_session(db: DbSession, user: User) -> str:
    """Returns the raw token — only the hash is stored, so it cannot be recovered later."""
    token = secrets.token_urlsafe(48)
    expires = datetime.now(UTC) + timedelta(hours=get_settings().session_ttl_hours)
    db.add(SessionRow(user_id=user.id, token_hash=_hash_token(token), expires_at=expires))
    db.commit()
    return token


def resolve_session(db: DbSession, token: str) -> User | None:
    row = db.scalar(select(SessionRow).where(SessionRow.token_hash == _hash_token(token)))
    if row is None or row.revoked_at is not None:
        return None
    if row.expires_at <= datetime.now(UTC):
        return None
    user = db.get(User, row.user_id)
    if user is None or not user.is_active:
        return None
    return user


def revoke_session(db: DbSession, token: str) -> None:
    row = db.scalar(select(SessionRow).where(SessionRow.token_hash == _hash_token(token)))
    if row is not None and row.revoked_at is None:
        row.revoked_at = datetime.now(UTC)
        db.commit()
