"""M6统计接口：与共享口径statistics.py一一对应；GET请求运行在只读REPEATABLE READ快照中。"""

from datetime import date, datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.auth import current_user, database_session, fail
from app.data_api import answer, identifier
from app.spatial_api import manager
from app import statistics as stats

router = APIRouter(prefix="/api/v1")
DB = Depends(database_session, scope="function")
USER = Depends(current_user)
MANAGER = Depends(manager)


def checked_range(start: date, end: date):
    if start >= end:
        fail(422, "INVALID_RANGE", "结束日期必须晚于开始日期；结束日期不包含在范围内。")


def scope_filters(start, end, borough_id, street, vehicle_type_id, factor_id):
    return stats.collision_scope(start, end, borough_id, street, vehicle_type_id, factor_id)


@router.get("/statistics/overview")
def overview(request: Request, start: date = date(2025, 1, 1), end: date = date(2026, 1, 1),
             borough_id: int | None = Query(None, ge=1, le=5), street: str | None = Query(None, max_length=160),
             vehicle_type_id: int | None = Query(None, gt=0), factor_id: int | None = Query(None, gt=0),
             user=USER, session: Session = DB):
    checked_range(start, end)
    scope = scope_filters(start, end, borough_id, street, vehicle_type_id, factor_id)
    data = stats.overview(session, scope)
    data["filters"] = stats.filters_summary(start, end, borough_id, street, vehicle_type_id, factor_id)
    return answer(request, data, session)


@router.get("/statistics/boroughs")
def boroughs(request: Request, start: date = date(2025, 1, 1), end: date = date(2026, 1, 1),
             borough_id: int | None = Query(None, ge=1, le=5), street: str | None = Query(None, max_length=160),
             vehicle_type_id: int | None = Query(None, gt=0), factor_id: int | None = Query(None, gt=0),
             user=USER, session: Session = DB):
    checked_range(start, end)
    scope = scope_filters(start, end, borough_id, street, vehicle_type_id, factor_id)
    data = stats.boroughs(session, scope)
    data["filters"] = stats.filters_summary(start, end, borough_id, street, vehicle_type_id, factor_id)
    return answer(request, data, session)


@router.get("/statistics/trends")
def trends(request: Request, start: date = date(2025, 1, 1), end: date = date(2026, 1, 1),
           granularity: Literal["month", "hours"] = "month",
           borough_id: int | None = Query(None, ge=1, le=5), street: str | None = Query(None, max_length=160),
           vehicle_type_id: int | None = Query(None, gt=0), factor_id: int | None = Query(None, gt=0),
           user=USER, session: Session = DB):
    checked_range(start, end)
    if granularity == "month":
        stats.checked_month_limit(start, end)
    scope = scope_filters(start, end, borough_id, street, vehicle_type_id, factor_id)
    data = stats.trends_months(session, scope, start, end) if granularity == "month" else stats.trends_hours(session, scope)
    data["granularity"] = granularity
    data["filters"] = stats.filters_summary(start, end, borough_id, street, vehicle_type_id, factor_id)
    return answer(request, data, session)


@router.get("/statistics/factors")
def factors(request: Request, start: date = date(2025, 1, 1), end: date = date(2026, 1, 1),
            borough_id: int | None = Query(None, ge=1, le=5), street: str | None = Query(None, max_length=160),
            vehicle_type_id: int | None = Query(None, gt=0), factor_id: int | None = Query(None, gt=0),
            user=USER, session: Session = DB):
    checked_range(start, end)
    scope = scope_filters(start, end, borough_id, street, vehicle_type_id, factor_id)
    data = stats.factors(session, scope)
    data["filters"] = stats.filters_summary(start, end, borough_id, street, vehicle_type_id, factor_id)
    return answer(request, data, session)


@router.get("/statistics/vehicle-types")
def vehicle_types(request: Request, start: date = date(2025, 1, 1), end: date = date(2026, 1, 1),
                  borough_id: int | None = Query(None, ge=1, le=5), street: str | None = Query(None, max_length=160),
                  vehicle_type_id: int | None = Query(None, gt=0), factor_id: int | None = Query(None, gt=0),
                  user=USER, session: Session = DB):
    checked_range(start, end)
    scope = scope_filters(start, end, borough_id, street, vehicle_type_id, factor_id)
    data = stats.vehicle_types(session, scope)
    data["filters"] = stats.filters_summary(start, end, borough_id, street, vehicle_type_id, factor_id)
    return answer(request, data, session)


@router.get("/statistics/persons")
def persons(request: Request, start: date = date(2025, 1, 1), end: date = date(2026, 1, 1),
            borough_id: int | None = Query(None, ge=1, le=5), street: str | None = Query(None, max_length=160),
            vehicle_type_id: int | None = Query(None, gt=0), factor_id: int | None = Query(None, gt=0),
            user=MANAGER, session: Session = DB):
    """人员细分属于"人员详细分析"权限：ADMIN/MANAGER可读，VIEWER后端403。"""
    checked_range(start, end)
    scope = scope_filters(start, end, borough_id, street, vehicle_type_id, factor_id)
    data = stats.person_groups(session, scope)
    data["filters"] = stats.filters_summary(start, end, borough_id, street, vehicle_type_id, factor_id)
    return answer(request, data, session)


@router.get("/statistics/governance")
def governance(request: Request, status: Literal["DRAFT", "OPEN", "IN_PROGRESS", "PENDING_REVIEW",
               "COMPLETED", "CANCELLED"] | None = None, assignee_id: str | None = None,
               created_from: date | None = None, created_to: date | None = None,
               user=MANAGER, session: Session = DB):
    """模拟治理工单统计；业务筛选独立于事故筛选，VIEWER 403。"""
    number = identifier(assignee_id) if assignee_id else None
    if created_from and created_to and created_from >= created_to:
        fail(422, "INVALID_RANGE", "创建日期范围为左闭右开，结束日期必须晚于开始日期。")
    data = stats.governance_summary(session, status, number, created_from, created_to)
    data["filters"] = {"status": status, "assignee_id": assignee_id,
                       "created_from": created_from.isoformat() if created_from else None,
                       "created_to": created_to.isoformat() if created_to else None,
                       "created_to_exclusive": True, "deleted_tasks_excluded": True}
    return answer(request, data, session)
