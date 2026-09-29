from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.pool import NullPool

from app.config import Settings


def database_engine(settings: Settings, *, migration: bool = False) -> Engine:
    return create_engine(
        settings.connection_url(migration=migration),
        poolclass=NullPool,
        connect_args={"connect_timeout": 3},
        hide_parameters=True,
    )
