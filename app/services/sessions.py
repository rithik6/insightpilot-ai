from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from secrets import token_urlsafe
from uuid import UUID

from sqlalchemy.orm import Session

from app.db.repositories.sessions import (
    SessionRecord,
    add_session,
    find_unexpired_session,
)
from app.security.sessions import SESSION_TOKEN, TOKEN_BYTES, session_digest


@dataclass(frozen=True)
class SessionBootstrap:
    expires_at: datetime
    token: str = field(repr=False)
    created: bool


def _find_session(database: Session, token: str, now: datetime) -> SessionRecord | None:
    if SESSION_TOKEN.fullmatch(token) is None:
        return None
    return find_unexpired_session(database, session_digest(token), now)


def active_session_id(database: Session, cookie: str | None) -> UUID | None:
    if cookie is None:
        return None
    with database.begin():
        existing = _find_session(database, cookie, datetime.now(UTC))
        return existing.id if existing is not None else None


def establish_session(
    database: Session, cookie: str | None, lifetime: timedelta
) -> SessionBootstrap:
    now = datetime.now(UTC)
    with database.begin():
        if cookie is not None:
            existing = _find_session(database, cookie, now)
            if existing is not None:
                return SessionBootstrap(
                    expires_at=existing.expires_at, token=cookie, created=False
                )

        token = token_urlsafe(TOKEN_BYTES)
        expires_at = now + lifetime
        add_session(database, session_digest(token), now, expires_at)

    return SessionBootstrap(expires_at=expires_at, token=token, created=True)
