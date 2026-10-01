"""M2发布数据查询、导入控制和按角色投影。"""

import base64
from datetime import date, datetime, timezone
import hashlib
import hmac
import json
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from pydantic import Field
from sqlalchemy import func, select, tuple_
from sqlalchemy.orm import Session

from app.auth import Input, administrator, current_user, database_session, fail, response
from app.config import Settings
from app.importing.cleaning import ImportProblem, digest
from app.importing.service import batch_data, create_batch, request_action
from app.importing.storage import save_files
from app.models import (AuditLog, Borough, CasualtyStat, Collision, CollisionFactor, ContributingFactor,
                        DataIssue, DatasetState, ImportBatch, Location, Person, RawRecord, Vehicle, VehicleType)

router = APIRouter(prefix="/api/v1")
DB = Depends(database_session, scope="function")
USER = Depends(current_user)
ADMIN = Depends(administrator)


def answer(request, data, session):
    result = response(request, data)
    result["meta"]["data_revision"] = str(session.scalar(select(DatasetState.revision).where(DatasetState.state_id == 1)))
    return result


def identifier(value):
    if not value.isascii() or not value.isdigit() or not 0 < int(value) <= 9223372036854775807:
        fail(422, "INVALID_INPUT", "编号格式无效。")
    return int(value)


def collision_statement():
    columns = [Collision.collision_id, Collision.crash_date, Collision.crash_time, Location.borough_id,
               Borough.borough_name, Location.on_street_name, Location.cross_street_name, Location.off_street_name,
               func.ST_Y(Location.geom).label("latitude"), func.ST_X(Location.geom).label("longitude")]
    columns += [column for column in CasualtyStat.__table__.columns if column.name != "collision_id"]
    return select(*columns).join(Location, Collision.location_id == Location.location_id).outerjoin(Borough).join(CasualtyStat)


def apply_shared_filters(statement, borough_id, street, vehicle_type_id, factor_id):
    """委托给M6共享口径，保证列表、统计、导出使用同一套筛选实现。"""
    from app.statistics import apply_collision_filters
    return apply_collision_filters(statement, borough_id, street, vehicle_type_id, factor_id)


def collision_data(row):
    value = dict(row._mapping)
    value["collision_id"] = str(value["collision_id"])
    value["borough_id"] = str(value["borough_id"]) if value["borough_id"] is not None else None
    return value


def cursor_encode(payload):
    body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    signature = hmac.new(Settings().signing_key().encode(), body, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(body + signature).decode().rstrip("=")


def cursor_decode(value, filters, revision):
    try:
        raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
        body, signature = raw[:-32], raw[-32:]
        expected = hmac.new(Settings().signing_key().encode(), body, hashlib.sha256).digest()
        if not hmac.compare_digest(signature, expected): raise ValueError()
        data = json.loads(body)
        if data["filters"] != filters or data["revision"] != revision: raise ValueError()
        return date.fromisoformat(data["date"]), identifier(data["id"])
    except (ValueError, KeyError, TypeError, UnicodeError):
        fail(409, "CURSOR_INVALID", "分页条件或数据版本已改变，请从第一页重新查询。")


@router.get("/collisions")
def collisions(request: Request, start: date = date(2025, 1, 1), end: date = date(2026, 1, 1),
               borough_id: int | None = Query(None, ge=1, le=5), street: str | None = Query(None, max_length=160),
               vehicle_type_id: int | None = Query(None, gt=0), factor_id: int | None = Query(None, gt=0),
               page_size: int = Query(20, ge=1, le=100), cursor: str | None = Query(None, max_length=2048),
               include_total: bool = False, user=USER, session: Session = DB):
    if start >= end: fail(422, "INVALID_RANGE", "结束日期必须晚于开始日期；结束日期不包含在范围内。")
    statement = collision_statement().where(Collision.crash_date >= start, Collision.crash_date < end)
    statement = apply_shared_filters(statement, borough_id, street, vehicle_type_id, factor_id)
    revision = str(session.scalar(select(DatasetState.revision).where(DatasetState.state_id == 1)))
    filters = digest([str(start), str(end), borough_id, street, vehicle_type_id, factor_id, page_size])
    total = session.scalar(select(func.count()).select_from(statement.subquery())) if include_total else None
    if cursor:
        last_date, last_id = cursor_decode(cursor, filters, revision)
        statement = statement.where(tuple_(Collision.crash_date, Collision.collision_id) < tuple_(last_date, last_id))
    rows = session.execute(statement.order_by(Collision.crash_date.desc(), Collision.collision_id.desc()).limit(page_size + 1)).all()
    next_cursor = cursor_encode({"date": rows[page_size - 1].crash_date.isoformat(), "id": str(rows[page_size - 1].collision_id),
                                 "filters": filters, "revision": revision}) if len(rows) > page_size else None
    return answer(request, {"items": [collision_data(row) for row in rows[:page_size]], "next_cursor": next_cursor, "total": total}, session)


def require_collision(session, number):
    if not session.get(Collision, number): fail(404, "NOT_FOUND", "事故不存在。")


@router.get("/collisions/{collision_id}")
def collision_detail(collision_id: str, request: Request, user=USER, session: Session = DB):
    number = identifier(collision_id)
    row = session.execute(collision_statement().where(Collision.collision_id == number)).first()
    if row is None: fail(404, "NOT_FOUND", "事故不存在。")
    data = collision_data(row)
    source = session.execute(select(RawRecord.batch_id, RawRecord.raw_record_id, ImportBatch.cleaning_version)
                            .join(ImportBatch).join(Collision, Collision.source_record_id == RawRecord.raw_record_id)
                            .where(Collision.collision_id == number)).first()
    data["source"] = {"batch_id": str(source.batch_id), "raw_record_id": str(source.raw_record_id), "cleaning_version": source.cleaning_version}
    data["factors"] = [dict(row._mapping) for row in session.execute(select(CollisionFactor.factor_order, ContributingFactor.canonical_name,
                                    ContributingFactor.display_name).join(ContributingFactor).where(CollisionFactor.collision_id == number).order_by(CollisionFactor.factor_order))]
    return answer(request, data, session)


@router.get("/collisions/{collision_id}/persons")
def persons(collision_id: str, request: Request, page: int = Query(1, ge=1, le=100000), page_size: int = Query(20, ge=1, le=100), user=USER, session: Session = DB):
    number = identifier(collision_id)
    require_collision(session, number)
    columns = [Person.person_id, Person.collision_id, Person.person_type, Person.person_injury]
    if user.role_id in (1, 2): columns += [Person.person_age, Person.person_sex, Person.source_person_id, Person.source_vehicle_id]
    statement = select(*columns).where(Person.collision_id == number)
    total = session.scalar(select(func.count()).select_from(statement.subquery()))
    items = [dict(row._mapping) for row in session.execute(statement.order_by(Person.person_id).offset((page - 1) * page_size).limit(page_size))]
    for item in items:
        item["person_id"], item["collision_id"] = str(item["person_id"]), str(item["collision_id"])
    return answer(request, {"items": items, "total": total}, session)


@router.get("/collisions/{collision_id}/vehicles")
def vehicles(collision_id: str, request: Request, page: int = Query(1, ge=1, le=100000), page_size: int = Query(20, ge=1, le=100), user=USER, session: Session = DB):
    number = identifier(collision_id)
    require_collision(session, number)
    columns = [Vehicle.vehicle_id, Vehicle.collision_id, VehicleType.canonical_name, Vehicle.vehicle_year,
               Vehicle.travel_direction, Vehicle.pre_crash, Vehicle.point_of_impact, Vehicle.vehicle_damage]
    if user.role_id in (1, 2): columns.append(Vehicle.source_vehicle_id)
    statement = select(*columns).outerjoin(VehicleType).where(Vehicle.collision_id == number)
    total = session.scalar(select(func.count()).select_from(statement.subquery()))
    items = [dict(row._mapping) for row in session.execute(statement.order_by(Vehicle.vehicle_id).offset((page - 1) * page_size).limit(page_size))]
    for item in items:
        item["vehicle_id"], item["collision_id"] = str(item["vehicle_id"]), str(item["collision_id"])
    return answer(request, {"items": items, "total": total}, session)


def import_reader(user=USER):
    if user.role_id not in (1, 2): fail(403, "FORBIDDEN", "此操作需要管理员或治理人员权限。")
    return user


def get_batch(session, number, lock=False):
    statement = select(ImportBatch).where(ImportBatch.batch_id == identifier(number))
    batch = session.scalar(statement.with_for_update() if lock else statement)
    if not batch: fail(404, "NOT_FOUND", "批次不存在。")
    return batch


@router.get("/imports")
def imports(request: Request, page: int = Query(1, ge=1, le=100000), page_size: int = Query(20, ge=1, le=100), user=Depends(import_reader), session: Session = DB):
    total = session.scalar(select(func.count()).select_from(ImportBatch))
    batches = session.scalars(select(ImportBatch).order_by(ImportBatch.batch_id.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    return answer(request, {"items": [batch_data(batch, detailed=user.role_id == 1) for batch in batches], "total": total}, session)


@router.get("/imports/{batch_id}")
def import_detail(batch_id: str, request: Request, user=Depends(import_reader), session: Session = DB):
    return answer(request, batch_data(get_batch(session, batch_id), detailed=user.role_id == 1), session)


@router.post("/imports", status_code=202)
def upload(request: Request, request_id: UUID = Form(...), requested_start: date = Form(...), requested_end: date = Form(...),
           header_mode: Literal["api", "display", "auto"] = Form("auto"), crashes: UploadFile = File(...), persons: UploadFile = File(...), vehicles: UploadFile = File(...), user=ADMIN, session: Session = DB):
    if requested_start >= requested_end: fail(422, "IMPORT_RANGE_INVALID", "请选择左闭右开的有效日期范围。")
    try:
        manifest = save_files([(kind, upload.file, upload.filename or "") for kind, upload in zip(("CRASHES", "PERSON", "VEHICLES"), (crashes, persons, vehicles))], header_mode)
    except ImportProblem as error:
        fail(422, str(error), "文件格式、表头、编码或大小不符合导入要求。")
    batch = create_batch(session, user, request_id, requested_start, requested_end, manifest)
    return answer(request, batch_data(batch), session)


class ActionInput(Input):
    request_id: UUID


@router.post("/imports/{batch_id}/publish", status_code=202)
def publish_request(batch_id: str, body: ActionInput, request: Request, user=ADMIN, session: Session = DB):
    return answer(request, batch_data(request_action(session, user, get_batch(session, batch_id, True), body.request_id, "IMPORT_PUBLISH")), session)


@router.post("/imports/{batch_id}/retry", status_code=202)
def retry_request(batch_id: str, body: ActionInput, request: Request, user=ADMIN, session: Session = DB):
    return answer(request, batch_data(request_action(session, user, get_batch(session, batch_id, True), body.request_id, "IMPORT_RETRY")), session)


@router.get("/imports/{batch_id}/issues")
def issues(batch_id: str, request: Request, page: int = Query(1, ge=1, le=100000), page_size: int = Query(20, ge=1, le=100), user=ADMIN, session: Session = DB):
    batch = get_batch(session, batch_id)
    columns = [DataIssue.issue_id, DataIssue.issue_code, DataIssue.severity, DataIssue.field_name, DataIssue.description,
               DataIssue.status, DataIssue.resolution_note, RawRecord.row_no, RawRecord.source_kind]
    statement = select(*columns).outerjoin(RawRecord).where(DataIssue.batch_id == batch.batch_id)
    items = [dict(row._mapping) for row in session.execute(statement.order_by(DataIssue.issue_id).offset((page - 1) * page_size).limit(page_size))]
    for item in items: item["issue_id"] = str(item["issue_id"])
    return answer(request, {"items": items, "total": session.scalar(select(func.count()).select_from(statement.subquery()))}, session)


class IssueChange(Input):
    status: Literal["ACKNOWLEDGED", "RESOLVED"]
    resolution_note: str = Field(min_length=1, max_length=2000)


@router.patch("/data-issues/{issue_id}")
def issue_change(issue_id: str, body: IssueChange, request: Request, user=ADMIN, session: Session = DB):
    issue = session.scalar(select(DataIssue).where(DataIssue.issue_id == identifier(issue_id)).with_for_update())
    if not issue: fail(404, "NOT_FOUND", "问题不存在。")
    if not body.resolution_note.strip(): fail(422, "INVALID_INPUT", "处理说明不能为空。")
    issue.status, issue.resolution_note = body.status, body.resolution_note.strip()
    issue.resolved_by, issue.resolved_at = user.user_id, datetime.now(timezone.utc)
    session.add(AuditLog(actor_id=user.user_id, action="DATA_ISSUE_REVIEWED", entity_type="data_issue", entity_id=str(issue.issue_id), request_id=request.state.request_id, details={"status": body.status}))
    session.flush()
    return response(request, {"issue_id": str(issue.issue_id), "status": issue.status})


@router.get("/raw-records/{raw_record_id}")
def raw_record(raw_record_id: str, request: Request, user=ADMIN, session: Session = DB):
    raw = session.get(RawRecord, identifier(raw_record_id))
    if not raw: fail(404, "NOT_FOUND", "原始记录不存在。")
    return response(request, {"raw_record_id": str(raw.raw_record_id), "batch_id": str(raw.batch_id), "source_kind": raw.source_kind,
                              "row_no": raw.row_no, "payload": raw.payload, "validation_status": raw.validation_status})


DICTIONARIES = {"vehicle-types": (VehicleType, "vehicle_type_id"), "factors": (ContributingFactor, "factor_id")}


def dictionary(kind):
    if kind not in DICTIONARIES: fail(404, "NOT_FOUND", "字典不存在。")
    return DICTIONARIES[kind]


@router.get("/dictionaries/{kind}")
def dictionary_list(kind: str, request: Request, user=USER, session: Session = DB):
    model, key = dictionary(kind)
    items = [{"id": str(getattr(item, key)), "canonical_name": item.canonical_name, "display_name": item.display_name, "is_active": item.is_active}
             for item in session.scalars(select(model).order_by(model.canonical_name))]
    return response(request, {"items": items})


class DictionaryChange(Input):
    display_name: str | None = Field(None, min_length=1, max_length=160)
    is_active: bool | None = None


@router.patch("/dictionaries/{kind}/{item_id}")
def dictionary_change(kind: str, item_id: str, body: DictionaryChange, request: Request, user=ADMIN, session: Session = DB):
    model, key = dictionary(kind)
    item = session.scalar(select(model).where(getattr(model, key) == identifier(item_id)).with_for_update())
    if not item: fail(404, "NOT_FOUND", "字典条目不存在。")
    if not body.model_fields_set: fail(422, "INVALID_INPUT", "请提供修改内容。")
    if "display_name" in body.model_fields_set:
        if body.display_name is not None and not body.display_name.strip(): fail(422, "INVALID_INPUT", "显示名不能为空。")
        item.display_name = body.display_name.strip() if body.display_name else None
    if "is_active" in body.model_fields_set:
        if body.is_active is None: fail(422, "INVALID_INPUT", "启用状态不能为空。")
        item.is_active = body.is_active
    session.add(AuditLog(actor_id=user.user_id, action="DICTIONARY_UPDATED", entity_type=model.__tablename__, entity_id=item_id,
                         request_id=request.state.request_id, details={"fields": sorted(body.model_fields_set)}))
    session.flush()
    return response(request, {"id": str(getattr(item, key)), "canonical_name": item.canonical_name, "display_name": item.display_name, "is_active": item.is_active})


@router.get("/audit-logs")
def audit_logs(request: Request, page: int = Query(1, ge=1, le=100000), page_size: int = Query(20, ge=1, le=100), user=Depends(import_reader), session: Session = DB):
    statement = select(AuditLog)
    if user.role_id == 2: statement = statement.where(AuditLog.actor_id == user.user_id)
    items = [{"audit_id": str(item.audit_id), "actor_id": str(item.actor_id) if item.actor_id else None, "action": item.action,
              "entity_type": item.entity_type, "entity_id": item.entity_id, "created_at": item.created_at, "details": item.details}
             for item in session.scalars(statement.order_by(AuditLog.audit_id.desc()).offset((page - 1) * page_size).limit(page_size))]
    return response(request, {"items": items, "total": session.scalar(select(func.count()).select_from(statement.subquery()))})
