from collections.abc import Iterator
from hmac import compare_digest
from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.security.sessions import cookie_name, csrf_token
from app.services.sessions import active_session_id

STORAGE_UNAVAILABLE = "Data storage unavailable."


def database_session(request: Request) -> Iterator[Session]:
    factory: sessionmaker[Session] | None = request.app.state.database_sessions
    if factory is None:
        raise HTTPException(status_code=503, detail=STORAGE_UNAVAILABLE)

    with factory() as database:
        yield database


DatabaseSession = Annotated[Session, Depends(database_session)]


def require_trusted_origin(request: Request) -> None:
    settings: Settings = request.app.state.settings
    origins = request.headers.getlist("origin")
    if len(origins) != 1 or origins[0] not in settings.browser_origins:
        raise HTTPException(status_code=403, detail="Origin rejected.")


def require_session(request: Request, database: DatabaseSession) -> UUID:
    cookie = request.cookies.get(cookie_name(request.app.state.settings))
    session_id = active_session_id(database, cookie)
    if session_id is None:
        raise HTTPException(status_code=401, detail="An active session is required.")
    return session_id


ActiveSession = Annotated[UUID, Depends(require_session)]


def require_csrf(request: Request, session_id: ActiveSession) -> UUID:
    cookie = request.cookies[cookie_name(request.app.state.settings)]
    expected = csrf_token(cookie)
    tokens = request.headers.getlist("x-csrf-token")
    if len(tokens) != 1 or not compare_digest(tokens[0].encode(), expected.encode()):
        raise HTTPException(status_code=403, detail="CSRF token rejected.")

    return session_id


WriteSession = Annotated[UUID, Depends(require_csrf)]
