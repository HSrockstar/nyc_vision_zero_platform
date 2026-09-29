"""真实PG用独立随机数据库与独立随机凭据；保留验证库，不触碰开发数据。"""

import json
import os
import secrets
from unittest.mock import patch
from uuid import uuid4

from alembic import command
from alembic.config import Config
from dotenv import dotenv_values
import psycopg
from psycopg import sql
import pytest

from app.auth import login_limiter, password_hasher
from app.config import BACKEND_ROOT, PROJECT_ROOT, Settings
from app.db.provision import admin_connect, provision
from app import models
from app.db.base import Base

TEST_PASSWORD = "M1-Synthetic-Password-2026!"
TEST_HASH = password_hasher.hash(TEST_PASSWORD)


def validation_config():
    name = "vision_zero_m1_test_" + secrets.token_hex(6)
    with admin_connect(autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    with admin_connect(name) as connection:
        connection.execute("CREATE EXTENSION IF NOT EXISTS postgis")
        connection.execute("CREATE SCHEMA extension_fixture")
        connection.execute("CREATE TABLE extension_fixture.reference (id integer)")
    path = provision(database=name)
    values = {key: value for key, value in dotenv_values(path).items() if key.startswith("VISION_ZERO_")}
    values["VISION_ZERO_RUN_DB_TESTS"] = "1"
    values["VISION_ZERO_TEST_CONFIG_FILE"] = str(path)
    return values


def alembic_config():
    return Config(str(BACKEND_ROOT / "alembic.ini"))


def connect_as(kind="migrator", *, autocommit=False):
    url = Settings().connection_url(migration=kind == "migrator", worker=kind == "worker")
    return psycopg.connect(host=url.host, port=url.port, dbname=url.database,
                          user=url.username, password=url.password, connect_timeout=3, autocommit=autocommit)


def seed_user(connection, *, role=1, username=None):
    name = username or "test_" + uuid4().hex[:16]
    user_id = connection.execute("""INSERT INTO public.app_user (username, password_hash, display_name, role_id)
        VALUES (%s, %s, %s, %s) RETURNING user_id""", (name, TEST_HASH, "明确标记的M1测试账户", role)).fetchone()[0]
    return user_id, name


@pytest.fixture(scope="session")
def model_database():
    if os.getenv("VISION_ZERO_RUN_DB_TESTS") != "1":
        pytest.skip("需显式启用真实PostgreSQL验证")
    values = validation_config()
    with patch.dict(os.environ, values):
        command.upgrade(alembic_config(), "head")
        command.check(alembic_config())
        with connect_as() as connection:
            result = {
                "database": Settings().database_name,
                "postgresql": connection.execute("SHOW server_version").fetchone()[0],
                "postgis": connection.execute("SELECT postgis_lib_version()").fetchone()[0],
                "tables": [row[0] for row in connection.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND tablename = ANY(%s) ORDER BY tablename", (list(Base.metadata.tables),))],
                "views": [row[0] for row in connection.execute("SELECT viewname FROM pg_views WHERE schemaname='public' ORDER BY viewname")],
                "foreign_keys": connection.execute("SELECT count(*) FROM pg_constraint WHERE contype='f' AND connamespace='public'::regnamespace").fetchone()[0],
                "checks": connection.execute("SELECT count(*) FROM pg_constraint WHERE contype='c' AND connamespace='public'::regnamespace").fetchone()[0],
                "roles": [list(row) for row in connection.execute("SELECT rolname, rolsuper, rolcreatedb, rolcreaterole, rolbypassrls FROM pg_roles WHERE rolname = ANY(%s) ORDER BY rolname", ([Settings().database_name + '_' + kind for kind in ('app', 'migrator', 'worker')],))],
                "retained_for_review": True,
            }
        output = PROJECT_ROOT / ".m1-work/model/schema-evidence.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return values


@pytest.fixture
def db_env(model_database):
    with patch.dict(os.environ, model_database):
        with login_limiter.lock:
            login_limiter.entries.clear()
        yield model_database


@pytest.fixture
def isolated_db():
    if os.getenv("VISION_ZERO_RUN_DB_TESTS") != "1":
        pytest.skip("需显式启用真实PostgreSQL验证")
    values = validation_config()
    with patch.dict(os.environ, values):
        command.upgrade(alembic_config(), "head")
        with login_limiter.lock:
            login_limiter.entries.clear()
        yield values
