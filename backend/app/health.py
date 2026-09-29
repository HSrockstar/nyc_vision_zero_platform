"""就绪检查返回固定状态码，避免暴露凭据、地址及数据库异常栈。"""

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.config import BACKEND_ROOT, Settings
from app.db.connection import database_engine


def expected_revision() -> str:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    return ScriptDirectory.from_config(config).get_current_head()


def readiness(*, worker: bool = False) -> tuple[dict, int]:
    try:
        settings = Settings()
        engine = database_engine(settings, worker=worker)
    except ValueError:
        return {"status": "not_ready", "reason": "configuration_invalid"}, 503
    try:
        with engine.connect() as connection:
            version = connection.scalar(text("SHOW server_version"))
            extension = connection.scalar(
                text("SELECT extversion FROM pg_extension WHERE extname = 'postgis'")
            )
            if version.split()[0] != "17.11" or extension != "3.6.4":
                return {"status": "not_ready", "reason": "database_version_mismatch"}, 503
            present = connection.scalar(text("SELECT to_regclass('public.alembic_version')"))
            if not present:
                return {"status": "not_ready", "reason": "migration_pending"}, 503
            revisions = connection.scalars(text("SELECT version_num FROM public.alembic_version")).all()
            if revisions != [expected_revision()]:
                return {"status": "not_ready", "reason": "migration_pending"}, 503
            connection.scalar(text("SELECT ST_SRID(ST_SetSRID(ST_MakePoint(-73.9857, 40.7484), 4326))"))
        return {"status": "ready", "checks": {"database": "ok", "migration": "current", "postgis": "ok"}}, 200
    except SQLAlchemyError:
        return {"status": "not_ready", "reason": "database_unavailable"}, 503
    finally:
        engine.dispose()
