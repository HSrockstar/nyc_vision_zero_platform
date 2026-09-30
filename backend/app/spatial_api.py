"""M3地图、附近查询及交叉口人工复核接口。"""

from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import Field, field_validator
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.auth import Input, current_user, database_session, fail, response
from app.data_api import answer, identifier
from app.models import Intersection, Location, LocationAssignment, RiskProfile
from app.spatial import generate, get_intersection, manual_assignment, review

router = APIRouter(prefix="/api/v1")
DB = Depends(database_session, scope="function")
USER = Depends(current_user)


def manager(user=USER):
    if user.role_id not in (1, 2):
        fail(403, "FORBIDDEN", "此操作需要管理员或治理人员权限。")
    return user


MANAGER = Depends(manager)


def valid_bbox(west: float, south: float, east: float, north: float):
    if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
        fail(422, "INVALID_BBOX", "范围应为 west,south,east,north，且经纬度递增。")


def map_point(row):
    value = dict(row._mapping)
    value["collision_id"] = str(value["collision_id"])
    if value.get("location_id") is not None:
        value["location_id"] = str(value["location_id"])
    value["intersection_id"] = str(value["intersection_id"]) if value.get("intersection_id") else None
    return value


@router.get("/map/collisions")
def map_collisions(request: Request, start: date, end: date,
                   west: float = Query(..., ge=-180, le=180), south: float = Query(..., ge=-90, le=90),
                   east: float = Query(..., ge=-180, le=180), north: float = Query(..., ge=-90, le=90),
                   limit: int = Query(500, ge=1, le=2000), user=USER, session: Session = DB):
    if start >= end:
        fail(422, "INVALID_RANGE", "结束日期必须晚于开始日期。")
    valid_bbox(west, south, east, north)
    values = {"start": start, "end": end, "west": west, "south": south, "east": east,
              "north": north, "limit": limit + 1}
    coverage = dict(session.execute(text("""
        SELECT count(*) AS total,
          count(*) FILTER (WHERE l.geom IS NOT NULL) AS geocoded,
          count(*) FILTER (WHERE l.geom IS NULL) AS missing_coordinates,
          count(*) FILTER (WHERE a.match_status IN ('AUTO_MATCHED','MANUAL_CONFIRMED')
            AND i.status='CONFIRMED' AND i.is_active) AS confirmed_assigned,
          count(*) - count(*) FILTER (WHERE a.match_status IN ('AUTO_MATCHED','MANUAL_CONFIRMED')
            AND i.status='CONFIRMED' AND i.is_active) AS unmatched
        FROM public.collision c JOIN public.location l USING(location_id)
          LEFT JOIN public.location_assignment a USING(location_id)
          LEFT JOIN public.intersection i ON i.intersection_id=a.intersection_id
        WHERE c.crash_date >= :start AND c.crash_date < :end
    """), values).first()._mapping)
    rows = session.execute(text("""
        SELECT c.collision_id,c.crash_date,c.crash_time,l.location_id,l.borough_id,
          ST_X(l.geom) AS longitude,ST_Y(l.geom) AS latitude,
          CASE WHEN a.match_status IN ('AUTO_MATCHED','MANUAL_CONFIRMED')
                  AND i.status='CONFIRMED' AND i.is_active THEN a.intersection_id ELSE NULL END AS intersection_id
        FROM public.collision c JOIN public.location l USING(location_id)
          LEFT JOIN public.location_assignment a USING(location_id)
          LEFT JOIN public.intersection i ON i.intersection_id=a.intersection_id
        WHERE c.crash_date >= :start AND c.crash_date < :end AND l.geom IS NOT NULL
          AND l.geom && ST_MakeEnvelope(:west,:south,:east,:north,4326)
          AND ST_Intersects(l.geom, ST_MakeEnvelope(:west,:south,:east,:north,4326))
        ORDER BY c.crash_date DESC,c.collision_id DESC LIMIT :limit
    """), values).all()
    return answer(request, {"items": [map_point(row) for row in rows[:limit]],
                            "returned": min(len(rows), limit), "truncated": len(rows) > limit,
                            "coverage": coverage, "bounds": [west, south, east, north]}, session)


@router.get("/map/nearby")
def nearby(request: Request, longitude: float = Query(..., ge=-180, le=180),
           latitude: float = Query(..., ge=-90, le=90), radius_m: int = Query(200, ge=1, le=1000),
           limit: int = Query(100, ge=1, le=200), user=USER, session: Session = DB):
    rows = session.execute(text("""
        SELECT c.collision_id,c.crash_date,c.crash_time,l.location_id,l.borough_id,
          ST_X(l.geom) AS longitude,ST_Y(l.geom) AS latitude,
          ST_Distance(l.geom::geography,ST_SetSRID(ST_MakePoint(:longitude,:latitude),4326)::geography) AS distance_m,
          NULL::bigint AS intersection_id
        FROM public.location l JOIN public.collision c USING(location_id)
        WHERE l.geom IS NOT NULL AND ST_DWithin(l.geom::geography,
          ST_SetSRID(ST_MakePoint(:longitude,:latitude),4326)::geography,:radius_m)
        ORDER BY distance_m,c.collision_id LIMIT :limit
    """), {"longitude": longitude, "latitude": latitude, "radius_m": radius_m,
           "limit": limit + 1}).all()
    return answer(request, {"items": [map_point(row) for row in rows[:limit]],
                            "truncated": len(rows) > limit, "radius_m": radius_m}, session)


def intersection_data(row):
    data = dict(row._mapping)
    data["intersection_id"] = str(data["intersection_id"])
    data["borough_id"] = str(data["borough_id"]) if data["borough_id"] else None
    return data


@router.get("/intersections")
def intersections(request: Request, status: Literal["CANDIDATE", "CONFIRMED", "REJECTED"] | None = None,
                  west: float | None = Query(None, ge=-180, le=180), south: float | None = Query(None, ge=-90, le=90),
                  east: float | None = Query(None, ge=-180, le=180), north: float | None = Query(None, ge=-90, le=90),
                  page: int = Query(1, ge=1, le=100000), page_size: int = Query(50, ge=1, le=200),
                  user=USER, session: Session = DB):
    bbox = (west, south, east, north)
    if any(value is not None for value in bbox):
        if any(value is None for value in bbox):
            fail(422, "INVALID_BBOX", "范围必须同时提供四个边界。")
        valid_bbox(west, south, east, north)
    statement = select(Intersection.intersection_id, Intersection.intersection_code, Intersection.borough_id,
                       Intersection.street_a, Intersection.street_b, Intersection.status, Intersection.source_method,
                       Intersection.is_active, Intersection.version,
                       func.ST_X(Intersection.center_geom).label("longitude"),
                       func.ST_Y(Intersection.center_geom).label("latitude"))
    if status:
        statement = statement.where(Intersection.status == status)
    if west is not None:
        envelope = func.ST_MakeEnvelope(west, south, east, north, 4326)
        statement = statement.where(Intersection.center_geom.op("&&")(envelope),
                                    func.ST_Intersects(Intersection.center_geom, envelope))
    total = session.scalar(select(func.count()).select_from(statement.subquery()))
    rows = session.execute(statement.order_by(Intersection.intersection_id.desc()).offset((page-1)*page_size).limit(page_size)).all()
    return answer(request, {"items": [intersection_data(row) for row in rows], "total": total}, session)


@router.get("/intersections/{intersection_id}")
def intersection_detail(intersection_id: str, request: Request, user=USER, session: Session = DB):
    number = identifier(intersection_id)
    item = get_intersection(session, number)
    row = session.execute(select(Intersection.intersection_id, Intersection.intersection_code, Intersection.borough_id,
         Intersection.street_a, Intersection.street_b, Intersection.status, Intersection.source_method,
         Intersection.is_active, Intersection.version,
         func.ST_X(Intersection.center_geom).label("longitude"),
         func.ST_Y(Intersection.center_geom).label("latitude")).where(Intersection.intersection_id == number)).first()
    data = intersection_data(row)
    data["created_at"] = item.created_at.isoformat()
    data["confirmed_at"] = item.confirmed_at.isoformat() if item.confirmed_at else None
    if user.role_id in (1, 2):
        data["confirmation_note"] = item.confirmation_note
    data["location_count"] = session.scalar(select(func.count()).select_from(LocationAssignment).where(
        LocationAssignment.intersection_id == number))
    data["risk_profile_count"] = session.scalar(select(func.count()).select_from(RiskProfile).where(
        RiskProfile.intersection_id == number))
    samples = session.execute(text("""
        SELECT l.location_id,l.on_street_name,l.cross_street_name,l.borough_id,
          ST_X(l.geom) AS longitude,ST_Y(l.geom) AS latitude,
          a.match_status,a.distance_m,a.version
        FROM public.location_assignment a JOIN public.location l USING(location_id)
        WHERE a.intersection_id=:number ORDER BY l.location_id LIMIT 20
    """), {"number": number}).mappings()
    data["locations"] = [{**row, "location_id": str(row["location_id"]),
                          "distance_m": float(row["distance_m"]) if row["distance_m"] is not None else None}
                         for row in samples]
    return answer(request, data, session)


@router.get("/location-assignments/{location_id}")
def assignment_detail(location_id: str, request: Request, user=USER, session: Session = DB):
    number = identifier(location_id)
    location = session.get(Location, number)
    if location is None:
        fail(404, "NOT_FOUND", "观察地点不存在。")
    assignment = session.get(LocationAssignment, number)
    coords = session.execute(select(func.ST_X(Location.geom), func.ST_Y(Location.geom)).where(
        Location.location_id == number)).first()
    data = {"location_id": str(number), "borough_id": str(location.borough_id) if location.borough_id else None,
            "on_street_name": location.on_street_name, "cross_street_name": location.cross_street_name,
            "longitude": coords[0], "latitude": coords[1],
            "intersection_id": str(assignment.intersection_id) if assignment and assignment.intersection_id else None,
            "match_status": assignment.match_status if assignment else "UNMATCHED",
            "version": assignment.version if assignment else 0}
    if user.role_id in (1, 2):
        data["evidence"] = assignment.evidence if assignment else {}
        data["reviewed_at"] = assignment.reviewed_at.isoformat() if assignment and assignment.reviewed_at else None
    return answer(request, data, session)


class GenerateInput(Input):
    borough_id: int = Field(ge=1, le=5)
    after_location_id: int = Field(default=0, ge=0, le=9223372036854775807)
    max_locations: int = Field(default=100, ge=1, le=100)
    radius_m: int = Field(default=50, ge=20, le=80)


@router.post("/intersection-candidates/generate")
def generate_candidates(body: GenerateInput, request: Request, user=MANAGER, session: Session = DB):
    result = generate(session, user.user_id, request.state.request_id,
                      borough_id=body.borough_id, after_location_id=body.after_location_id,
                      max_locations=body.max_locations, radius_m=body.radius_m)
    return response(request, result)


class ReviewInput(Input):
    version: int = Field(gt=0)
    note: str = Field(min_length=1, max_length=2000)

    @field_validator("note")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("理由不能为空")
        return value.strip()


@router.post("/intersections/{intersection_id}/confirm")
def confirm(intersection_id: str, body: ReviewInput, request: Request, user=MANAGER, session: Session = DB):
    return response(request, review(session, user.user_id, request.state.request_id,
                                    identifier(intersection_id), body.version, body.note, confirm=True))


@router.post("/intersections/{intersection_id}/reject")
def reject(intersection_id: str, body: ReviewInput, request: Request, user=MANAGER, session: Session = DB):
    return response(request, review(session, user.user_id, request.state.request_id,
                                    identifier(intersection_id), body.version, body.note, confirm=False))


class AssignmentInput(Input):
    version: int = Field(ge=0)
    status: Literal["MANUAL_CONFIRMED", "REJECTED", "UNMATCHED"]
    intersection_id: int | None = Field(default=None, gt=0, le=9223372036854775807)
    reason: str = Field(min_length=1, max_length=2000)

    @field_validator("reason")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("理由不能为空")
        return value.strip()


@router.patch("/location-assignments/{location_id}")
def change_assignment(location_id: str, body: AssignmentInput, request: Request,
                      user=MANAGER, session: Session = DB):
    return response(request, manual_assignment(session, user.user_id, request.state.request_id,
                     identifier(location_id), body.version, body.status, body.intersection_id, body.reason))
