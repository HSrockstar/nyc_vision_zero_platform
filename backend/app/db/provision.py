"""用本机维护账号配置专用库角色；不修改其他数据库或复用未知角色。"""

import hashlib
import json
import re
import secrets
import os
import subprocess
from pathlib import Path

from dotenv import dotenv_values
import psycopg
from psycopg import sql
from sqlalchemy.engine import URL, make_url

from app.config import PROJECT_ROOT, workspace_path


def root_values():
    values = dotenv_values(workspace_path(PROJECT_ROOT / ".env"))
    expected = "vision-zero-" + hashlib.sha256(str(PROJECT_ROOT).lower().encode()).hexdigest()[:16]
    lock = json.loads((PROJECT_ROOT / "validation/m0/database-image.lock.json").read_text(encoding="utf-8"))
    if (values.get("VISION_ZERO_WORKSPACE_ID") != expected
            or values.get("VISION_ZERO_DATABASE_NAME") != "vision_zero_dev"
            or values.get("VISION_ZERO_DB_IMAGE") != lock["local_image_id"]
            or not (values.get("POSTGRES_PASSWORD") and len(values["POSTGRES_PASSWORD"]) >= 32)
            or not 1024 <= int(values.get("VISION_ZERO_DB_PORT") or "0") <= 65535):
        raise ValueError("本机维护配置不符合项目边界。")
    return values


def admin_connect(database="vision_zero_dev", *, autocommit=False):
    if database != "vision_zero_dev" and not re.fullmatch(r"vision_zero_m1_test_[0-9a-f]{12}", database):
        raise ValueError("维护目标不符合项目边界。")
    values = root_values()
    assert_local_container(values)
    return psycopg.connect(host="127.0.0.1", port=int(values["VISION_ZERO_DB_PORT"]),
                          dbname=database, user="postgres", password=values["POSTGRES_PASSWORD"],
                          connect_timeout=3, autocommit=autocommit)


def assert_local_container(values):
    """实际维护执行层校验容器，不依赖操作者选择PowerShell包装入口。"""
    if any(os.getenv(key) for key in ('DOCKER_HOST', 'DOCKER_CONTEXT', 'DOCKER_TLS_VERIFY', 'DOCKER_CERT_PATH')):
        raise ValueError("Docker目标覆盖不被允许。")
    def run(arguments):
        result = subprocess.run(['docker', *arguments], capture_output=True, text=True, encoding='utf-8', timeout=10)
        if result.returncode:
            raise ValueError("本机Docker资源无法核对。")
        return result.stdout.strip()
    context = run(['context', 'show'])
    endpoint = run(['context', 'inspect', '--format', '{{.Endpoints.docker.Host}}', context])
    if endpoint not in ('npipe:////./pipe/dockerDesktopLinuxEngine', 'npipe:////./pipe/docker_engine'):
        raise ValueError("维护只允许本机Docker命名管道引擎。")
    container = json.loads(run(['inspect', 'vision-zero-dev-db']))[0]
    volume = json.loads(run(['volume', 'inspect', 'vision-zero-dev-postgis-data']))[0]
    volume_labels = volume.get('Labels') or {}
    labels = container['Config'].get('Labels') or {}
    bindings = container['HostConfig'].get('PortBindings') or {}
    mounts = container.get('Mounts') or []
    environment = container['Config'].get('Env') or []
    if (not container['State']['Running']
            or volume.get('Name') != 'vision-zero-dev-postgis-data'
            or volume_labels.get('vision-zero.scope') != 'development'
            or volume_labels.get('vision-zero.workspace') != values['VISION_ZERO_WORKSPACE_ID']
            or container['Image'] != values['VISION_ZERO_DB_IMAGE']
            or labels.get('vision-zero.scope') != 'development'
            or labels.get('vision-zero.workspace') != values['VISION_ZERO_WORKSPACE_ID']
            or bindings != {'5432/tcp': [{'HostIp': '127.0.0.1', 'HostPort': values['VISION_ZERO_DB_PORT']}]}
            or len(mounts) != 1 or mounts[0].get('Type') != 'volume'
            or mounts[0].get('Name') != 'vision-zero-dev-postgis-data'
            or mounts[0].get('Destination') != '/var/lib/postgresql/data' or not mounts[0].get('RW')
            or 'POSTGRES_USER=postgres' not in environment
            or 'POSTGRES_DB=vision_zero_dev' not in environment
            or 'POSTGRES_PASSWORD=' + values['POSTGRES_PASSWORD'] not in environment):
        raise ValueError("本机容器身份与批准配置不一致。")



def write_config(path: Path, values: dict, *, exclusive=False):
    path = workspace_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    content = "".join(f"{key}={value}\n" for key, value in values.items() if value is not None)
    if exclusive:
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
    else:
        temporary = workspace_path(path.with_suffix(path.suffix + ".pending"))
        with temporary.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
        workspace_path(path)
        temporary.replace(path)


def provision(*, database="vision_zero_dev") -> Path:
    root = root_values()
    is_test = bool(re.fullmatch(r"vision_zero_m1_test_[0-9a-f]{12}", database))
    if database != "vision_zero_dev" and not is_test:
        raise ValueError("维护目标不符合项目边界。")
    directory = workspace_path(PROJECT_ROOT / ".m1-work/model")
    target = directory / (database + ".env") if is_test else PROJECT_ROOT / ".env"
    saved = workspace_path(directory / (database + "-provision.env"))
    if saved.exists():
        values = dict(dotenv_values(saved))
        for key in ("POSTGRES_PASSWORD", "VISION_ZERO_WORKSPACE_ID", "VISION_ZERO_DB_PORT"):
            if values.get(key) != root.get(key):
                raise ValueError("保留的角色配置与当前工作区不符。")
    else:
        values = dict(root)
        values["VISION_ZERO_DATABASE_NAME"] = database
        for kind, key in (("app", "VISION_ZERO_DATABASE_URL"),
                          ("migrator", "VISION_ZERO_MIGRATION_DATABASE_URL"),
                          ("worker", "VISION_ZERO_WORKER_DATABASE_URL")):
            url = URL.create("postgresql+psycopg", username=database + "_" + kind,
                             password=secrets.token_hex(48), host="127.0.0.1",
                             port=int(root["VISION_ZERO_DB_PORT"]), database=database)
            values[key] = url.render_as_string(hide_password=False)
        values["VISION_ZERO_JWT_SECRET"] = secrets.token_hex(48)
        values["VISION_ZERO_JWT_MINUTES"] = "15"
        write_config(saved, values, exclusive=True)
    urls = [make_url(values[key]) for key in (
        "VISION_ZERO_MIGRATION_DATABASE_URL", "VISION_ZERO_DATABASE_URL", "VISION_ZERO_WORKER_DATABASE_URL")]
    for url, kind in zip(urls, ("migrator", "app", "worker")):
        if (url.drivername != "postgresql+psycopg" or url.host != "127.0.0.1"
                or url.port != int(root["VISION_ZERO_DB_PORT"]) or url.database != database
                or url.username != database + "_" + kind or not url.password or len(url.password) < 32 or url.query):
            raise ValueError("保留的角色配置无效。")
    with admin_connect(database) as connection:
        connection.execute("SELECT pg_advisory_xact_lock(76301001)")
        for url in urls:
            marker = root["VISION_ZERO_WORKSPACE_ID"] + ":" + database
            existing = connection.execute("""SELECT rolsuper, rolcreatedb, rolcreaterole,
                rolreplication, rolbypassrls, rolcanlogin, shobj_description(oid, 'pg_authid')
                FROM pg_roles WHERE rolname = %s""", (url.username,)).fetchone()
            if existing:
                if existing != (False, False, False, False, False, True, marker):
                    raise ValueError("同名角色不符合项目归属或权限要求，停止配置。")
                memberships = connection.execute("""SELECT count(*) FROM pg_auth_members
                    WHERE member = (SELECT oid FROM pg_roles WHERE rolname = %s)
                       OR roleid = (SELECT oid FROM pg_roles WHERE rolname = %s)""", (url.username, url.username)).fetchone()[0]
                if memberships:
                    raise ValueError("专用角色存在非预期成员关系。")
            else:
                connection.execute(sql.SQL("CREATE ROLE {} LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD {}").format(sql.Identifier(url.username), sql.Literal(url.password)))
                connection.execute(sql.SQL("COMMENT ON ROLE {} IS {}").format(sql.Identifier(url.username), sql.Literal(marker)))
            connection.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(sql.Identifier(database), sql.Identifier(url.username)))
            connection.execute(sql.SQL("ALTER ROLE {} IN DATABASE {} SET search_path = pg_catalog, public").format(sql.Identifier(url.username), sql.Identifier(database)))
        connection.execute(sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(sql.Identifier(database)))
        migrator = urls[0].username
        connection.execute(sql.SQL("ALTER SCHEMA public OWNER TO {}").format(sql.Identifier(migrator)))
        connection.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
        connection.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}, {}").format(sql.Identifier(urls[1].username), sql.Identifier(urls[2].username)))
        for schema in ("tiger", "tiger_data", "topology"):
            if connection.execute("SELECT 1 FROM pg_namespace WHERE nspname = %s", (schema,)).fetchone():
                connection.execute(sql.SQL("REVOKE ALL ON SCHEMA {} FROM PUBLIC").format(sql.Identifier(schema)))
        if connection.execute("SELECT to_regclass('public.alembic_version')").fetchone()[0]:
            owner = connection.execute("SELECT pg_get_userbyid(relowner) FROM pg_class WHERE oid = 'public.alembic_version'::regclass").fetchone()[0]
            if owner not in ("postgres", migrator):
                raise ValueError("迁移版本表所有者不符合项目边界。")
            connection.execute(sql.SQL("ALTER TABLE public.alembic_version OWNER TO {}").format(sql.Identifier(migrator)))
    if not is_test:
        backup = directory / "before-role-provision.env"
        if not backup.exists():
            write_config(backup, root, exclusive=True)
    write_config(target, values)
    return target
