from alembic import context
from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool

from app.core.config import Settings
from app.db.config import database_url
from app.db.models import Base


def run_migrations_offline() -> None:
    context.configure(
        dialect_name="postgresql", target_metadata=Base.metadata, literal_binds=True
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    url = context.config.attributes.get("database_url")
    if url is None:
        url = database_url(Settings())
    engine = create_engine(
        url,
        poolclass=NullPool,
        hide_parameters=True,
        connect_args={"connect_timeout": 3},
    )
    try:
        with engine.connect() as connection:
            context.configure(
                connection=connection,
                target_metadata=Base.metadata,
                compare_server_default=True,
            )
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
