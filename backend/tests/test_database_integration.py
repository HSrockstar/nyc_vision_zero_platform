"""M1空库生命周期只在独立随机验证库执行。"""

import json
import os
from unittest.mock import patch
from alembic import command
from fastapi.testclient import TestClient
import pytest
from app.config import PROJECT_ROOT
from app.main import app
from app import models
from app.db.base import Base
from conftest import alembic_config, connect_as, validation_config

pytestmark = pytest.mark.skipif(os.getenv("VISION_ZERO_RUN_DB_TESTS") != "1", reason="需显式启用真实PG验证")


def test_empty_database_migration_lifecycle():
    values = validation_config()
    with patch.dict(os.environ, values), TestClient(app) as client:
        assert client.get("/health/live").status_code == 200
        assert client.get("/health/ready").json()["reason"] == "migration_pending"
        command.upgrade(alembic_config(), "head")
        assert client.get("/health/ready").status_code == 200
        command.check(alembic_config())
        command.upgrade(alembic_config(), "head")
        with connect_as() as connection:
            tables = [row[0] for row in connection.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")]
            assert set(Base.metadata.tables).issubset(tables)
            assert connection.execute("SELECT version_num FROM public.alembic_version").fetchone()[0] == "0002_business_model"
            assert connection.execute("SELECT EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='extension_fixture' AND c.relname='reference')").fetchone()[0]
        command.downgrade(alembic_config(), "base")
        assert client.get("/health/ready").json()["reason"] == "migration_pending"
        command.upgrade(alembic_config(), "head")
        assert client.get("/health/ready").status_code == 200
        with connect_as() as connection:
            assert connection.execute("SELECT ST_SRID(ST_SetSRID(ST_MakePoint(-73.9857, 40.7484), 4326))").fetchone()[0] == 4326
            assert connection.execute("SELECT EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='extension_fixture' AND c.relname='reference')").fetchone()[0]
        output = PROJECT_ROOT / ".m1-work/model/migration-lifecycle.json"
        output.write_text(json.dumps({"database": values["VISION_ZERO_DATABASE_NAME"], "status": "passed",
            "business_tables": len(Base.metadata.tables), "revision": "0002_business_model",
            "empty_upgrade_repeat_downgrade_reupgrade": True, "external_schema_preserved": True,
            "retained_for_review": True}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
