from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel

from app.api.dependencies import DatabaseSession, require_trusted_origin
from app.core.config import Settings
from app.security.sessions import cookie_name, csrf_token
from app.services.sessions import establish_session

router = APIRouter()


class SessionResponse(BaseModel):
    expires_at: datetime
    csrf_token: str


@router.post(
    "/session",
    dependencies=[Depends(require_trusted_origin)],
    responses={201: {"description": "Session created"}},
)
def create_session(
    request: Request, response: Response, database: DatabaseSession
) -> SessionResponse:
    settings: Settings = request.app.state.settings
    name = cookie_name(settings)
    lifetime = timedelta(days=settings.session_lifetime_days)
    session = establish_session(database, request.cookies.get(name), lifetime)

    response.headers["Cache-Control"] = "no-store"
    if session.created:
        response.status_code = 201
        response.set_cookie(
            name,
            session.token,
            max_age=int(lifetime.total_seconds()),
            expires=session.expires_at,
            path="/",
            secure=settings.secure_session_cookie,
            httponly=True,
            samesite="lax",
        )
    return SessionResponse(
        expires_at=session.expires_at, csrf_token=csrf_token(session.token)
    )
