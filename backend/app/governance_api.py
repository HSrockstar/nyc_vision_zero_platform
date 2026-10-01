"""M5模拟治理任务API；写入身份始终来自当前Bearer会话。"""

from datetime import date
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from pydantic import Field, field_validator, model_validator
from sqlalchemy.orm import Session

from app.auth import Input, database_session, fail
from app.data_api import answer, identifier
from app.governance import (change_task, create_task, get_task, list_assignees,
                            list_tasks, task_history)
from app.models import AppUser
from app.spatial_api import manager


router = APIRouter(prefix="/api/v1")
DB = Depends(database_session, scope="function")
MANAGER = Depends(manager)
TaskMeasure = Literal["MARKING_MAINTENANCE", "SIGNAL_REVIEW",
                      "PEDESTRIAN_FACILITY_REVIEW", "FIELD_SURVEY", "OTHER"]
TaskPriority = Literal["LOW", "MEDIUM", "HIGH", "URGENT"]
TaskStatus = Literal["DRAFT", "OPEN", "IN_PROGRESS", "PENDING_REVIEW", "COMPLETED", "CANCELLED"]


def clean_text(value):
    value = value.strip()
    if not value:
        raise ValueError("内容不能为空")
    return value


class CreateInput(Input):
    request_id: UUID
    profile_id: str
    title: str = Field(min_length=1, max_length=160)
    description: str = Field(min_length=1, max_length=10000)
    measure_type: TaskMeasure
    priority: TaskPriority
    due_date: date | None = None
    effective_on: date | None = None
    radius_m: int = Field(default=50, ge=1, le=1000)
    rationale: str | None = Field(default=None, max_length=2000)

    @field_validator("title", "description")
    @classmethod
    def nonempty_content(cls, value):
        return clean_text(value)

    @field_validator("rationale")
    @classmethod
    def nonempty_rationale(cls, value):
        return clean_text(value) if value is not None else value


class VersionInput(Input):
    request_id: UUID
    expected_version: int = Field(gt=0)
    note: str = Field(min_length=1, max_length=10000)

    @field_validator("note")
    @classmethod
    def nonempty_note(cls, value):
        return clean_text(value)


class EditInput(VersionInput):
    title: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, min_length=1, max_length=10000)
    measure_type: TaskMeasure | None = None
    priority: TaskPriority | None = None
    due_date: date | None = None
    effective_on: date | None = None

    @field_validator("title", "description")
    @classmethod
    def optional_nonempty_content(cls, value):
        return clean_text(value) if value is not None else value

    @model_validator(mode="after")
    def changed_fields_required(self):
        editable = {"title", "description", "measure_type", "priority", "due_date", "effective_on"}
        selected = self.model_fields_set & editable
        if not selected:
            raise ValueError("至少提供一个可修改字段")
        if any(getattr(self, field) is None for field in selected & {"title", "description", "measure_type", "priority"}):
            raise ValueError("文本和枚举字段不能设为空")
        return self


class PublishInput(VersionInput):
    assignee_id: str


class AssignInput(VersionInput):
    assignee_id: str


class ReviewInput(VersionInput):
    decision: Literal["APPROVE", "REJECT"]


def _write(request, session, actor, task_id, action, operation, body, payload):
    data = change_task(session, actor, task_id=task_id, action=action, operation=operation,
                       request_id=body.request_id, expected_version=body.expected_version,
                       payload={**payload, "note": body.note})
    return answer(request, data, session)


@router.get("/governance-tasks/assignees")
def assignees(request: Request, search: str | None = Query(None, max_length=80),
              page: int = Query(1, ge=1, le=100000), page_size: int = Query(100, ge=1, le=100),
              user: AppUser = MANAGER, session: Session = DB):
    return answer(request, list_assignees(session, search=search, page=page, page_size=page_size), session)


@router.get("/governance-tasks")
def tasks(request: Request, status: TaskStatus | None = None, my_todo: bool = False,
          page: int = Query(1, ge=1, le=100000), page_size: int = Query(20, ge=1, le=100),
          user: AppUser = MANAGER, session: Session = DB):
    data = list_tasks(session, user, status=status, my_todo=my_todo, page=page, page_size=page_size)
    return answer(request, data, session)


@router.post("/governance-tasks", status_code=201)
def create_governance_task(request: Request, body: CreateInput, user: AppUser = MANAGER,
                           session: Session = DB):
    data = create_task(session, user, request_id=body.request_id,
                       profile_id=identifier(body.profile_id), title=body.title,
                       description=body.description, measure_type=body.measure_type,
                       priority=body.priority, due_date=body.due_date,
                       effective_on=body.effective_on, radius_m=body.radius_m,
                       rationale=body.rationale)
    return answer(request, data, session)


@router.get("/governance-tasks/{task_id}/history")
def history(request: Request, task_id: str, user: AppUser = MANAGER, session: Session = DB):
    return answer(request, task_history(session, identifier(task_id), user), session)


@router.get("/governance-tasks/{task_id}")
def task_detail(request: Request, task_id: str, user: AppUser = MANAGER, session: Session = DB):
    return answer(request, get_task(session, identifier(task_id), user), session)


@router.patch("/governance-tasks/{task_id}")
def edit_task(request: Request, task_id: str, body: EditInput,
              user: AppUser = MANAGER, session: Session = DB):
    fields = ("title", "description", "measure_type", "priority", "due_date", "effective_on")
    payload = {}
    for field in body.model_fields_set & set(fields):
        value = getattr(body, field)
        payload[field] = value.isoformat() if isinstance(value, date) else value
    return _write(request, session, user, identifier(task_id), "EDIT", "TASK_EDIT", body, payload)


@router.delete("/governance-tasks/{task_id}")
def delete_draft(request: Request, task_id: str, body: VersionInput,
                 user: AppUser = MANAGER, session: Session = DB):
    return _write(request, session, user, identifier(task_id), "DELETE_DRAFT",
                   "TASK_DELETE_DRAFT", body, {})


@router.post("/governance-tasks/{task_id}/publish")
def publish_task(request: Request, task_id: str, body: PublishInput,
                 user: AppUser = MANAGER, session: Session = DB):
    return _write(request, session, user, identifier(task_id), "PUBLISH", "TASK_PUBLISH", body,
                   {"assignee_id": str(identifier(body.assignee_id))})


@router.post("/governance-tasks/{task_id}/assign")
def assign_task(request: Request, task_id: str, body: AssignInput,
                 user: AppUser = MANAGER, session: Session = DB):
    return _write(request, session, user, identifier(task_id), "ASSIGN", "TASK_ASSIGN", body,
                   {"assignee_id": str(identifier(body.assignee_id))})


@router.post("/governance-tasks/{task_id}/start")
def start_task(request: Request, task_id: str, body: VersionInput,
               user: AppUser = MANAGER, session: Session = DB):
    return _write(request, session, user, identifier(task_id), "START", "TASK_START", body, {})


@router.post("/governance-tasks/{task_id}/progress")
def progress_task(request: Request, task_id: str, body: VersionInput,
                  user: AppUser = MANAGER, session: Session = DB):
    return _write(request, session, user, identifier(task_id), "PROGRESS", "TASK_PROGRESS", body, {})


@router.post("/governance-tasks/{task_id}/submit")
def submit_task(request: Request, task_id: str, body: VersionInput,
                user: AppUser = MANAGER, session: Session = DB):
    return _write(request, session, user, identifier(task_id), "SUBMIT", "TASK_SUBMIT", body, {})


@router.post("/governance-tasks/{task_id}/review")
def review_task(request: Request, task_id: str, body: ReviewInput,
                user: AppUser = MANAGER, session: Session = DB):
    return _write(request, session, user, identifier(task_id), "REVIEW", "TASK_REVIEW", body,
                   {"decision": body.decision})


@router.post("/governance-tasks/{task_id}/cancel")
def cancel_task(request: Request, task_id: str, body: VersionInput,
                user: AppUser = MANAGER, session: Session = DB):
    return _write(request, session, user, identifier(task_id), "CANCEL", "TASK_CANCEL", body, {})
