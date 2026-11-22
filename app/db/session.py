from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from app.core.config import Settings
from app.db.config import database_url


def open_database_engine(settings: Settings) -> Engine:
    return create_engine(
        database_url(settings),
        hide_parameters=True,
        pool_pre_ping=True,
        connect_args={"connect_timeout": 3},
    )
