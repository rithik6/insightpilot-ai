from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from secrets import token_urlsafe

from sqlalchemy.orm import Session

from app.db.models import AnonymousSession
from app.security.sessions import TOKEN_BYTES, find_active_session, session_digest


@dataclass(frozen=True)
class SessionBootstrap:
    expires_at: datetime
    token: str = field(repr=False)
    created: bool


def establish_session(
    database: Session, cookie: str | None, lifetime: timedelta
) -> SessionBootstrap:
    now = datetime.now(UTC)
    with database.begin():
        existing = find_active_session(database, cookie, now)
        if existing is not None and cookie is not None:
            return SessionBootstrap(
                expires_at=existing.expires_at, token=cookie, created=False
            )

        token = token_urlsafe(TOKEN_BYTES)
        expires_at = now + lifetime
        database.add(
            AnonymousSession(
                token_hash=session_digest(token), created_at=now, expires_at=expires_at
            )
        )

    return SessionBootstrap(expires_at=expires_at, token=token, created=True)
