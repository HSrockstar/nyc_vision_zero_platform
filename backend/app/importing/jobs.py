"""单worker租约作业：暂存可恢复，正式发布在一个事务内完成。"""

from collections import Counter
from datetime import datetime, timezone
from itertools import islice
from uuid import uuid4

from sqlalchemy import String, cast, distinct, func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.auth import ACCOUNT_LOCK
from app.config import Settings
from app.db.connection import database_engine
from app.importing.cleaning import (CLEANING_VERSION, HEADERS, ImportProblem, KINDS, MESSAGES,
                                   canonical_row, digest, normalized, source_id)
from app.importing.service import record_audit
from app.importing.storage import csv_rows, verify_files
from app.models import (AppUser, CasualtyStat, Collision, CollisionFactor, ContributingFactor,
                        DataIssue, DatasetState, ImportBatch, Location, Person, RawRecord,
                        Vehicle, VehicleType)

CHUNK = 1000
LEASE = text("interval '120 seconds'")
FACTS = {"CRASHES": (Collision, "collision_id"), "PERSON": (Person, "person_id"), "VEHICLES": (Vehicle, "vehicle_id")}


def chunks(iterator, size=CHUNK):
    iterator = iter(iterator)
    while part := list(islice(iterator, size)):
        yield part


def leased_batch(session, batch_id, token):
    batch = session.scalar(select(ImportBatch).where(ImportBatch.batch_id == batch_id,
        ImportBatch.worker_token == token, ImportBatch.status.in_(("VALIDATING", "PUBLISHING")),
        ImportBatch.lease_expires_at > func.clock_timestamp()).with_for_update())
    if batch is None:
        raise ImportProblem("JOB_LEASE_LOST")
    return batch


def heartbeat(session, batch_id, token):
    batch = leased_batch(session, batch_id, token)
    batch.lease_expires_at = func.clock_timestamp() + LEASE
    session.flush()
    return batch


def claim(engine):
    with Session(engine, expire_on_commit=False) as session, session.begin():
        expired = session.scalars(select(ImportBatch).where(
            ImportBatch.status.in_(("VALIDATING", "PUBLISHING")), ImportBatch.worker_token.is_not(None),
            ImportBatch.lease_expires_at <= func.clock_timestamp()).with_for_update(skip_locked=True).limit(100)).all()
        for batch in expired:
            batch.status = "FAILED"
            batch.error_summary = "JOB_LEASE_EXPIRED：作业租约已过期，可由管理员记录重试。"
            batch.finished_at = datetime.now(timezone.utc)
            batch.worker_token = None
            batch.lease_expires_at = None
            record_audit(session, None, "IMPORT_LEASE_EXPIRED", batch.batch_id, uuid4())
        session.flush()
        batch = session.scalar(select(ImportBatch).where(
            (ImportBatch.status == "UPLOADED") | ((ImportBatch.status == "PUBLISHING") & ImportBatch.worker_token.is_(None))
        ).order_by(ImportBatch.batch_id).with_for_update(skip_locked=True).limit(1))
        if batch is None:
            return None
        operation = "publish" if batch.status == "PUBLISHING" else "validate"
        if operation == "validate": batch.status = "VALIDATING"
        batch.worker_token = uuid4()
        batch.lease_expires_at = func.clock_timestamp() + LEASE
        batch.started_at = datetime.now(timezone.utc)
        batch.attempt_no += 1
        session.flush()
        return batch.batch_id, batch.worker_token, operation


def stage(engine, batch_id, token):
    with Session(engine) as session:
        batch = leased_batch(session, batch_id, token)
        manifest = dict(batch.input_manifest)
        session.commit()
    directory = verify_files(manifest)
    for file in sorted(manifest["files"], key=lambda value: KINDS.index(value["source_kind"])):
        kind = file["source_kind"]
        for part in chunks(csv_rows(directory / (kind + ".csv"))):
            rows = []
            for row_no, payload in part:
                row = canonical_row(kind, payload, file["header_mode"])
                try: key = str(source_id(row.get("collision_id" if kind == "CRASHES" else "unique_id")))
                except ValueError: key = None
                rows.append({"batch_id": batch_id, "source_kind": kind, "row_no": row_no,
                             "source_key": key, "payload": payload, "row_hash": digest(payload), "validation_status": "UNVALIDATED"})
            with Session(engine) as session, session.begin():
                heartbeat(session, batch_id, token)
                session.execute(insert(RawRecord).values(rows).on_conflict_do_nothing(constraint="uq_raw_batch_line"))
                actual = session.execute(select(RawRecord.row_no, RawRecord.row_hash).where(
                    RawRecord.batch_id == batch_id, RawRecord.source_kind == kind,
                    RawRecord.row_no.in_([row["row_no"] for row in rows]))).all()
                if dict(actual) != {row["row_no"]: row["row_hash"] for row in rows}:
                    raise ImportProblem("SAVED_CONTENT_CONFLICT")
                leased_batch(session, batch_id, token)
    verify_files(manifest)


def source_state(session, batch_id):
    # 匹配范围限于本批来源键及父键，避免每次装载整个正式库。
    display_key = next(key for key, value in HEADERS["PERSON"].items() if value == "collision_id")
    # 与source_id的Python str.strip一致；默认btrim只去空格会误隔离仅子表输入。
    trim_chars = " \t\n\r\v\f\x1c\x1d\x1e\x1f\x85\xa0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000"
    parent_key = func.ltrim(func.btrim(func.coalesce(RawRecord.payload["collision_id"].astext, RawRecord.payload[display_key].astext), trim_chars), "0")
    # 先一次性汇总本批父键，再做半连接；不能对每个正式父行扫描含JSON条件的raw表。
    parent_keys = select(RawRecord.source_key).where(RawRecord.batch_id == batch_id, RawRecord.source_kind == "CRASHES").union(
        select(parent_key).where(RawRecord.batch_id == batch_id, RawRecord.source_kind.in_(("PERSON", "VEHICLES"))))
    parents = dict(session.execute(select(Collision.collision_id, Collision.crash_date).where(cast(Collision.collision_id, String).in_(parent_keys))).all())
    existing = {}
    for kind, (model, key) in FACTS.items():
        rows = session.execute(select(getattr(model, key), RawRecord.row_hash, ImportBatch.cleaning_version)
            .join(RawRecord, model.source_record_id == RawRecord.raw_record_id)
            .join(ImportBatch, RawRecord.batch_id == ImportBatch.batch_id).where(cast(getattr(model, key), String).in_(
                select(RawRecord.source_key).where(RawRecord.batch_id == batch_id, RawRecord.source_kind == kind)))).all()
        existing[kind] = {number: (row_hash, version) for number, row_hash, version in rows}
    return parents, existing


def raw_pages(session, batch_id, kind, accepted=False):
    last = 0
    while True:
        statement = select(RawRecord).where(RawRecord.batch_id == batch_id, RawRecord.source_kind == kind, RawRecord.raw_record_id > last)
        if accepted: statement = statement.where(RawRecord.validation_status == "ACCEPTED")
        rows = session.scalars(statement.order_by(RawRecord.raw_record_id).limit(CHUNK)).all()
        if not rows: break
        yield rows
        last = rows[-1].raw_record_id
        session.expunge_all()


def diagnostics(session, batch_id, raw_id, issues):
    if not issues: return
    values = [{"batch_id": batch_id, "raw_record_id": raw_id, "issue_code": issue["issue_code"],
               "severity": issue["severity"], "field_name": issue["field_name"],
               "description": MESSAGES[issue["issue_code"]], "status": "OPEN"} for issue in issues]
    session.execute(insert(DataIssue).values(values).on_conflict_do_nothing(constraint="uq_issue_diagnostic"))


def validate(engine, batch_id, token):
    stage(engine, batch_id, token)
    with Session(engine, expire_on_commit=False) as session:
        batch = leased_batch(session, batch_id, token)
        start, end, manifest = batch.requested_start, batch.requested_end, dict(batch.input_manifest)
        if batch.cleaning_version != CLEANING_VERSION: raise ImportProblem("CLEANING_VERSION_UNSUPPORTED")
        parents, existing = source_state(session, batch_id)
        conflicts = set(session.execute(select(RawRecord.source_kind, RawRecord.source_key).where(
            RawRecord.batch_id == batch_id, RawRecord.source_key.is_not(None)).group_by(
            RawRecord.source_kind, RawRecord.source_key).having(func.count(distinct(RawRecord.row_hash)) > 1)).all())
        revision = session.scalar(select(DatasetState.revision).where(DatasetState.state_id == 1))
        session.commit()
        counts, planned, source_counts = Counter(), Counter(), {}
        seen = set()
        modes = {file["source_kind"]: file["header_mode"] for file in manifest["files"]}
        for kind in KINDS:
            source_counts[kind] = Counter()
            for part in raw_pages(session, batch_id, kind):
                heartbeat(session, batch_id, token)
                changes = []
                for raw in part:
                    row = canonical_row(kind, raw.payload, modes[kind])
                    identity = (kind, raw.source_key)
                    if raw.source_key is not None and identity in conflicts:
                        value, issues, status = None, [{"issue_code": "DUPLICATE_CONFLICT", "field_name": "source_key", "severity": "ERROR"}], "REJECTED"
                    elif raw.source_key is not None and identity in seen:
                        value, issues, status = None, [{"issue_code": "DUPLICATE_IDENTICAL", "field_name": "source_key", "severity": "INFO"}], "SKIPPED"
                    else:
                        value, issues, status = normalized(kind, row, parents, start, end)
                        if raw.source_key is not None: seen.add(identity)
                        if status == "ACCEPTED":
                            old = existing[kind].get(value["id"])
                            if kind == "CRASHES": parents[value["id"]] = value["crash_date"]
                            operation = "inserted" if old is None else "updated"
                            if old == (raw.row_hash, CLEANING_VERSION):
                                status, operation = "SKIPPED", "unchanged"
                                issues.append({"issue_code": "SOURCE_UNCHANGED", "field_name": "source_key", "severity": "INFO"})
                            planned[operation] += 1
                    counts[status] += 1
                    source_counts[kind][status.lower()] += 1
                    changes.append({"status": status, "raw_id": raw.raw_record_id})
                    diagnostics(session, batch_id, raw.raw_record_id, issues)
                session.execute(text("UPDATE public.raw_record SET validation_status=:status WHERE raw_record_id=:raw_id"), changes)
                leased_batch(session, batch_id, token)
                session.commit()
        batch = heartbeat(session, batch_id, token)
        total = sum(counts.values())
        blocked = len(conflicts) + int(counts["ACCEPTED"] == 0 and revision == 0)
        manifest["validation"] = {"source_counts": {kind: dict(value) for kind, value in source_counts.items()},
                                  "planned": {key: planned[key] for key in ("inserted", "updated", "unchanged")},
                                  "blocking_issue_count": blocked, "data_revision": str(revision),
                                  "coverage": {"method": "按父事故编号验证；缺失明细不伪造", "selected_range": [start.isoformat(), end.isoformat()]}}
        batch.input_manifest = manifest
        batch.rows_read, batch.rows_accepted, batch.rows_rejected, batch.rows_skipped = total, counts["ACCEPTED"], counts["REJECTED"], counts["SKIPPED"]
        batch.status = "FAILED" if blocked else "READY"
        batch.error_summary = "INPUT_BLOCKED：来源键冲突或空库无有效记录；请核对问题并用修正文件建立新批次。" if blocked else None
        batch.finished_at = datetime.now(timezone.utc) if blocked else None
        batch.worker_token = None
        batch.lease_expires_at = None
        record_audit(session, batch.created_by, "IMPORT_VALIDATED", batch_id, uuid4(), {"rows": total, "blocked": bool(blocked)})
        session.commit()


def dictionary_ids(session, model, key_column, names):
    names = sorted({name for name in names if name})
    if not names: return {}
    session.execute(insert(model).values([{"canonical_name": name} for name in names]).on_conflict_do_nothing(index_elements=["canonical_name"]))
    return dict(session.execute(select(model.canonical_name, getattr(model, key_column)).where(model.canonical_name.in_(names))).all())


def locations(session, values):
    unique = {value["location_key"]: value for value in values}
    rows = []
    for key, value in unique.items():
        item = value["location"]
        rows.append({"location_key": key, "key_input": value["key_input"],
                     **{field: item[field] for field in ("borough_id", "zip_code", "on_street_name", "cross_street_name", "off_street_name")},
                     "geom": f"SRID=4326;POINT({item['longitude']} {item['latitude']})" if item["latitude"] is not None else None})
    session.execute(insert(Location).values(rows).on_conflict_do_nothing(index_elements=["location_key"]))
    actual = session.execute(select(Location.location_key, Location.location_id, Location.key_input).where(Location.location_key.in_(list(unique)))).all()
    if any(key_input != unique[key]["key_input"] for key, identifier, key_input in actual):
        raise ImportProblem("LOCATION_KEY_COLLISION")
    return {key: identifier for key, identifier, key_input in actual}


def upsert(session, model, key, values):
    if not values: return
    statement = insert(model).values(values)
    fields = {name: getattr(statement.excluded, name) for name in values[0] if name != key}
    if "updated_at" in model.__table__.columns: fields["updated_at"] = func.clock_timestamp()
    session.execute(statement.on_conflict_do_update(index_elements=[key], set_=fields))


def write_facts(session, kind, pairs):
    if kind == "CRASHES":
        ids = locations(session, [value for raw, value in pairs])
        factor_ids = dictionary_ids(session, ContributingFactor, "factor_id", [name for raw, value in pairs for name in value["factors"].values()])
        collision_rows, casualty_rows, factors = [], [], []
        for raw, value in pairs:
            number = value["id"]
            collision_rows.append({"collision_id": number, "location_id": ids[value["location_key"]], "crash_date": value["crash_date"],
                                   "crash_time": value["crash_time"], "source_record_id": raw.raw_record_id})
            casualty_rows.append({"collision_id": number, **value["casualty"]})
            factors.extend({"collision_id": number, "factor_order": slot, "factor_id": factor_ids[name]} for slot, name in value["factors"].items() if name)
        upsert(session, Collision, "collision_id", collision_rows)
        upsert(session, CasualtyStat, "collision_id", casualty_rows)
        session.execute(CollisionFactor.__table__.delete().where(CollisionFactor.collision_id.in_([value["id"] for raw, value in pairs])))
        if factors: session.execute(insert(CollisionFactor).values(factors))
    else:
        model, key = FACTS[kind]
        type_ids = dictionary_ids(session, VehicleType, "vehicle_type_id", [value["canonical_name"] for raw, value in pairs]) if kind == "VEHICLES" else {}
        rows = []
        for raw, value in pairs:
            row = {name: value.get(name) for name in model.__table__.columns.keys() if name not in (key, "source_record_id", "updated_at", "vehicle_type_id")}
            row.update({key: value["id"], "source_record_id": raw.raw_record_id})
            if kind == "VEHICLES": row["vehicle_type_id"] = type_ids.get(value["canonical_name"])
            rows.append(row)
        upsert(session, model, key, rows)


def publish(engine, batch_id, token):
    with Session(engine, expire_on_commit=False) as session, session.begin():
        # 与账户管理使用一致顺序，避免授权过期与分析版本写入竞争。
        session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": ACCOUNT_LOCK})
        state = session.scalar(select(DatasetState).where(DatasetState.state_id == 1).with_for_update())
        batch = leased_batch(session, batch_id, token)
        publisher = session.execute(select(AppUser.user_id, AppUser.role_id, AppUser.is_active).where(AppUser.user_id == batch.publish_requested_by)).first()
        if publisher is None or publisher.role_id != 1 or not publisher.is_active:
            raise ImportProblem("PUBLISHER_NO_LONGER_AUTHORIZED")
        manifest = dict(batch.input_manifest)
        verify_files(manifest)
        if batch.cleaning_version != CLEANING_VERSION: raise ImportProblem("CLEANING_VERSION_UNSUPPORTED")
        parents, existing = source_state(session, batch_id)
        counts = Counter(unchanged=manifest.get("validation", {}).get("planned", {}).get("unchanged", 0))
        modes = {file["source_kind"]: file["header_mode"] for file in manifest["files"]}
        for kind in KINDS:
            for part in raw_pages(session, batch_id, kind, accepted=True):
                heartbeat(session, batch_id, token)
                pairs = []
                for raw in part:
                    value, issues, status = normalized(kind, canonical_row(kind, raw.payload, modes[kind]), parents, batch.requested_start, batch.requested_end)
                    if status != "ACCEPTED": raise ImportProblem("VALIDATION_STALE")
                    if kind == "CRASHES": parents[value["id"]] = value["crash_date"]
                    old = existing[kind].get(value["id"])
                    if old == (raw.row_hash, CLEANING_VERSION):
                        counts["unchanged"] += 1
                        continue
                    counts["inserted" if old is None else "updated"] += 1
                    pairs.append((raw, value))
                if pairs: write_facts(session, kind, pairs)
        if session.scalar(text("SELECT EXISTS(SELECT 1 FROM public.collision c LEFT JOIN public.casualty_stat s USING(collision_id) WHERE s.collision_id IS NULL)")):
            raise ImportProblem("CASUALTY_INTEGRITY_FAILED")
        # raw_pages分块释放对象，重新取持久对象，避免把状态更新留在脱离会话的对象上。
        state = session.scalar(select(DatasetState).where(DatasetState.state_id == 1))
        batch = heartbeat(session, batch_id, token)
        if counts["inserted"] + counts["updated"]:
            state.revision += 1
            state.updated_at = datetime.now(timezone.utc)
            state.last_change_note = "M2批次正式发布：" + str(batch_id)
        if state.revision == 0: raise ImportProblem("NO_FORMAL_DATA")
        manifest["publication"] = {key: counts[key] for key in ("inserted", "updated", "unchanged")}
        manifest["publication"].update(revision=str(state.revision), no_change=not bool(counts["inserted"] + counts["updated"]))
        batch.input_manifest = manifest
        batch.status = "SUCCEEDED"
        batch.published_revision = state.revision
        batch.finished_at = datetime.now(timezone.utc)
        batch.error_summary = None
        batch.worker_token = None
        batch.lease_expires_at = None
        record_audit(session, publisher.user_id, "IMPORT_PUBLISHED", batch_id, batch.publish_request_id, manifest["publication"])
        session.flush()


def fail_job(engine, batch_id, token, code):
    with Session(engine) as session, session.begin():
        batch = session.scalar(select(ImportBatch).where(ImportBatch.batch_id == batch_id, ImportBatch.worker_token == token,
            ImportBatch.status.in_(("VALIDATING", "PUBLISHING"))).with_for_update())
        if batch:
            batch.status = "FAILED"
            batch.error_summary = code + "：作业未完成，正式发布已回滚；请核对文件与批次后记录重试。"
            batch.finished_at = datetime.now(timezone.utc)
            batch.worker_token = None
            batch.lease_expires_at = None
            record_audit(session, None, "IMPORT_FAILED", batch_id, uuid4(), {"code": code})


def run_once():
    engine = database_engine(Settings(), worker=True)
    job = None
    try:
        job = claim(engine)
        if job is None: return {"status": "idle", "processed": False}
        batch_id, token, operation = job
        (publish if operation == "publish" else validate)(engine, batch_id, token)
        return {"status": "processed", "processed": True, "batch_id": str(batch_id), "operation": operation}
    except Exception as exception:
        code = str(exception) if isinstance(exception, ImportProblem) else "IMPORT_PROCESSING_FAILED"
        if job:
            try: fail_job(engine, job[0], job[1], code)
            except Exception: pass  # 数据库暂不可用时保留租约，由恢复流程处理。
        return {"status": "failed", "processed": bool(job), "error_code": code}
    finally:
        engine.dispose()
