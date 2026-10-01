"""M5模拟治理任务：受控数据库事务、幂等契约和只读投影。"""

from datetime import date, datetime
import json
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.auth import fail
from app.contracts import request_digest
from app.models import AppUser


TASK_SELECT = """
    SELECT t.task_id,t.task_code,t.request_id,t.profile_id,t.title,t.description,
           t.measure_type,t.priority,t.status,t.created_by,t.assignee_id,t.due_date,
           t.effective_on,t.assessment_scope,t.is_simulated,t.deleted_at,t.created_at,
           t.updated_at,t.version,p.intersection_id,p.run_id,i.intersection_code,
           v.risk_level,creator.display_name AS creator_name,
           assignee.display_name AS assignee_name
    FROM public.governance_task t
    JOIN public.risk_profile p USING (profile_id)
    JOIN public.intersection i USING (intersection_id)
    JOIN public.v_risk_profile v USING (profile_id)
    JOIN public.app_user creator ON creator.user_id=t.created_by
    LEFT JOIN public.app_user assignee ON assignee.user_id=t.assignee_id
"""


ERRORS = {
    "VZ_TASK_NOT_FOUND": (404, "TASK_NOT_FOUND", "未找到该治理任务。"),
    "VZ_PROFILE_NOT_FOUND": (404, "RISK_PROFILE_NOT_FOUND", "未找到该风险画像。"),
    "VZ_FORBIDDEN": (403, "FORBIDDEN", "当前账户无权执行此治理操作。"),
    "VZ_REQUEST_CONFLICT": (409, "REQUEST_CONTENT_CONFLICT", "该请求编号已用于不同的治理内容。"),
    "VZ_VERSION_CONFLICT": (409, "TASK_VERSION_CONFLICT", "任务已被其他操作修改，请刷新后重试。"),
    "VZ_STATE_CONFLICT": (409, "TASK_STATE_CONFLICT", "当前任务状态不允许此操作。"),
    "VZ_PROFILE_CONFLICT": (409, "PROFILE_NOT_ELIGIBLE", "画像或交叉口状态已变化，不能建立该任务。"),
    "VZ_INVALID_INPUT": (422, "INVALID_INPUT", "治理任务输入无效。"),
    "VZ_RATIONALE_REQUIRED": (422, "RATIONALE_REQUIRED", "LOW 或 MEDIUM 画像必须填写建立理由。"),
    "VZ_UNKNOWN_REQUIRES_SURVEY": (422, "UNKNOWN_REQUIRES_SURVEY", "UNKNOWN 画像仅允许 FIELD_SURVEY 调查草稿。"),
    "VZ_ASSIGNEE_INVALID": (422, "ASSIGNEE_INVALID", "执行人必须是启用的管理员或治理人员。"),
}


def _database_problem(exc):
    original = getattr(exc, "orig", None)
    message = getattr(getattr(original, "diag", None), "message_primary", None)
    if message in ERRORS:
        status, code, public_message = ERRORS[message]
        fail(status, code, public_message)
    raise exc


def _run_function(session, statement, values):
    try:
        return session.execute(statement, values).scalar_one()
    except DBAPIError as exc:
        _database_problem(exc)


def _iso(value):
    if value is None:
        return None
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def _allowed_actions(task, actor):
    if actor.role_id not in (1, 2) or task["deleted_at"] is not None:
        return []
    admin = actor.role_id == 1
    creator = task["created_by"] == actor.user_id
    assignee = task["assignee_id"] == actor.user_id
    status = task["status"]
    actions = []
    if status == "DRAFT" and (admin or creator):
        actions.extend(("edit", "delete_draft", "cancel"))
        if task["risk_level"] != "UNKNOWN":
            actions.append("publish")
    elif status == "OPEN":
        if admin or creator:
            actions.extend(("assign", "cancel"))
        if assignee:
            actions.append("start")
    elif status == "IN_PROGRESS":
        if admin or creator:
            actions.append("cancel")
        if assignee:
            actions.extend(("progress", "submit"))
    elif status == "PENDING_REVIEW":
        if (admin or creator) and not assignee:
            actions.extend(("approve", "reject"))
        if admin or creator:
            actions.append("cancel")
    return actions


def task_data(row, actor):
    task = dict(row)
    return {
        "task_id": str(task["task_id"]),
        "task_code": task["task_code"],
        "request_id": str(task["request_id"]),
        "profile_id": str(task["profile_id"]),
        "intersection_id": str(task["intersection_id"]),
        "intersection_code": task["intersection_code"],
        "run_id": str(task["run_id"]),
        "risk_level": task["risk_level"],
        "title": task["title"],
        "description": task["description"],
        "measure_type": task["measure_type"],
        "priority": task["priority"],
        "status": task["status"],
        "created_by": str(task["created_by"]),
        "creator_name": task["creator_name"],
        "assignee_id": str(task["assignee_id"]) if task["assignee_id"] is not None else None,
        "assignee_name": task["assignee_name"],
        "due_date": _iso(task["due_date"]),
        "effective_on": _iso(task["effective_on"]),
        "assessment_scope": task["assessment_scope"],
        "is_simulated": task["is_simulated"],
        "deleted_at": _iso(task["deleted_at"]),
        "created_at": _iso(task["created_at"]),
        "updated_at": _iso(task["updated_at"]),
        "version": task["version"],
        "allowed_actions": _allowed_actions(task, actor),
    }


def _task_row(session, task_id):
    return session.execute(text(TASK_SELECT + " WHERE t.task_id=:task_id"),
                           {"task_id": task_id}).mappings().one_or_none()


def get_task(session: Session, task_id: int, actor: AppUser):
    row = _task_row(session, task_id)
    if row is None:
        fail(404, "TASK_NOT_FOUND", "未找到该治理任务。")
    if row["deleted_at"] is not None and actor.role_id != 1 and row["created_by"] != actor.user_id:
        fail(404, "TASK_NOT_FOUND", "未找到该治理任务。")
    return task_data(row, actor)


def create_task(session: Session, actor: AppUser, *, request_id: UUID, profile_id: int,
                title: str, description: str, measure_type: str, priority: str,
                due_date: date | None, effective_on: date | None, radius_m: int,
                rationale: str | None):
    payload = {
        "profile_id": str(profile_id), "title": title, "description": description,
        "measure_type": measure_type, "priority": priority,
        "due_date": _iso(due_date), "effective_on": _iso(effective_on),
        "radius_m": radius_m, "rationale": rationale,
    }
    digest = request_digest(actor_id=str(actor.user_id), operation="TASK_CREATE",
                            target_id=None, payload=payload)
    task_id = _run_function(session, text("""
        SELECT public.vz_governance_create(
            :actor_id,:profile_id,:request_id,:request_hash,:title,:description,
            :measure_type,:priority,:due_date,:effective_on,:radius_m,:rationale)
    """), {
        "actor_id": actor.user_id, "profile_id": profile_id, "request_id": request_id,
        "request_hash": digest, "title": title, "description": description,
        "measure_type": measure_type, "priority": priority, "due_date": due_date,
        "effective_on": effective_on, "radius_m": radius_m, "rationale": rationale,
    })
    return get_task(session, task_id, actor)


def change_task(session: Session, actor: AppUser, *, task_id: int, action: str,
                operation: str, request_id: UUID, expected_version: int, payload: dict):
    digest_payload = {"expected_version": expected_version, **payload}
    digest = request_digest(actor_id=str(actor.user_id), operation=operation,
                            target_id=str(task_id), payload=digest_payload)
    changed_task_id = _run_function(session, text("""
        SELECT public.vz_governance_change(
            :task_id,:expected_version,:action,:actor_id,:request_id,:request_hash,
            CAST(:payload AS jsonb))
    """), {
        "task_id": task_id, "expected_version": expected_version, "action": action,
        "actor_id": actor.user_id, "request_id": request_id, "request_hash": digest,
        "payload": json.dumps(payload, ensure_ascii=False, sort_keys=True,
                              separators=(",", ":")),
    })
    return get_task(session, changed_task_id, actor)


def list_tasks(session: Session, actor: AppUser, *, status: str | None, my_todo: bool,
               page: int, page_size: int):
    where = ["t.deleted_at IS NULL"]
    values = {"limit": page_size, "offset": (page - 1) * page_size}
    if status:
        where.append("t.status=:status")
        values["status"] = status
    if my_todo:
        where.extend(("t.assignee_id=:actor_id", "t.status IN ('OPEN','IN_PROGRESS','PENDING_REVIEW')"))
        values["actor_id"] = actor.user_id
    predicate = " AND ".join(where)
    total = session.execute(text("""
        SELECT count(*) FROM public.governance_task t WHERE """ + predicate), values).scalar_one()
    rows = session.execute(text(TASK_SELECT + " WHERE " + predicate +
        " ORDER BY t.updated_at DESC,t.task_id DESC LIMIT :limit OFFSET :offset"), values).mappings()
    return {"items": [task_data(row, actor) for row in rows], "total": total,
            "page": page, "page_size": page_size}


def list_assignees(session: Session, *, search: str | None, page: int, page_size: int):
    where = ["is_active", "role_id IN (1,2)"]
    values = {"limit": page_size, "offset": (page - 1) * page_size}
    if search:
        where.append("display_name ILIKE :search ESCAPE '\\'")
        escaped = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        values["search"] = "%" + escaped + "%"
    predicate = " AND ".join(where)
    total = session.execute(text("SELECT count(*) FROM public.app_user WHERE " + predicate), values).scalar_one()
    rows = session.execute(text("""
        SELECT user_id,display_name,role_id FROM public.app_user WHERE """ + predicate +
        " ORDER BY display_name,user_id LIMIT :limit OFFSET :offset"), values).mappings()
    role_codes = {1: "ADMIN", 2: "MANAGER"}
    return {"items": [{"user_id": str(row["user_id"]), "display_name": row["display_name"],
                        "role": role_codes[row["role_id"]]} for row in rows],
            "total": total, "page": page, "page_size": page_size}


def task_history(session: Session, task_id: int, actor: AppUser):
    task = session.execute(text("""
        SELECT created_by,deleted_at FROM public.governance_task WHERE task_id=:id
    """), {"id": task_id}).mappings().one_or_none()
    if task is None or (task["deleted_at"] is not None and actor.role_id != 1
                        and task["created_by"] != actor.user_id):
        fail(404, "TASK_NOT_FOUND", "未找到该治理任务。")
    rows = session.execute(text("""
        SELECT h.history_id,h.task_id,h.sequence_no,h.request_id,h.event_type,
               h.from_status,h.to_status,h.actor_id,u.display_name AS actor_name,
               h.note,h.changed_fields,h.created_at
        FROM public.task_history h JOIN public.app_user u ON u.user_id=h.actor_id
        WHERE h.task_id=:task_id ORDER BY h.sequence_no
    """), {"task_id": task_id}).mappings()
    return {"items": [{
        "history_id": str(row["history_id"]), "task_id": str(row["task_id"]),
        "sequence_no": row["sequence_no"], "request_id": str(row["request_id"]),
        "event_type": row["event_type"], "from_status": row["from_status"],
        "to_status": row["to_status"], "actor_id": str(row["actor_id"]),
        "actor_name": row["actor_name"], "note": row["note"],
        "changed_fields": row["changed_fields"], "created_at": _iso(row["created_at"]),
    } for row in rows]}
