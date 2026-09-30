"""M3受控候选生成、人工确认与观察地点归属。"""

from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID
import unicodedata

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.auth import fail
from app.models import AuditLog, DatasetState, Intersection, Location, LocationAssignment

ALGORITHM = "m3-anchor-v1"
WORKFLOW_LOCK = 76301003


def street(value: str | None) -> str:
    return " ".join(unicodedata.normalize("NFKC", value or "").casefold().split()).upper()


def pair(a: str | None, b: str | None) -> tuple[str, str] | None:
    names = sorted((street(a), street(b)))
    return (names[0], names[1]) if names[0] and names[1] and names[0] != names[1] else None


def lock_workflow(session: Session) -> None:
    session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": WORKFLOW_LOCK})


def revision(session: Session, note: str) -> str:
    state = session.scalar(select(DatasetState).where(DatasetState.state_id == 1).with_for_update())
    state.revision += 1
    state.updated_at = datetime.now(timezone.utc)
    state.last_change_note = note
    session.flush()
    return str(state.revision)


def audit(session: Session, actor_id: int, action: str, entity_type: str, entity_id: int | None,
          request_id: UUID, details: dict) -> None:
    session.add(AuditLog(actor_id=actor_id, action=action, entity_type=entity_type,
                         entity_id=str(entity_id) if entity_id is not None else None,
                         request_id=request_id, details=details))


def nearby_intersections(session: Session, location_id: int, radius_m: int, names: tuple[str, str], borough_id: int):
    rows = session.execute(text("""
        SELECT i.intersection_id, i.intersection_code, i.status, i.street_a, i.street_b,
               ST_Distance(i.center_geom::geography, l.geom::geography) AS distance_m
        FROM public.intersection i JOIN public.location l ON l.location_id=:location_id
        WHERE i.borough_id=:borough_id AND i.is_active AND
              ST_DWithin(i.center_geom::geography, l.geom::geography, :radius_m)
        ORDER BY i.intersection_id
    """), {"location_id": location_id, "borough_id": borough_id, "radius_m": radius_m}).mappings()
    return [row for row in rows if pair(row["street_a"], row["street_b"]) == names]


def assign_generated(session: Session, location: Location, status: str, target: int | None,
                     distance: float | None, evidence: dict) -> bool:
    current = session.get(LocationAssignment, location.location_id)
    if current and (current.match_method in ("MANUAL", "M3_REVIEW") or
                    current.match_status in ("MANUAL_CONFIRMED", "AUTO_MATCHED", "REJECTED")):
        return False
    if current and current.match_status == status and current.intersection_id == target and current.evidence == evidence:
        return False
    if current is None:
        session.add(LocationAssignment(location_id=location.location_id, intersection_id=target,
                                       match_status=status, match_method="M3_GENERATE",
                                       algorithm_version=ALGORITHM, distance_m=distance, evidence=evidence))
    else:
        current.intersection_id = target
        current.match_status = status
        current.match_method = "M3_GENERATE"
        current.algorithm_version = ALGORITHM
        current.distance_m = distance
        current.evidence = evidence
        current.version += 1
        current.updated_at = datetime.now(timezone.utc)
    return True


def generate(session: Session, actor_id: int, request_id: UUID, *, borough_id: int,
             after_location_id: int = 0, max_locations: int = 100, radius_m: int = 50) -> dict:
    lock_workflow(session)
    ids = session.scalars(text("""
        SELECT location_id FROM public.location
        WHERE location_id > :after AND borough_id=:borough_id AND geom IS NOT NULL
          AND NULLIF(btrim(on_street_name), '') IS NOT NULL
          AND NULLIF(btrim(cross_street_name), '') IS NOT NULL
        ORDER BY location_id LIMIT :limit
    """), {"after": after_location_id, "borough_id": borough_id, "limit": max_locations + 1}).all()
    page, has_more = ids[:max_locations], len(ids) > max_locations
    counts = {"processed": len(page), "created_candidates": 0, "auto_matched": 0,
              "candidate_assignments": 0, "unchanged": 0, "invalid_pair": 0}
    for location_id in page:
        location = session.get(Location, location_id)
        names = pair(location.on_street_name, location.cross_street_name)
        if names is None:
            counts["invalid_pair"] += 1
            continue
        previous = session.get(LocationAssignment, location_id)
        if previous and (previous.match_method in ("MANUAL", "M3_REVIEW") or
                         previous.match_status in ("MANUAL_CONFIRMED", "AUTO_MATCHED", "REJECTED")):
            counts["unchanged"] += 1
            continue
        nearby = nearby_intersections(session, location_id, radius_m, names, borough_id)
        confirmed = [item for item in nearby if item["status"] == "CONFIRMED"]
        candidates = [item for item in nearby if item["status"] == "CANDIDATE"]
        rejected = [item for item in nearby if item["status"] == "REJECTED"]
        if len(confirmed) == 1:
            status, target, distance = "AUTO_MATCHED", confirmed[0]["intersection_id"], confirmed[0]["distance_m"]
        elif len(confirmed) > 1:
            status, target, distance = "CANDIDATE", None, None
        elif len(candidates) == 1:
            status, target, distance = "CANDIDATE", candidates[0]["intersection_id"], candidates[0]["distance_m"]
        elif len(candidates) > 1 or rejected:
            status, target, distance = "CANDIDATE", None, None
        else:
            candidate = Intersection(intersection_code=f"NYC-M3-{location_id}", borough_id=borough_id,
                                     street_a=names[0], street_b=names[1], center_geom=location.geom,
                                     status="CANDIDATE", source_method="DERIVED")
            session.add(candidate)
            session.flush()
            target, status, distance = candidate.intersection_id, "CANDIDATE", 0.0
            counts["created_candidates"] += 1
            candidates = [{"intersection_id": target, "intersection_code": candidate.intersection_code,
                           "distance_m": distance}]
        evidence = {"algorithm_version": ALGORITHM, "radius_m": radius_m,
                    "anchor_location_id": next((item["intersection_code"].removeprefix("NYC-M3-")
                        for item in candidates if item["intersection_code"].startswith("NYC-M3-")), None),
                    "candidate_ids": [str(item["intersection_id"]) for item in candidates],
                    "confirmed_ids": [str(item["intersection_id"]) for item in confirmed],
                    "rejected_ids": [str(item["intersection_id"]) for item in rejected],
                    "anchor_method": "首个观察点固定中心；不串联扩张"}
        if assign_generated(session, location, status, target, distance, evidence):
            counts["auto_matched" if status == "AUTO_MATCHED" else "candidate_assignments"] += 1
        else:
            counts["unchanged"] += 1
    if counts["auto_matched"]:
        revision(session, "M3自动归属：行政区" + str(borough_id))
    if counts["created_candidates"] or counts["auto_matched"] or counts["candidate_assignments"]:
        audit(session, actor_id, "INTERSECTION_CANDIDATES_GENERATED", "intersection", None, request_id,
              {"borough_id": borough_id, "radius_m": radius_m, **counts,
               "after_location_id": str(after_location_id), "last_location_id": str(page[-1]) if page else None})
    return {**counts, "last_location_id": str(page[-1]) if page else str(after_location_id),
            "has_more": has_more, "algorithm_version": ALGORITHM, "radius_m": radius_m}


def get_intersection(session: Session, number: int, *, lock: bool = False) -> Intersection:
    statement = select(Intersection).where(Intersection.intersection_id == number)
    item = session.scalar(statement.with_for_update() if lock else statement)
    if item is None:
        fail(404, "NOT_FOUND", "交叉口不存在。")
    return item


def review(session: Session, actor_id: int, request_id: UUID, number: int, expected_version: int,
           note: str, *, confirm: bool) -> dict:
    lock_workflow(session)
    item = get_intersection(session, number, lock=True)
    if item.version != expected_version or item.status != "CANDIDATE":
        fail(409, "VERSION_CONFLICT", "候选状态或版本已改变，请刷新后重试。")
    now = datetime.now(timezone.utc)
    item.status = "CONFIRMED" if confirm else "REJECTED"
    item.confirmation_note = note
    if confirm:
        item.confirmed_by, item.confirmed_at = actor_id, now
    item.version += 1
    item.updated_at = now
    session.flush()
    changed, ambiguous = 0, 0
    if confirm:
        # 新确认对象也可能让旧自动归属变成多解；同事务重新审查其最大允许半径内的生成结果。
        location_ids = session.scalars(text("""
            SELECT a.location_id FROM public.location_assignment a
              JOIN public.location l USING(location_id)
            WHERE a.match_method='M3_GENERATE' AND a.match_status IN ('CANDIDATE','AUTO_MATCHED')
              AND l.borough_id=:borough_id AND l.geom IS NOT NULL
              AND ST_DWithin(l.geom::geography,
                (SELECT center_geom::geography FROM public.intersection WHERE intersection_id=:number),80)
            ORDER BY a.location_id
        """), {"borough_id": item.borough_id, "number": number}).all()
        assignments = [session.get(LocationAssignment, location_id, with_for_update=True) for location_id in location_ids]
    else:
        assignments = session.scalars(select(LocationAssignment).where(
            LocationAssignment.intersection_id == number,
            LocationAssignment.match_status == "CANDIDATE").order_by(LocationAssignment.location_id).with_for_update()).all()
    for assignment in assignments:
        if assignment.match_method != "M3_GENERATE":
            continue
        if confirm:
            location = session.get(Location, assignment.location_id)
            if pair(location.on_street_name, location.cross_street_name) != pair(item.street_a, item.street_b):
                continue
            matches = [row for row in nearby_intersections(session, location.location_id,
                       int(assignment.evidence.get("radius_m", 50)),
                       pair(location.on_street_name, location.cross_street_name), location.borough_id)
                       if row["status"] == "CONFIRMED"]
            if len(matches) == 1:
                new_status, new_target, distance = "AUTO_MATCHED", matches[0]["intersection_id"], matches[0]["distance_m"]
            elif len(matches) > 1:
                new_status, new_target, distance = "CANDIDATE", None, None
            else:
                continue
            if assignment.match_status == new_status and assignment.intersection_id == new_target:
                continue
            assignment.match_status = new_status
            assignment.intersection_id = new_target
            assignment.distance_m = distance
            assignment.evidence = {**assignment.evidence,
                "confirmed_ids": [str(row["intersection_id"]) for row in matches]}
            if len(matches) > 1:
                ambiguous += 1
            changed += 1
        else:
            assignment.match_status = "REJECTED"
            assignment.intersection_id = None
            assignment.match_method = "M3_REVIEW"
            assignment.reviewed_by = actor_id
            assignment.reviewed_at = now
            assignment.evidence = {**assignment.evidence, "reason": note, "rejected_intersection_id": str(number)}
            changed += 1
        assignment.version += 1
        assignment.updated_at = now
    data_revision = revision(session, "M3候选确认" if confirm else "M3候选拒绝")
    audit(session, actor_id, "INTERSECTION_CONFIRMED" if confirm else "INTERSECTION_REJECTED",
          "intersection", number, request_id, {"note": note, "version": item.version,
                                                  "assignments_changed": changed, "ambiguous": ambiguous,
                                                  "data_revision": data_revision})
    return {"intersection_id": str(number), "status": item.status, "version": item.version,
            "assignments_changed": changed, "ambiguous": ambiguous, "data_revision": data_revision}


def manual_assignment(session: Session, actor_id: int, request_id: UUID, location_id: int,
                      expected_version: int, status: str, intersection_id: int | None, reason: str) -> dict:
    lock_workflow(session)
    location = session.get(Location, location_id)
    if location is None:
        fail(404, "NOT_FOUND", "观察地点不存在。")
    target = None
    if status == "MANUAL_CONFIRMED":
        if intersection_id is None:
            fail(422, "INVALID_TARGET", "人工确认需要已确认交叉口。")
        target = get_intersection(session, intersection_id)
        if target.status != "CONFIRMED" or not target.is_active:
            fail(409, "TARGET_INVALID", "只能归属到启用的已确认交叉口。")
    elif intersection_id is not None:
        fail(422, "INVALID_TARGET", "未匹配或拒绝状态不能保留目标交叉口。")
    current = session.get(LocationAssignment, location_id, with_for_update=True)
    if (current.version if current else 0) != expected_version:
        fail(409, "VERSION_CONFLICT", "归属版本已改变，请刷新后重试。")
    distance = None
    if target is not None and location.geom is not None:
        distance = session.scalar(text("""
            SELECT ST_Distance(i.center_geom::geography,l.geom::geography)
            FROM public.intersection i, public.location l
            WHERE i.intersection_id=:intersection_id AND l.location_id=:location_id
        """), {"intersection_id": intersection_id, "location_id": location_id})
    now = datetime.now(timezone.utc)
    evidence = {"reason": reason, "manual_target": str(intersection_id) if intersection_id else None}
    if current is None:
        current = LocationAssignment(location_id=location_id, intersection_id=intersection_id,
                                     match_status=status, match_method="MANUAL", algorithm_version=ALGORITHM,
                                     distance_m=distance, evidence=evidence, reviewed_by=actor_id, reviewed_at=now)
        session.add(current)
    else:
        current.intersection_id = intersection_id
        current.match_status = status
        current.match_method = "MANUAL"
        current.algorithm_version = ALGORITHM
        current.distance_m = distance
        current.evidence = evidence
        current.reviewed_by = actor_id
        current.reviewed_at = now
        current.version += 1
        current.updated_at = now
    data_revision = revision(session, "M3人工地点归属")
    audit(session, actor_id, "LOCATION_ASSIGNMENT_REVIEWED", "location_assignment", location_id,
          request_id, {"status": status, "target": str(intersection_id) if intersection_id else None,
                       "reason": reason, "version": current.version, "data_revision": data_revision})
    session.flush()
    return {"location_id": str(location_id), "intersection_id": str(intersection_id) if intersection_id else None,
            "match_status": status, "version": current.version, "data_revision": data_revision}
