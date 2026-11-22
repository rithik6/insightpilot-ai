from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session, sessionmaker


def database_session(request: Request) -> Iterator[Session]:
    factory: sessionmaker[Session] | None = request.app.state.database_sessions
    if factory is None:
        raise HTTPException(status_code=503, detail="Session storage unavailable.")

    with factory() as database:
        yield database


DatabaseSession = Annotated[Session, Depends(database_session)]
