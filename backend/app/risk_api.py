"""M4规则、运行状态和限定单批次的历史画像查询。"""

from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.auth import Input, current_user, database_session, fail
from app.data_api import answer, identifier
from app.models import DatasetState, RiskRule, RiskRun
from app.risks import create_run
from app.spatial_api import manager

router = APIRouter(prefix="/api/v1")
DB = Depends(database_session, scope="function")
USER = Depends(current_user)
MANAGER = Depends(manager)


class RunInput(Input):
    request_id: UUID
    rule_id: str
    period_start: date
    period_end: date


def values(data):
    result = dict(data)
    for key, value in result.items():
        if key.endswith("_id") or key == "input_revision":
            result[key] = str(value) if value is not None else None
        elif isinstance(value, Decimal):
            result[key] = str(value)
    return result


def run_data(run, revision):
    columns = ("run_id", "request_id", "rule_id", "period_start", "period_end", "input_revision", "status",
               "requested_by", "created_at", "started_at", "finished_at", "attempt_no", "error_summary",
               "coverage_summary", "input_manifest")
    data = values({name: getattr(run, name) for name in columns})
    data["requested_by"] = str(run.requested_by)
    data["is_stale"] = run.status == "SUCCEEDED" and run.input_revision != revision
    return data


@router.get("/risk-rules")
def rules(request: Request, user=USER, session: Session = DB):
    rows = session.execute(select(RiskRule).where(RiskRule.status.in_(("PUBLISHED", "RETIRED"))).order_by(
        RiskRule.rule_code, RiskRule.version_no.desc())).scalars().all()
    return answer(request, {"items": [values({col.name: getattr(row, col.name)
                    for col in RiskRule.__table__.columns}) for row in rows]}, session)


@router.post("/risk-runs", status_code=202)
def request_run(request: Request, body: RunInput, user=MANAGER, session: Session = DB):
    run = create_run(session, user, body.request_id, identifier(body.rule_id), body.period_start, body.period_end)
    revision = session.scalar(select(DatasetState.revision).where(DatasetState.state_id == 1))
    return answer(request, run_data(run, revision), session)


@router.get("/risk-runs")
def runs(request: Request, start: date | None = None, end: date | None = None,
         rule_id: str | None = None, status: Literal["QUEUED", "RUNNING", "SUCCEEDED", "FAILED"] | None = None,
         page: int = Query(1, ge=1, le=100000), page_size: int = Query(20, ge=1, le=100),
         user=USER, session: Session = DB):
    statement = select(RiskRun)
    if start is not None:
        statement = statement.where(RiskRun.period_start == start)
    if end is not None:
        statement = statement.where(RiskRun.period_end == end)
    if rule_id is not None:
        statement = statement.where(RiskRun.rule_id == identifier(rule_id))
    if status:
        statement = statement.where(RiskRun.status == status)
    count = session.scalar(select(func.count()).select_from(statement.subquery()))
    rows = session.scalars(statement.order_by(RiskRun.run_id.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    revision = session.scalar(select(DatasetState.revision).where(DatasetState.state_id == 1))
    return answer(request, {"items": [run_data(row, revision) for row in rows], "total": count,
                            "page": page, "page_size": page_size}, session)


def get_run(session, run_id):
    run = session.get(RiskRun, run_id)
    if run is None:
        fail(404, "RISK_RUN_NOT_FOUND", "未找到计算批次。")
    return run


@router.get("/risk-runs/{run_id}")
def run_detail(request: Request, run_id: str, user=USER, session: Session = DB):
    run = get_run(session, identifier(run_id))
    revision = session.scalar(select(DatasetState.revision).where(DatasetState.state_id == 1))
    return answer(request, run_data(run, revision), session)


@router.get("/risk-profiles")
def profiles(request: Request, run_id: str, risk_level: Literal["LOW", "MEDIUM", "HIGH", "UNKNOWN"] | None = None,
             intersection_id: str | None = None, sort: Literal["score", "collision_count"] = "score",
             page: int = Query(1, ge=1, le=100000), page_size: int = Query(20, ge=1, le=100),
             user=USER, session: Session = DB):
    run = get_run(session, identifier(run_id))
    if run.status != "SUCCEEDED":
        return answer(request, {"items": [], "total": 0, "page": page, "page_size": page_size,
                                "run_status": run.status}, session)
    where = "run_id=:run_id"
    params = {"run_id": run.run_id, "limit": page_size, "offset": (page - 1) * page_size}
    if risk_level:
        where += " AND risk_level=:level"
        params["level"] = risk_level
    if intersection_id is not None:
        where += " AND intersection_id=:intersection"
        params["intersection"] = identifier(intersection_id)
    total = session.scalar(text("SELECT count(*) FROM public.v_risk_profile WHERE " + where), params)
    rows = session.execute(text("SELECT * FROM public.v_risk_profile WHERE " + where +
        " ORDER BY " + sort + " DESC NULLS LAST,intersection_id LIMIT :limit OFFSET :offset"), params).mappings()
    return answer(request, {"items": [values(row) for row in rows], "total": total,
                            "page": page, "page_size": page_size, "run_status": run.status}, session)


@router.get("/risk-profiles/{profile_id}")
def profile_detail(request: Request, profile_id: str, user=USER, session: Session = DB):
    row = session.execute(text("SELECT * FROM public.v_risk_profile WHERE profile_id=:id"),
                          {"id": identifier(profile_id)}).mappings().one_or_none()
    if row is None:
        fail(404, "RISK_PROFILE_NOT_FOUND", "该批次未生成可见画像。")
    rule = session.get(RiskRule, row["rule_id"])
    data = values(row)
    data["contributions"] = {name: str(row[count] * getattr(rule, weight)) for name, count, weight in (
        ("collision", "collision_count", "weight_collision"), ("injured", "injured_count", "weight_injured"),
        ("killed", "killed_count", "weight_killed"), ("vru", "vulnerable_road_user_count", "weight_vru"))}
    data["run"] = run_data(session.get(RiskRun, row["run_id"]),
                          session.scalar(select(DatasetState.revision).where(DatasetState.state_id == 1)))
    return answer(request, data, session)
