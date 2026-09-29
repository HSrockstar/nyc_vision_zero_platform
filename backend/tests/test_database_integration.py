"""显式启用后，仅在专用开发容器中创建随机验证库，不回退开发库。"""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import secrets

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
import psycopg
from psycopg import sql
import pytest

from app.config import BACKEND_ROOT, PROJECT_ROOT, Settings
from app.main import app

pytestmark = pytest.mark.skipif(
    os.getenv("VISION_ZERO_RUN_DB_TESTS") != "1",
    reason="需显式启用真实PostgreSQL验证；普通Check不修改数据库",
)


def test_empty_database_migration_lifecycle(monkeypatch):
    url = Settings().connection_url(migration=True)
    assert url.database == "vision_zero_dev"
    name = "vision_zero_m1_test_" + secrets.token_hex(6)

    def connect(database):
        return psycopg.connect(
            host=url.host, port=url.port, dbname=database,
            user=url.username, password=url.password,
            connect_timeout=3, autocommit=True,
        )

    with connect(url.database) as connection:
        connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    with connect(name) as connection:
        # 回归官方镜像的多schema搜索路径：外部关系不应成为业务删除候选。
        connection.execute("CREATE SCHEMA extension_fixture")
        connection.execute("CREATE TABLE extension_fixture.reference (id integer)")
        connection.execute(sql.SQL("ALTER DATABASE {} SET search_path TO public, extension_fixture").format(sql.Identifier(name)))
    test_url = url.set(database=name)
    monkeypatch.setenv("VISION_ZERO_DATABASE_NAME", name)
    monkeypatch.setenv("VISION_ZERO_DATABASE_URL", test_url.render_as_string(hide_password=False))
    monkeypatch.setenv("VISION_ZERO_MIGRATION_DATABASE_URL", test_url.render_as_string(hide_password=False))
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    result = {"database": name, "checked_at": datetime.now(timezone.utc).isoformat(), "steps": {}}

    def relations():
        with connect(name) as connection:
            return [row[0] for row in connection.execute("""
                SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p')
                  AND NOT EXISTS (SELECT 1 FROM pg_depend d
                      WHERE d.classid = 'pg_class'::regclass AND d.objid = c.oid AND d.deptype = 'e')
                ORDER BY c.relname
            """)]

    assert relations() == []
    result["steps"]["initial_non_extension_tables"] = []
    with TestClient(app) as client:
        assert client.get("/health/live").status_code == 200
        before = client.get("/health/ready")
        assert before.status_code == 503
        result["steps"]["ready_before_migration"] = before.json()
        command.upgrade(config, "head")
        ready = client.get("/health/ready")
        assert ready.status_code == 200
        result["steps"]["ready_after_upgrade"] = ready.json()
        assert relations() == ["alembic_version"]
        command.check(config)
        with connect(name) as connection:
            assert connection.execute("SELECT to_regclass('extension_fixture.reference') IS NOT NULL").fetchone()[0]
        result["steps"]["autogenerate_external_schema_preserved"] = True
        command.upgrade(config, "head")
        with connect(name) as connection:
            revisions = connection.execute("SELECT version_num FROM public.alembic_version").fetchall()
            assert revisions == [("0001_environment",)]
            result["steps"]["repeat_upgrade_revision"] = revisions[0][0]
        command.downgrade(config, "base")
        after_down = client.get("/health/ready")
        assert after_down.status_code == 503
        assert after_down.json()["reason"] == "migration_pending"
        result["steps"]["ready_after_downgrade"] = after_down.json()
        command.upgrade(config, "head")
        assert client.get("/health/ready").status_code == 200
        with connect(name) as connection:
            srid = connection.execute("SELECT ST_SRID(ST_SetSRID(ST_MakePoint(-73.9857,40.7484),4326))").fetchone()[0]
            assert srid == 4326
            result["steps"]["spatial_srid"] = srid
            result["steps"]["postgresql"] = connection.execute("SHOW server_version").fetchone()[0]
            result["steps"]["postgis"] = connection.execute("SELECT postgis_lib_version()").fetchone()[0]
        result["steps"]["final_non_extension_tables"] = relations()

    result["status"] = "passed"
    result["retained_for_review"] = True
    output = PROJECT_ROOT / ".m1-work/foundation/database-integration.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
