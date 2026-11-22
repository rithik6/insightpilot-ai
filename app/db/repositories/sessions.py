from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import AnonymousSession


@dataclass(frozen=True)
class SessionRecord:
    id: UUID
    expires_at: datetime


def find_unexpired_session(
    database: Session, digest: bytes, now: datetime
) -> SessionRecord | None:
    row = database.execute(
        select(AnonymousSession.id, AnonymousSession.expires_at).where(
            AnonymousSession.token_hash == digest,
            AnonymousSession.expires_at > now,
        )
    ).one_or_none()
    return (
        SessionRecord(id=row.id, expires_at=row.expires_at) if row is not None else None
    )


def add_session(
    database: Session, digest: bytes, created_at: datetime, expires_at: datetime
) -> None:
    database.add(
        AnonymousSession(
            token_hash=digest, created_at=created_at, expires_at=expires_at
        )
    )
