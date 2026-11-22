import re
from datetime import datetime
from hashlib import sha256

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.models import AnonymousSession

TOKEN_BYTES = 32
SESSION_TOKEN = re.compile(r"[A-Za-z0-9_-]{43}")


def cookie_name(settings: Settings) -> str:
    return (
        "__Host-insightpilot_session"
        if settings.secure_session_cookie
        else "insightpilot_session"
    )


def session_digest(token: str) -> bytes:
    return sha256(token.encode("ascii")).digest()


def find_active_session(
    database: Session, token: str | None, now: datetime
) -> AnonymousSession | None:
    if token is None or SESSION_TOKEN.fullmatch(token) is None:
        return None

    return database.scalar(
        select(AnonymousSession).where(
            AnonymousSession.token_hash == session_digest(token),
            AnonymousSession.expires_at > now,
        )
    )
