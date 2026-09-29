from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.pool import NullPool

from app.config import Settings


def database_engine(settings: Settings, *, migration: bool = False, worker: bool = False) -> Engine:
    return create_engine(
        settings.connection_url(migration=migration, worker=worker),
        poolclass=NullPool,
        connect_args={"connect_timeout": 3},
        hide_parameters=True,
    )
