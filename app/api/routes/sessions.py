from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy.exc import SQLAlchemyError

from app.api.dependencies import DatabaseSession
from app.core.config import Settings
from app.security.sessions import cookie_name
from app.services.sessions import establish_session

router = APIRouter()


class SessionResponse(BaseModel):
    expires_at: datetime


@router.post("/session", responses={201: {"description": "Session created"}})
def create_session(
    request: Request, response: Response, database: DatabaseSession
) -> SessionResponse:
    settings: Settings = request.app.state.settings
    name = cookie_name(settings)
    lifetime = timedelta(days=settings.session_lifetime_days)
    try:
        session = establish_session(database, request.cookies.get(name), lifetime)
    except SQLAlchemyError:
        raise HTTPException(
            status_code=503, detail="Session storage unavailable."
        ) from None

    response.headers["Cache-Control"] = "no-store"
    if session.new_token is not None:
        response.status_code = 201
        response.set_cookie(
            name,
            session.new_token,
            max_age=int(lifetime.total_seconds()),
            expires=session.expires_at,
            path="/",
            secure=settings.secure_session_cookie,
            httponly=True,
            samesite="lax",
        )
    return SessionResponse(expires_at=session.expires_at)
