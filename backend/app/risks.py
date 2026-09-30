"""M4一致性读取、受控文件快照与整批原子发布。"""

from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import os
from threading import Event, Thread
from uuid import uuid4

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.auth import ACCOUNT_LOCK, fail
from app.config import PROJECT_ROOT, Settings, workspace_path
from app.contracts import request_digest
from app.db.connection import database_engine
from app.models import AppUser, AuditLog, RiskProfile, RiskRule, RiskRun
from app.risk_sql import AGGREGATES, BASE, COVERAGE, MAPPING

LEASE = text("interval '120 seconds'")
VERSION = "m4-snapshot-v1"


class RiskProblem(Exception):
    pass


def audit(session, actor, action, run_id, request_id, details=None):
    session.add(AuditLog(actor_id=actor, action=action, entity_type="risk_run",
                         entity_id=str(run_id), request_id=request_id, details=details or {}))


def create_run(session, actor, request_id, rule_id, start, end):
    if start >= end:
        fail(422, "INVALID_RANGE", "结束日期必须晚于开始日期，结束日期不包含在范围内。")
    session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": ACCOUNT_LOCK})
    current = session.execute(select(AppUser.role_id, AppUser.is_active).where(
        AppUser.user_id == actor.user_id)).one()
    if current.role_id not in (1, 2) or not current.is_active:
        fail(403, "FORBIDDEN", "当前账户不能创建风险计算。")
    digest = request_digest(actor_id=str(actor.user_id), operation="RISK_CREATE", target_id=None,
                            payload={"rule_id": str(rule_id), "start": start.isoformat(), "end": end.isoformat()})
    old = session.scalar(select(RiskRun).where(RiskRun.request_id == request_id))
    if old:
        if old.request_hash != digest:
            fail(409, "REQUEST_CONTENT_CONFLICT", "此请求编号已经用于另一计算内容。")
        return old
    rule = session.scalar(select(RiskRule).where(RiskRule.rule_id == rule_id, RiskRule.status == "PUBLISHED"))
    if rule is None:
        fail(422, "RULE_NOT_PUBLISHED", "请选择已发布的规则版本。")
    run = RiskRun(request_id=request_id, request_hash=digest, rule_id=rule_id, period_start=start,
                  period_end=end, requested_by=actor.user_id, status="QUEUED")
    session.add(run)
    session.flush()
    audit(session, actor.user_id, "RISK_REQUESTED", run.run_id, request_id)
    return run


def leased(session, run_id, token):
    run = session.scalar(select(RiskRun).where(RiskRun.run_id == run_id, RiskRun.status == "RUNNING",
        RiskRun.worker_token == token, RiskRun.lease_expires_at > func.clock_timestamp()).with_for_update())
    if run is None:
        raise RiskProblem("RISK_LEASE_LOST")
    return run


def heartbeat(engine, run_id, token):
    with Session(engine) as session, session.begin():
        run = leased(session, run_id, token)
        run.lease_expires_at = func.clock_timestamp() + LEASE


def claim(engine):
    with Session(engine, expire_on_commit=False) as session, session.begin():
        expired = session.scalars(select(RiskRun).where(RiskRun.status == "RUNNING",
            RiskRun.lease_expires_at <= func.clock_timestamp()).with_for_update(skip_locked=True).limit(100)).all()
        for run in expired:
            run.status = "FAILED"
            run.finished_at = datetime.now(timezone.utc)
            run.error_summary = "RISK_LEASE_EXPIRED：租约已过期，请使用新的请求编号重新计算。"
            run.worker_token = run.lease_expires_at = None
            audit(session, None, "RISK_LEASE_EXPIRED", run.run_id, uuid4())
        run = session.scalar(select(RiskRun).where(RiskRun.status == "QUEUED").order_by(
            RiskRun.run_id).with_for_update(skip_locked=True).limit(1))
        if run is None:
            return None
        run.status = "RUNNING"
        run.started_at = datetime.now(timezone.utc)
        run.worker_token = uuid4()
        run.lease_expires_at = func.clock_timestamp() + LEASE
        run.attempt_no += 1
        session.flush()
        return run.run_id, run.worker_token


def json_value(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError("快照包含不支持的类型")


def snapshot_path(key):
    if len(key) != 32 or any(char not in "0123456789abcdef" for char in key):
        raise RiskProblem("RISK_SNAPSHOT_REFERENCE_INVALID")
    settings = Settings()
    settings.connection_url(worker=True)
    return workspace_path(PROJECT_ROOT / ".m4-work/snapshots" / settings.database_name / (key + ".json"))


def write_snapshot(payload):
    key = uuid4().hex
    path = snapshot_path(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                         default=json_value, allow_nan=False).encode("utf-8")
    temporary = workspace_path(path.with_suffix(".pending"))
    with temporary.open("xb") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
    workspace_path(path)
    temporary.replace(path)
    return {"storage_key": key, "sha256": hashlib.sha256(content).hexdigest(), "bytes": len(content),
            "profile_rows": len(payload["profiles"]), "mapping_rows": len(payload["mapping"]),
            "included_collision_rows": len(payload["included_inputs"]), "format": VERSION}


def read_snapshot(reference):
    content = snapshot_path(reference["storage_key"]).read_bytes()
    if len(content) != reference["bytes"] or hashlib.sha256(content).hexdigest() != reference["sha256"]:
        raise RiskProblem("RISK_SNAPSHOT_HASH_MISMATCH")
    payload = json.loads(content)
    if (payload["format"] != VERSION or len(payload["profiles"]) != reference["profile_rows"]
            or len(payload["mapping"]) != reference["mapping_rows"]
            or len(payload["included_inputs"]) != reference["included_collision_rows"]):
        raise RiskProblem("RISK_SNAPSHOT_CONTENT_INVALID")
    return payload


def calculate(engine, run_id, token):
    # 整个读取事务只读；租约心跳使用另一连接，避免修改快照中的运行行。
    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as connection, connection.begin():
        connection.execute(text("SET TRANSACTION READ ONLY"))
        connection.execute(text("SET LOCAL statement_timeout = '60s'"))
        run = connection.execute(text("SELECT rule_id,period_start,period_end FROM public.risk_run WHERE run_id=:id"),
                                 {"id": run_id}).one()
        revision = connection.scalar(text("SELECT revision FROM public.dataset_state WHERE state_id=1"))
        rule = dict(connection.execute(text("""SELECT rule_id,rule_code,version_no,rule_name,weight_collision,
            weight_injured,weight_killed,weight_vru,threshold_medium,threshold_high,rationale,status
            FROM public.risk_rule WHERE rule_id=:id"""), {"id": run.rule_id}).one()._mapping)
        if rule["status"] != "PUBLISHED":
            raise RiskProblem("RISK_RULE_NO_LONGER_PUBLISHED")
        params = {"start": run.period_start, "end": run.period_end}
        profiles = [dict(row) for row in connection.execute(text(AGGREGATES), params).mappings()]
        coverage = dict(connection.execute(text(COVERAGE), params).one()._mapping)
        coverage["coverage_ratio"] = coverage["included"] / coverage["total"] if coverage["total"] else None
        coverage["confirmed_intersections"] = connection.scalar(text(
            "SELECT count(*) FROM public.intersection WHERE status='CONFIRMED' AND is_active"))
        mapping = [dict(row) for row in connection.execute(text(MAPPING), params).mappings()]
        inputs = [dict(row) for row in connection.execute(text("WITH base AS (" + BASE +
            ") SELECT * FROM base WHERE intersection_id IS NOT NULL ORDER BY collision_id"), params).mappings()]
        sources = [dict(row) for row in connection.execute(text("""
            SELECT DISTINCT b.batch_id,rr.source_kind,b.cleaning_version,b.published_revision,b.input_manifest
            FROM public.import_batch b JOIN public.raw_record rr ON rr.batch_id=b.batch_id
              JOIN public.collision c ON c.source_record_id=rr.raw_record_id
            WHERE c.crash_date >= :start AND c.crash_date < :end ORDER BY b.batch_id
        """), params).mappings()]
        # 文件hash与映射在同一数据快照内取得；只保留来源元数据，不复制人员明细。
        source_manifest = [{"batch_id": str(row["batch_id"]), "source_kind": row["source_kind"],
            "cleaning_version": row["cleaning_version"], "published_revision": str(row["published_revision"]),
            "files": [{key: file[key] for key in ("source_kind", "dataset_id", "sha256", "bytes")}
                      for file in row["input_manifest"].get("files", [])]} for row in sources]
        code_hashes = {name: hashlib.sha256((PROJECT_ROOT / "backend/app" / name).read_bytes()).hexdigest()
                       for name in ("risks.py", "risk_sql.py")}
        code_hashes["0002_views.sql"] = hashlib.sha256((PROJECT_ROOT /
            "backend/migrations/sql/0002_views.sql").read_bytes()).hexdigest()
        view_definition = connection.scalar(text("SELECT pg_get_viewdef('public.v_risk_profile'::regclass,true)"))
        code_hashes["v_risk_profile"] = hashlib.sha256(view_definition.encode()).hexdigest()
        payload = {"format": VERSION, "run_id": str(run_id), "worker_token": str(token),
            "period_start": run.period_start.isoformat(), "period_end": run.period_end.isoformat(),
            "input_revision": str(revision), "rule": rule, "coverage": coverage, "profiles": profiles,
            "mapping": mapping, "included_inputs": inputs, "sources": source_manifest,
            "code_hashes": code_hashes, "view_definition": view_definition}
        reference = write_snapshot(payload)
    return reference


def publish(engine, run_id, token, reference):
    payload = read_snapshot(reference)
    if payload["run_id"] != str(run_id) or payload["worker_token"] != str(token):
        raise RiskProblem("RISK_SNAPSHOT_JOB_MISMATCH")
    with Session(engine) as session, session.begin():
        session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": ACCOUNT_LOCK})
        run = leased(session, run_id, token)
        actor = session.execute(select(AppUser.role_id, AppUser.is_active).where(
            AppUser.user_id == run.requested_by)).one_or_none()
        if actor is None or actor.role_id not in (1, 2) or not actor.is_active:
            raise RiskProblem("RISK_REQUESTER_NO_LONGER_AUTHORIZED")
        if (payload["period_start"] != run.period_start.isoformat()
                or payload["period_end"] != run.period_end.isoformat()
                or int(payload["rule"]["rule_id"]) != run.rule_id):
            raise RiskProblem("RISK_SNAPSHOT_PARAMETERS_MISMATCH")
        rows = [{"run_id": run_id, **row} for row in payload["profiles"]]
        if rows:
            session.execute(RiskProfile.__table__.insert(), rows)
        run.input_revision = int(payload["input_revision"])
        run.coverage_summary = payload["coverage"]
        run.input_manifest = {"format": VERSION, "snapshot": reference, "sources": payload["sources"],
                              "rule": payload["rule"], "code_hashes": payload["code_hashes"],
                              "matching_versions": sorted({row["algorithm_version"] for row in payload["mapping"]})}
        run.status = "SUCCEEDED"
        run.finished_at = datetime.now(timezone.utc)
        run.worker_token = run.lease_expires_at = None
        run.error_summary = None
        audit(session, run.requested_by, "RISK_SUCCEEDED", run_id, run.request_id,
              {"input_revision": str(run.input_revision), "profiles": len(rows), "snapshot_sha256": reference["sha256"]})
        session.flush()


def fail_job(engine, run_id, token, code):
    with Session(engine) as session, session.begin():
        run = session.scalar(select(RiskRun).where(RiskRun.run_id == run_id, RiskRun.status == "RUNNING",
            RiskRun.worker_token == token).with_for_update())
        if run:
            run.status = "FAILED"
            run.finished_at = datetime.now(timezone.utc)
            run.worker_token = run.lease_expires_at = None
            run.error_summary = code + "：未发布结果，请使用新的请求编号重新计算。"
            audit(session, None, "RISK_FAILED", run_id, uuid4(), {"code": code})


def run_once():
    engine = database_engine(Settings(), worker=True)
    job = None
    stop = Event()
    errors = []
    thread = None
    try:
        job = claim(engine)
        if job is None:
            return {"status": "idle", "processed": False}
        run_id, token = job

        def renew():
            while not stop.wait(20):
                try:
                    heartbeat(engine, run_id, token)
                except Exception:
                    errors.append("RISK_HEARTBEAT_FAILED")
                    return

        thread = Thread(target=renew, daemon=True)
        thread.start()
        reference = calculate(engine, run_id, token)
        stop.set()
        thread.join()
        if errors:
            raise RiskProblem(errors[0])
        heartbeat(engine, run_id, token)
        publish(engine, run_id, token, reference)
        return {"status": "processed", "processed": True, "operation": "risk", "run_id": str(run_id)}
    except Exception as exception:
        code = str(exception) if isinstance(exception, RiskProblem) else "RISK_PROCESSING_FAILED"
        if job:
            try:
                fail_job(engine, *job, code)
            except Exception:
                pass  # 数据库不可用则保留租约，下一次claim负责标记过期。
        return {"status": "failed", "processed": bool(job), "error_code": code}
    finally:
        stop.set()
        if thread:
            thread.join()
        engine.dispose()
