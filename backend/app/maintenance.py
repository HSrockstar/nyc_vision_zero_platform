"""本机备份与隔离恢复；开发库只读，既有恢复目标一律拒绝。"""

from contextlib import contextmanager
import csv
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

from alembic import command
from alembic.config import Config
from dotenv import dotenv_values
import psycopg
from psycopg import sql

from app.config import BACKEND_ROOT, PROJECT_ROOT, Settings, workspace_path
from app.db.base import Base
from app.db.provision import admin_connect, assert_local_container, provision, root_values
from app import models  # noqa: F401：注册完整业务模型。


FORMAT = "vision-zero-backup-v1"
TEST_NAME = re.compile(r"vision_zero_m1_test_[0-9a-f]{12}")
TABLES = tuple(sorted(Base.metadata.tables))
CONTAINER = "vision-zero-dev-db"


class MaintenanceError(ValueError):
    """只包含可公开的固定错误码，不携带驱动异常或敏感数据。"""


def require_database(name, *, target=False):
    if not TEST_NAME.fullmatch(name) and (target or name != "vision_zero_dev"):
        raise MaintenanceError("DATABASE_NOT_ALLOWED")
    return name


def bundle_path(path, *, create=False):
    path = Path(path)
    path = workspace_path(path if path.is_absolute() else PROJECT_ROOT / path)
    parent = workspace_path(PROJECT_ROOT / ".m7-work/backups")
    if path.parent != parent or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", path.name):
        raise MaintenanceError("BACKUP_PATH_NOT_ALLOWED")
    if create:
        parent.mkdir(parents=True, exist_ok=True)
        path.mkdir(exist_ok=False)
        protect_directory(path)
    elif not path.is_dir():
        raise MaintenanceError("BACKUP_NOT_FOUND")
    return path


def protect_directory(path):
    """仅收紧本工具新建的备份目录；Windows使用当前SID，其他系统仅所有者访问。"""
    path = workspace_path(path)
    if os.name != "nt":
        path.chmod(0o700)
        return
    identity = subprocess.run(["whoami", "/user", "/fo", "csv", "/nh"],
                              capture_output=True, text=True, timeout=10)
    if identity.returncode:
        raise MaintenanceError("BACKUP_ACCESS_PROTECTION_FAILED")
    rows = list(csv.reader(identity.stdout.strip().splitlines()))
    sid = rows[0][-1] if len(rows) == 1 and rows[0] else ""
    if not re.fullmatch(r"S-1-(?:[0-9]+-)*[0-9]+", sid):
        raise MaintenanceError("BACKUP_ACCESS_PROTECTION_FAILED")
    result = subprocess.run(["icacls", str(path), "/inheritance:r", "/grant:r",
                             "*" + sid + ":(OI)(CI)F", "*S-1-5-18:(OI)(CI)F"],
                            capture_output=True, timeout=10)
    if result.returncode:
        raise MaintenanceError("BACKUP_ACCESS_PROTECTION_FAILED")


def write_json(path, value):
    with workspace_path(path).open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, default=str, allow_nan=False)
        stream.write("\n")


def sha256(path):
    digest = hashlib.sha256()
    with workspace_path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def migration_files():
    paths = [BACKEND_ROOT / "alembic.ini"]
    paths += [p for p in (BACKEND_ROOT / "migrations").rglob("*") if p.suffix in {".py", ".sql"}]
    return {p.relative_to(PROJECT_ROOT).as_posix(): sha256(p) for p in sorted(paths)}


def git_revision():
    result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT,
                            capture_output=True, text=True, timeout=10)
    if result.returncode:
        raise MaintenanceError("GIT_REVISION_UNAVAILABLE")
    return result.stdout.strip()


def table_summary(connection):
    result = {}
    for name in TABLES:
        # 排序后的逐行摘要不依赖物理行序；仅摘要出库，不输出业务记录。
        count, digest = connection.execute(sql.SQL("""
            SELECT count(*), encode(sha256(convert_to(COALESCE(string_agg(h, '' ORDER BY h), ''),
                'UTF8')), 'hex') FROM (
                SELECT encode(sha256(convert_to(row_to_json(t)::text, 'UTF8')), 'hex') AS h
                FROM public.{} t) rows
        """).format(sql.Identifier(name))).fetchone()
        result[name] = {"rows": count, "sha256": digest}
    return result


def schema_summary(connection):
    queries = {
        "columns": """SELECT c.relname,a.attname,format_type(a.atttypid,a.atttypmod),a.attnotnull,
            a.attidentity,pg_get_expr(d.adbin,d.adrelid) FROM pg_class c
            JOIN pg_namespace n ON n.oid=c.relnamespace JOIN pg_attribute a ON a.attrelid=c.oid
            LEFT JOIN pg_attrdef d ON d.adrelid=c.oid AND d.adnum=a.attnum
            WHERE n.nspname='public' AND c.relname=ANY(%s) AND a.attnum>0 AND NOT a.attisdropped
            ORDER BY c.relname,a.attnum""",
        "constraints": """SELECT c.relname,k.conname,k.contype,pg_get_constraintdef(k.oid),k.convalidated
            FROM pg_constraint k JOIN pg_class c ON c.oid=k.conrelid
            WHERE c.relnamespace='public'::regnamespace AND c.relname=ANY(%s)
            ORDER BY c.relname,k.conname""",
        "indexes": """SELECT tablename,indexname,indexdef FROM pg_indexes
            WHERE schemaname='public' AND tablename=ANY(%s) ORDER BY tablename,indexname""",
        "triggers": """SELECT c.relname,t.tgname,pg_get_triggerdef(t.oid),t.tgenabled
            FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid
            WHERE c.relnamespace='public'::regnamespace AND c.relname=ANY(%s) AND NOT t.tgisinternal
            ORDER BY c.relname,t.tgname""",
    }
    result = {key: [list(row) for row in connection.execute(query, (list(TABLES),))]
              for key, query in queries.items()}
    result["views"] = [list(row) for row in connection.execute("""
        SELECT viewname,definition FROM pg_views WHERE schemaname='public' AND viewname LIKE 'v_%'
        ORDER BY viewname""")]
    result["functions"] = [list(row) for row in connection.execute("""
        SELECT p.proname,pg_get_function_identity_arguments(p.oid),pg_get_functiondef(p.oid)
        FROM pg_proc p WHERE p.pronamespace='public'::regnamespace AND p.proname LIKE 'vz_%'
        ORDER BY p.proname,pg_get_function_identity_arguments(p.oid)""")]
    result["extensions"] = [list(row) for row in connection.execute(
        "SELECT extname,extversion FROM pg_extension ORDER BY extname")]
    result["migration"] = connection.execute("SELECT version_num FROM public.alembic_version").fetchone()[0]
    return result


def sequence_summary(connection):
    result = {}
    for name, in connection.execute("""SELECT c.relname FROM pg_class c
        WHERE c.relnamespace='public'::regnamespace AND c.relkind='S' ORDER BY c.relname"""):
        result[name] = list(connection.execute(sql.SQL("SELECT last_value,is_called FROM public.{}")
                                              .format(sql.Identifier(name))).fetchone())
    return result


def aggregate_summary(connection):
    return {
        "revision": connection.execute("SELECT revision FROM dataset_state WHERE state_id=1").fetchone()[0],
        "casualties": list(connection.execute("""SELECT sum(persons_injured),sum(persons_killed),
            count(*) FILTER (WHERE persons_injured IS NULL),count(*) FILTER (WHERE persons_killed IS NULL)
            FROM casualty_stat""").fetchone()),
        "risk_levels": [list(row) for row in connection.execute(
            "SELECT risk_level,count(*) FROM v_risk_profile GROUP BY risk_level ORDER BY risk_level")],
        "tasks": [list(row) for row in connection.execute(
            "SELECT status,count(*) FROM governance_task GROUP BY status ORDER BY status")],
    }


def snapshot(connection):
    connection.execute("SET LOCAL statement_timeout='180s'")
    connection.execute("SET LOCAL timezone='UTC'")
    return {"tables": table_summary(connection), "schema": schema_summary(connection),
            "sequences": sequence_summary(connection), "aggregates": aggregate_summary(connection)}


def file_references(connection, database):
    files = {}
    for manifest, in connection.execute("SELECT input_manifest FROM import_batch ORDER BY batch_id"):
        key = manifest.get("storage_key", "")
        if not re.fullmatch(r"[0-9a-f]{32}", key):
            raise MaintenanceError("IMPORT_FILE_REFERENCE_INVALID")
        for item in manifest["files"]:
            kind = item["source_kind"]
            if kind not in {"CRASHES", "PERSON", "VEHICLES"}:
                raise MaintenanceError("IMPORT_FILE_REFERENCE_INVALID")
            relative = f"raw/{key}/{kind}.csv"
            files[relative] = (workspace_path(PROJECT_ROOT / "data/raw" / database / key / f"{kind}.csv"),
                               item["sha256"], item["bytes"])
    for manifest, in connection.execute("SELECT input_manifest FROM risk_run WHERE status='SUCCEEDED' ORDER BY run_id"):
        reference = manifest.get("snapshot")
        if not reference:
            raise MaintenanceError("RISK_SNAPSHOT_REFERENCE_MISSING")
        key = reference.get("storage_key", "")
        if not re.fullmatch(r"[0-9a-f]{32}", key):
            raise MaintenanceError("RISK_SNAPSHOT_REFERENCE_INVALID")
        files[f"snapshots/{key}.json"] = (workspace_path(PROJECT_ROOT / ".m4-work/snapshots" / database / f"{key}.json"),
                                          reference["sha256"], reference["bytes"])
    return files


def copy_checked(source, target, digest, size):
    if not source.is_file() or source.stat().st_size != size or sha256(source) != digest:
        raise MaintenanceError("EXTERNAL_FILE_HASH_MISMATCH")
    target = workspace_path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    with source.open("rb") as src, target.open("xb") as dst:
        shutil.copyfileobj(src, dst)
    if sha256(target) != digest:
        raise MaintenanceError("COPIED_FILE_HASH_MISMATCH")


def docker_command(arguments, *, stdin=None, stdout=None, stderr):
    assert_local_container(root_values())
    result = subprocess.run(["docker", "exec", "-i", CONTAINER, *arguments], stdin=stdin,
                            stdout=stdout, stderr=stderr, timeout=1800)
    if result.returncode:
        raise MaintenanceError("POSTGRES_TOOL_FAILED")


def backup_database(output, *, database="vision_zero_dev"):
    require_database(database)
    bundle = bundle_path(output, create=True)
    manifest = {"format": FORMAT, "database": database, "created_at": datetime.now(timezone.utc).isoformat(),
                "git_commit": git_revision(), "migration_files": migration_files(), "files": {}, "source_files": {}}
    # 导出快照在pg_dump结束前保持打开；明细、外部引用、摘要均从同一快照读取。
    with admin_connect(database) as connection:
        connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        busy = connection.execute("""SELECT (SELECT count(*) FROM import_batch
            WHERE status IN ('UPLOADED','VALIDATING','READY','PUBLISHING')) +
            (SELECT count(*) FROM risk_run WHERE status IN ('QUEUED','RUNNING'))""").fetchone()[0]
        if busy:
            raise MaintenanceError("QUIESCENT_BACKUP_REQUIRED")
        exported = connection.execute("SELECT pg_export_snapshot()").fetchone()[0]
        manifest["snapshot"] = snapshot(connection)
        with (bundle / "database.dump").open("xb") as dump, (bundle / "dump-stderr.log").open("xb") as errors:
            docker_command(["pg_dump", "-U", "postgres", "-d", database, "--format=custom", "--schema=public",
                            "--no-owner", "--no-acl", "--snapshot=" + exported,
                            "--exclude-table-data=public.alembic_version",
                            "--exclude-table-data=public.spatial_ref_sys"], stdout=dump, stderr=errors)
        for relative, (source, digest, size) in file_references(connection, database).items():
            copy_checked(source, bundle / "files" / relative, digest, size)
            manifest["files"][relative] = {"sha256": digest, "bytes": size}
        # 序列不遵循MVCC；有并行写入时拒绝把本轮备份标为可恢复完成。
        if sequence_summary(connection) != manifest["snapshot"]["sequences"]:
            raise MaintenanceError("SOURCE_CHANGED_DURING_BACKUP")
    manifest["dump_sha256"] = sha256(bundle / "database.dump")
    manifest["dump_bytes"] = (bundle / "database.dump").stat().st_size
    # 额外保留迁移和依赖，便于按相同版本重建，不复制.env或密钥。
    paths = [PROJECT_ROOT / path for path in manifest["migration_files"]]
    paths += list(BACKEND_ROOT.glob("requirements*")) + [BACKEND_ROOT / "pyproject.toml"]
    paths += list((PROJECT_ROOT / "validation/m0").glob("*.lock*"))
    for source in sorted(set(paths)):
        if source.is_file():
            relative = source.relative_to(PROJECT_ROOT).as_posix()
            digest, size = sha256(source), source.stat().st_size
            copy_checked(source, bundle / "source" / relative, digest, size)
            manifest["source_files"][relative] = {"sha256": digest, "bytes": size}
    write_json(bundle / "manifest.json", manifest)  # 最后写manifest代表完整成功。
    return {"status": "completed", "database": database, "bundle": str(bundle),
            "dump_bytes": manifest["dump_bytes"], "external_files": len(manifest["files"]),
            "table_counts": {k: v["rows"] for k, v in manifest["snapshot"]["tables"].items()}}


@contextmanager
def isolated_environment(config):
    values = {k: v for k, v in dotenv_values(config).items() if k.startswith("VISION_ZERO_")}
    values.update(VISION_ZERO_RUN_DB_TESTS="1", VISION_ZERO_TEST_CONFIG_FILE=str(config))
    old = {k: os.environ.get(k) for k in values}
    os.environ.update(values)
    try:
        yield values
    finally:
        for key, value in old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def new_database(database, *, extensions=("plpgsql", "postgis")):
    require_database(database, target=True)
    if not set(extensions) <= {"plpgsql", "postgis", "fuzzystrmatch", "postgis_topology", "postgis_tiger_geocoder"}:
        raise MaintenanceError("EXTENSION_NOT_ALLOWED")
    # 目标的数据库、凭据和文件空间都必须全新；不以--force绕过。
    for path in (PROJECT_ROOT / ".m1-work/model" / (database + ".env"),
                 PROJECT_ROOT / ".m1-work/model" / (database + "-provision.env"),
                 PROJECT_ROOT / "data/raw" / database, PROJECT_ROOT / ".m4-work/snapshots" / database,
                 PROJECT_ROOT / ".m7-work/restores" / database, PROJECT_ROOT / ".m8-work/demo" / database):
        if workspace_path(path).exists():
            raise MaintenanceError("TARGET_ALREADY_EXISTS")
    with admin_connect(autocommit=True) as connection:
        if connection.execute("SELECT 1 FROM pg_database WHERE datname=%s", (database,)).fetchone():
            raise MaintenanceError("TARGET_ALREADY_EXISTS")
        if connection.execute("SELECT 1 FROM pg_roles WHERE rolname=ANY(%s)",
                              ([database + "_" + kind for kind in ("app", "migrator", "worker")],)).fetchone():
            raise MaintenanceError("TARGET_ROLE_ALREADY_EXISTS")
        connection.execute(sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(sql.Identifier(database)))
    with admin_connect(database) as connection:
        for extension in ("postgis", "fuzzystrmatch", "postgis_topology", "postgis_tiger_geocoder"):
            if extension in extensions:
                connection.execute(sql.SQL("CREATE EXTENSION {}").format(sql.Identifier(extension)))
    config = provision(database=database)
    with isolated_environment(config):
        command.upgrade(Config(str(BACKEND_ROOT / "alembic.ini")), "head")
    return config


def foreign_key_check(connection):
    failures = []
    keys = connection.execute("""SELECT c.relname,p.relname,k.conname,
        ARRAY(SELECT a.attname FROM unnest(k.conkey) WITH ORDINALITY x(n,o)
            JOIN pg_attribute a ON a.attrelid=k.conrelid AND a.attnum=x.n ORDER BY x.o),
        ARRAY(SELECT a.attname FROM unnest(k.confkey) WITH ORDINALITY x(n,o)
            JOIN pg_attribute a ON a.attrelid=k.confrelid AND a.attnum=x.n ORDER BY x.o)
        FROM pg_constraint k JOIN pg_class c ON c.oid=k.conrelid JOIN pg_class p ON p.oid=k.confrelid
        WHERE k.contype='f' AND c.relnamespace='public'::regnamespace ORDER BY c.relname,k.conname""").fetchall()
    for child, parent, name, child_columns, parent_columns in keys:
        present = sql.SQL(" AND ").join(sql.SQL("c.{} IS NOT NULL").format(sql.Identifier(c)) for c in child_columns)
        equal = sql.SQL(" AND ").join(sql.SQL("p.{}=c.{}").format(sql.Identifier(p), sql.Identifier(c))
                                    for c, p in zip(child_columns, parent_columns))
        count = connection.execute(sql.SQL("SELECT count(*) FROM public.{} c WHERE {} AND NOT EXISTS"
            " (SELECT 1 FROM public.{} p WHERE {})").format(sql.Identifier(child), present,
                                                          sql.Identifier(parent), equal)).fetchone()[0]
        if count:
            failures.append({"constraint": name, "orphans": count})
    return {"checked": len(keys), "failures": failures}


def permission_check(connection, database):
    app, worker, migrator = [database + "_" + kind for kind in ("app", "worker", "migrator")]
    checks = {
        "app_can_read_collision": connection.execute("SELECT has_table_privilege(%s,'collision','SELECT')", (app,)).fetchone()[0],
        "app_cannot_write_collision": not connection.execute("SELECT has_table_privilege(%s,'collision','INSERT')", (app,)).fetchone()[0],
        "app_cannot_write_task": not connection.execute("SELECT has_table_privilege(%s,'governance_task','UPDATE')", (app,)).fetchone()[0],
        "worker_cannot_read_password": not connection.execute("SELECT has_column_privilege(%s,'app_user','password_hash','SELECT')", (worker,)).fetchone()[0],
        "worker_cannot_write_task": not connection.execute("SELECT has_table_privilege(%s,'governance_task','INSERT')", (worker,)).fetchone()[0],
        "roles_not_superuser": connection.execute("""SELECT count(*)=3 AND bool_and(NOT rolsuper AND NOT rolcreatedb
            AND NOT rolcreaterole AND NOT rolbypassrls) FROM pg_roles WHERE rolname=ANY(%s)""", ([app, worker, migrator],)).fetchone()[0],
        "definer_owner_is_target": connection.execute("""SELECT count(*)>=3 AND bool_and(pg_get_userbyid(proowner)=%s)
            FROM pg_proc WHERE pronamespace='public'::regnamespace AND left(proname,3)='vz_'
            AND prosecdef""", (migrator,)).fetchone()[0],
        "public_cannot_execute_custom_functions": connection.execute("""SELECT count(*)=0
            FROM pg_proc p CROSS JOIN LATERAL aclexplode(COALESCE(p.proacl,acldefault('f',p.proowner))) a
            WHERE p.pronamespace='public'::regnamespace AND left(p.proname,3)='vz_'
            AND a.grantee=0 AND a.privilege_type='EXECUTE'""").fetchone()[0],
        "runtime_cannot_execute_trigger_functions": connection.execute("""SELECT count(*)>0 AND
            bool_and(NOT has_function_privilege(%s,p.oid,'EXECUTE')
                 AND NOT has_function_privilege(%s,p.oid,'EXECUTE'))
            FROM pg_proc p WHERE p.pronamespace='public'::regnamespace AND left(p.proname,3)='vz_'
            AND p.prorettype='trigger'::regtype""", (app, worker)).fetchone()[0],
        "all_triggers_enabled": connection.execute("""SELECT count(*)=0 FROM pg_trigger
            WHERE tgrelid IN (SELECT oid FROM pg_class WHERE relnamespace='public'::regnamespace)
            AND tgenabled='D'""").fetchone()[0],
    }
    for kind, role in (("app", app), ("worker", worker)):
        granted = connection.execute("""SELECT bool_and(has_function_privilege(%s,p.oid,'EXECUTE')),
            bool_or(has_function_privilege(%s,p.oid,'EXECUTE'))
            FROM pg_proc p WHERE p.pronamespace='public'::regnamespace
            AND p.proname IN ('vz_governance_create','vz_governance_change')""", (role, role)).fetchone()
        checks[kind + "_governance_execute"] = bool(granted[0]) if kind == "app" else not bool(granted[1])
    return checks


def runtime_checks(config, database):
    """独立恢复库的真实角色拒绝路径、健康检查及序列分配；不会接受开发库。"""
    require_database(database, target=True)
    result = {}
    with isolated_environment(config):
        from app.health import readiness
        result["readiness"] = readiness()[1] == 200 and readiness(worker=True)[1] == 200
        for kind, statement in (("app", "INSERT INTO public.governance_task DEFAULT VALUES"),
                                ("worker", "SELECT password_hash FROM public.app_user")):
            url = Settings().connection_url(worker=kind == "worker")
            with psycopg.connect(host=url.host, port=url.port, dbname=url.database, user=url.username,
                                 password=url.password, connect_timeout=3) as connection:
                try:
                    connection.execute(statement)
                except psycopg.errors.InsufficientPrivilege:
                    result[kind + "_denied"] = True
                else:
                    result[kind + "_denied"] = False
                finally:
                    connection.rollback()
    with admin_connect(database) as connection:
        before = sequence_summary(connection)
        valid = True
        try:
            for name in before:
                owned = connection.execute("""SELECT t.relname,a.attname FROM pg_depend d
                    JOIN pg_class s ON s.oid=d.objid JOIN pg_class t ON t.oid=d.refobjid
                    JOIN pg_attribute a ON a.attrelid=t.oid AND a.attnum=d.refobjsubid
                    WHERE d.classid='pg_class'::regclass AND d.refclassid='pg_class'::regclass
                    AND d.deptype IN ('a','i') AND s.relnamespace='public'::regnamespace
                    AND s.relname=%s AND a.attidentity IN ('a','d')""", (name,)).fetchone()
                if owned:
                    # 只探测模型internal_id()声明的IDENTITY；官方源主键及固定角色/行政区
                    # 均由业务显式提供，不能拿它们未使用的SERIAL默认值判定恢复失败。
                    next_value = connection.execute("SELECT nextval(%s::regclass)", ("public." + name,)).fetchone()[0]
                    maximum = connection.execute(sql.SQL("SELECT max({}) FROM public.{}")
                        .format(sql.Identifier(owned[1]), sql.Identifier(owned[0]))).fetchone()[0]
                    valid = valid and (maximum is None or next_value > maximum)
        finally:
            # nextval不随事务回滚；离线隔离库的探针显式恢复本次借用的序列值。
            connection.rollback()
            for name, (value, called) in before.items():
                connection.execute("SELECT setval(%s::regclass,%s,%s)", ("public." + name, value, called))
        result["sequences_allocate_after_max"] = valid
        result["sequence_probe_restored"] = sequence_summary(connection) == before
    return result


def restored_file_target(database, relative):
    if re.fullmatch(r"raw/[0-9a-f]{32}/(CRASHES|PERSON|VEHICLES)\.csv", relative):
        return workspace_path(PROJECT_ROOT / "data/raw" / database / relative.removeprefix("raw/"))
    if re.fullmatch(r"snapshots/[0-9a-f]{32}\.json", relative):
        return workspace_path(PROJECT_ROOT / ".m4-work/snapshots" / database / relative.removeprefix("snapshots/"))
    raise MaintenanceError("BACKUP_FILE_REFERENCE_INVALID")


def restore_database(backup, database):
    require_database(database, target=True)
    bundle = bundle_path(backup)
    manifest = json.loads(workspace_path(bundle / "manifest.json").read_text(encoding="utf-8"))
    if (manifest.get("format") != FORMAT or manifest.get("migration_files") != migration_files()
            or manifest.get("dump_sha256") != sha256(bundle / "database.dump")
            or manifest.get("dump_bytes") != (bundle / "database.dump").stat().st_size):
        raise MaintenanceError("BACKUP_OR_MIGRATION_MISMATCH")
    for relative, item in manifest["files"].items():
        restored_file_target(database, relative)  # 全部预检，之后才创建目标。
        path = workspace_path(bundle / "files" / relative)
        if path.stat().st_size != item["bytes"] or sha256(path) != item["sha256"]:
            raise MaintenanceError("BACKUP_FILE_HASH_MISMATCH")
    for relative, item in manifest.get("source_files", {}).items():
        if not relative.startswith(("backend/", "validation/m0/")) or ".." in Path(relative).parts:
            raise MaintenanceError("BACKUP_SOURCE_REFERENCE_INVALID")
        path = workspace_path(bundle / "source" / relative)
        if path.stat().st_size != item["bytes"] or sha256(path) != item["sha256"]:
            raise MaintenanceError("BACKUP_SOURCE_HASH_MISMATCH")
    config = new_database(database, extensions=[row[0] for row in manifest["snapshot"]["schema"]["extensions"]])
    directory = workspace_path(PROJECT_ROOT / ".m7-work/restores" / database)
    directory.mkdir(parents=True, exist_ok=False)
    with admin_connect(database) as connection:
        if schema_summary(connection) != manifest["snapshot"]["schema"]:
            raise MaintenanceError("SOURCE_SCHEMA_DIFFERS_FROM_MIGRATIONS")
        connection.execute(sql.SQL("TRUNCATE {} RESTART IDENTITY").format(
            sql.SQL(",").join(sql.Identifier("public", name) for name in TABLES)))
    with (bundle / "database.dump").open("rb") as dump, (directory / "restore-stderr.log").open("xb") as errors, \
            (directory / "restore-stdout.log").open("xb") as output:
        docker_command(["pg_restore", "-U", "postgres", "-d", database, "--data-only", "--no-owner",
                        "--no-acl", "--disable-triggers", "--single-transaction", "--exit-on-error"],
                       stdin=dump, stdout=output, stderr=errors)
    for relative, item in manifest["files"].items():
        copy_checked(bundle / "files" / relative, restored_file_target(database, relative), item["sha256"], item["bytes"])
    with admin_connect(database) as connection:
        connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        actual = snapshot(connection)
        checks = {key: actual[key] == manifest["snapshot"][key] for key in actual}
        fk = foreign_key_check(connection)
        permissions = permission_check(connection, database)
        references = file_references(connection, database)
        checks["external_file_references"] = {key: {"sha256": digest, "bytes": size}
            for key, (_, digest, size) in references.items()} == manifest["files"]
    runtime = runtime_checks(config, database)
    result = {"status": "completed" if all(checks.values()) and not fk["failures"] and all(permissions.values()) and all(runtime.values()) else "failed",
              "database": database, "source_database": manifest["database"], "backup_sha256": manifest["dump_sha256"],
              "checks": checks, "foreign_keys": fk, "permissions": permissions,
              "runtime": runtime,
              "snapshot": actual, "external_files": len(manifest["files"]),
              "retained_for_review": True}
    write_json(directory / "verification.json", result)
    if result["status"] != "completed":
        raise MaintenanceError("RESTORE_VERIFICATION_FAILED")
    return {"status": "completed", "database": database, "verification": str(directory / "verification.json"),
            "config_file": str(config), "external_files": len(manifest["files"])}
