"""M6统计口径：先确定一事故一行的筛选集合，再统计该集合内的事实。

所有事故统计共享 collision_scope 的筛选条件；车辆与原因筛选使用 EXISTS，
伤亡只取 casualty_stat 汇总，禁止把事故、人员、车辆、原因直接连接后求和。
月度空月份不补零：来源批次的声明范围不构成逐月完整证据，统一标注覆盖状态。
"""

from datetime import date, datetime, timezone

from sqlalchemy import func, literal_column, select

from app.auth import fail
from app.models import (AppUser, Borough, CasualtyStat, Collision, CollisionFactor, ContributingFactor,
                        GovernanceTask, ImportBatch, Location, LocationAssignment, Intersection,
                        Person, Vehicle, VehicleType)

BOROUGH_UNKNOWN = "未知行政区"
CASUALTY_NOTE = "伤亡为Crashes汇总口径（casualty_stat）；人员明细不完整不代表没有伤亡。"
MONTH_LIMIT = 120


def checked_month_limit(start, end):
    """月度趋势与统计CSV的月度节共用同一上限校验；按年月差计算，不先构造月份列表。"""
    if start >= end:
        fail(422, "INVALID_RANGE", "结束日期必须晚于开始日期；结束日期不包含在范围内。")
    if month_span(start, end) > MONTH_LIMIT:
        fail(422, "INVALID_RANGE", f"月度统计最多{MONTH_LIMIT}个月，请缩小日期范围。")


def street_condition(term):
    """M2同规则：转义%._\\后做两侧包含匹配。"""
    escaped = term.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    pattern = "%" + escaped + "%"
    return (Location.on_street_name.ilike(pattern, escape="\\") |
            Location.cross_street_name.ilike(pattern, escape="\\") |
            Location.off_street_name.ilike(pattern, escape="\\"))


def apply_collision_filters(statement, borough_id, street, vehicle_type_id, factor_id):
    """M2事故列表与M6导出共享的筛选实现，避免出现第二套含义。

    纯空白street视为没有街道条件：去空白后为空不再生成ILIKE，
    保证街道字段全部NULL的事故与无条件时同集合；%._\\保持字面匹配。
    """
    if borough_id:
        statement = statement.where(Location.borough_id == borough_id)
    if street and street.strip():
        statement = statement.where(street_condition(street))
    if vehicle_type_id:
        statement = statement.where(select(1).select_from(Vehicle).where(
            Vehicle.collision_id == Collision.collision_id,
            Vehicle.vehicle_type_id == vehicle_type_id).exists())
    if factor_id:
        statement = statement.where(select(1).select_from(CollisionFactor).where(
            CollisionFactor.collision_id == Collision.collision_id,
            CollisionFactor.factor_id == factor_id).exists())
    return statement


def collision_scope(start, end, borough_id=None, street=None, vehicle_type_id=None, factor_id=None):
    """一事故一行的筛选集合；命中事故后统计其全部明细，不按筛选维度裁剪明细。"""
    confirmed = select(1).select_from(LocationAssignment).join(
        Intersection, Intersection.intersection_id == LocationAssignment.intersection_id).where(
        LocationAssignment.location_id == Location.location_id,
        LocationAssignment.match_status.in_(("AUTO_MATCHED", "MANUAL_CONFIRMED")),
        Intersection.status == "CONFIRMED", Intersection.is_active.is_(True)).exists()
    statement = select(
        Collision.collision_id.label("collision_id"),
        Collision.crash_date.label("crash_date"),
        Collision.crash_time.label("crash_time"),
        Location.borough_id.label("borough_id"),
        Borough.borough_name.label("borough_name"),
        Location.geom.is_not(None).label("geocoded"),
        confirmed.label("confirmed_assigned"),
        CasualtyStat.persons_injured.label("persons_injured"),
        CasualtyStat.persons_killed.label("persons_killed"),
    ).select_from(Collision).join(
        Location, Location.location_id == Collision.location_id).outerjoin(
        Borough, Borough.borough_id == Location.borough_id).join(
        CasualtyStat, CasualtyStat.collision_id == Collision.collision_id).where(
        Collision.crash_date >= start, Collision.crash_date < end)
    statement = apply_collision_filters(statement, borough_id, street, vehicle_type_id, factor_id)
    return statement.cte("m6_scope")


def scope_description(vehicle_type_id=None, factor_id=None):
    """口径文字按实际筛选生成；未使用车型/原因筛选时不声称"涉及所选车型"。"""
    selected = [name for name, value in (("车型", vehicle_type_id), ("原因", factor_id)) if value]
    if selected:
        return f"涉及所选{'与'.join(selected)}的全部事故；统计这些事故内的全部车辆与人员明细"
    return "符合当前筛选条件的事故及其全部明细（车辆与人员记录数）"


def filters_summary(start, end, borough_id, street, vehicle_type_id, factor_id):
    """回显结构化筛选参数；street为用户自由文本，不回显原文。"""
    return {"start": start.isoformat(), "end": end.isoformat(), "end_exclusive": True,
            "borough_id": str(borough_id) if borough_id else None,
            "street_filter": bool(street and street.strip()),
            "vehicle_type_id": str(vehicle_type_id) if vehicle_type_id else None,
            "factor_id": str(factor_id) if factor_id else None,
            "collision_scope": scope_description(vehicle_type_id, factor_id)}


def scope_group_aggregates(scope):
    return [func.count().label("collision_count"),
            func.sum(scope.c.persons_injured).label("known_injured_count"),
            func.count().filter(scope.c.persons_injured.is_(None)).label("injured_missing_count"),
            func.sum(scope.c.persons_killed).label("known_killed_count"),
            func.count().filter(scope.c.persons_killed.is_(None)).label("killed_missing_count")]


def overview(session, scope):
    """空集合统一为：计数0、合计NULL、缺失0；比例分母0返回NULL。"""
    row = session.execute(select(*scope_group_aggregates(scope)).select_from(scope)).one()
    person_records = session.scalar(select(func.count()).select_from(Person).where(
        Person.collision_id.in_(select(scope.c.collision_id))))
    vehicle_records = session.scalar(select(func.count()).select_from(Vehicle).where(
        Vehicle.collision_id.in_(select(scope.c.collision_id))))
    geocoded = session.scalar(select(func.count()).select_from(scope).where(scope.c.geocoded.is_(True)))
    confirmed = session.scalar(select(func.count()).select_from(scope).where(
        scope.c.confirmed_assigned.is_(True)))
    ratio = None
    if row.collision_count:
        ratio = f"{confirmed / row.collision_count:.6f}"
    return {"collision_count": row.collision_count,
            "known_injured_count": row.known_injured_count,
            "injured_missing_count": row.injured_missing_count,
            "known_killed_count": row.known_killed_count,
            "killed_missing_count": row.killed_missing_count,
            "person_records": person_records,
            "vehicle_records": vehicle_records,
            "geocoded_count": geocoded,
            "missing_coordinates_count": row.collision_count - geocoded,
            "confirmed_assigned_count": confirmed,
            "assignment_coverage_ratio": ratio,
            "casualty_note": CASUALTY_NOTE}


def boroughs(session, scope):
    """outerjoin行政区字典在scope内完成；NULL borough保留为未知组。"""
    rows = session.execute(select(scope.c.borough_id, scope.c.borough_name,
                                  *scope_group_aggregates(scope)).select_from(scope).group_by(
        scope.c.borough_id, scope.c.borough_name).order_by(scope.c.borough_id.nulls_last())).all()
    return {"items": [{"borough_id": str(row.borough_id) if row.borough_id else None,
                       "borough_name": row.borough_name or BOROUGH_UNKNOWN,
                       "collision_count": row.collision_count,
                       "known_injured_count": row.known_injured_count,
                       "injured_missing_count": row.injured_missing_count,
                       "known_killed_count": row.known_killed_count,
                       "killed_missing_count": row.killed_missing_count} for row in rows],
            "casualty_note": CASUALTY_NOTE}


def month_span(start, end):
    """[start, end)涉及的月份数；按年月差计算，不逐月构造，供统一上限校验。"""
    diff = (end.year - start.year) * 12 + (end.month - start.month)
    return diff + 1 if end.day > 1 else diff


def month_sequence(start, end):
    """[start, end)内每月首日；推进到9999-12后安全终止，不构造越界日期。"""
    months, cursor = [], date(start.year, start.month, 1)
    while cursor < end:
        months.append(cursor)
        if cursor.month == 12:
            if cursor.year == 9999:
                break
            cursor = date(cursor.year + 1, 1, 1)
        else:
            cursor = date(cursor.year, cursor.month + 1, 1)
    return months


def month_end_bound(month_start):
    """月度覆盖比较用的月末界；9999-12没有下个月，返回该月最后一天。"""
    if month_start.month == 12:
        return date(9999, 12, 31) if month_start.year == 9999 else date(month_start.year + 1, 1, 1)
    return date(month_start.year, month_start.month + 1, 1)


def declared_ranges(session):
    """含CRASHES文件的成功批次的声明日期范围；仅用于标注覆盖，不用于补零。"""
    rows = session.execute(select(ImportBatch.requested_start, ImportBatch.requested_end,
                                  ImportBatch.input_manifest).where(ImportBatch.status == "SUCCEEDED")).all()
    ranges = []
    for batch_start, batch_end, manifest in rows:
        files = (manifest or {}).get("files", [])
        has_crashes = any(file.get("source_kind") == "CRASHES" for file in files)
        if not has_crashes:
            continue
        selected = ((manifest or {}).get("validation", {}).get("coverage", {}) or {}).get("selected_range")
        bounds = None
        if isinstance(selected, list) and len(selected) == 2:
            try:
                bounds = (date.fromisoformat(selected[0]), date.fromisoformat(selected[1]))
            except ValueError:
                bounds = None
        if bounds is None and batch_start and batch_end:
            bounds = (batch_start, batch_end)
        if bounds is not None:
            ranges.append(bounds)
    return ranges


def month_coverage(month_start, month_end, ranges):
    if month_start >= month_end:
        raise ValueError("月份区间无效")
    if ranges:
        for range_start, range_end in ranges:
            if range_start <= month_start and month_end <= range_end:
                return "NO_RECORDS_COVERAGE_UNCONFIRMED"
    return "OUTSIDE_DECLARED_RANGES"


MONTH_COVERAGE_NOTES = {
    "WITH_DATA": "有事故记录的月份",
    "NO_RECORDS_COVERAGE_UNCONFIRMED": "空月份；所在月份被成功批次声明范围覆盖，但声明范围不构成逐日完整证据，因此不补零",
    "OUTSIDE_DECLARED_RANGES": "空月份；不在任何成功批次声明范围内，可视为来源未覆盖",
}


def trends_months(session, scope, start, end):
    """按月分组；空月份返回NULL计数并标注覆盖状态，不伪造0。"""
    month_expr = func.date_trunc("month", scope.c.crash_date).label("month")
    rows = session.execute(select(month_expr, *scope_group_aggregates(scope)).select_from(scope).where(
        scope.c.crash_date.is_not(None)).group_by(literal_column("1"))).all()
    grouped = {row.month.date().replace(day=1): row for row in rows}
    ranges = declared_ranges(session)
    items = []
    for month_start in month_sequence(start, end):
        row = grouped.get(month_start)
        if row is not None:
            items.append({"month": month_start.strftime("%Y-%m"), "collision_count": row.collision_count,
                          "known_injured_count": row.known_injured_count,
                          "injured_missing_count": row.injured_missing_count,
                          "known_killed_count": row.known_killed_count,
                          "killed_missing_count": row.killed_missing_count, "coverage": "WITH_DATA"})
        else:
            items.append({"month": month_start.strftime("%Y-%m"), "collision_count": None,
                          "known_injured_count": None, "injured_missing_count": None,
                          "known_killed_count": None, "killed_missing_count": None,
                          "coverage": month_coverage(month_start, month_end_bound(month_start), ranges)})
    return {"months": items, "zero_fill": False,
            "coverage_note": "空月份不补零：coverage说明各空月的证据状态，NULL表示无记录而非0。"}


def trends_hours(session, scope):
    """0—23小时与缺失时间分别统计；NULL不归入0点。"""
    rows = session.execute(select(func.extract("hour", scope.c.crash_time).label("hour"),
                                  func.count().label("collision_count")).select_from(scope).where(
        scope.c.crash_time.is_not(None)).group_by(literal_column("1"))).all()
    counts = {int(row.hour): row.collision_count for row in rows}
    unknown = session.scalar(select(func.count()).select_from(scope).where(
        scope.c.crash_time.is_(None)))
    return {"hours": [{"hour": hour, "collision_count": counts.get(hour, 0)} for hour in range(24)],
            "unknown_time_collision_count": unknown,
            "note": "按事故当地报告时间crash_time的小时统计；缺失时间单列，不并入0点。"}


def factors(session, scope):
    """按(collision_id, factor_id)去重；同事故同原因多槽位只计一次，同事故可进多组。"""
    rows = session.execute(select(ContributingFactor.factor_id, ContributingFactor.canonical_name,
                                  ContributingFactor.display_name,
                                  func.count(func.distinct(CollisionFactor.collision_id)).label("collision_count"))
                           .select_from(CollisionFactor).join(
        ContributingFactor, ContributingFactor.factor_id == CollisionFactor.factor_id).where(
        CollisionFactor.collision_id.in_(select(scope.c.collision_id))).group_by(
        ContributingFactor.factor_id, ContributingFactor.canonical_name, ContributingFactor.display_name)
        .order_by(func.count(func.distinct(CollisionFactor.collision_id)).desc(),
                  ContributingFactor.factor_id)).all()
    no_factor = session.scalar(select(func.count()).select_from(scope).where(
        ~select(1).select_from(CollisionFactor).where(
            CollisionFactor.collision_id == scope.c.collision_id).exists()))
    return {"items": [{"factor_id": str(row.factor_id), "canonical_name": row.canonical_name,
                       "display_name": row.display_name, "collision_count": row.collision_count}
                      for row in rows],
            "no_factor_collision_count": no_factor,
            "overlap_note": "同一事故可出现在多个原因组（按collision_id去重），各组事故数之和可能大于事故总数，不能画成互斥占比图。"}


def vehicle_types(session, scope):
    """车辆记录数与不同事故数分开计数；缺失车型保留未知组。"""
    rows = session.execute(select(Vehicle.vehicle_type_id, VehicleType.canonical_name,
                                  VehicleType.display_name,
                                  func.count(Vehicle.vehicle_id).label("vehicle_records"),
                                  func.count(func.distinct(Vehicle.collision_id)).label("collision_count"))
                           .select_from(Vehicle).outerjoin(
        VehicleType, VehicleType.vehicle_type_id == Vehicle.vehicle_type_id).where(
        Vehicle.collision_id.in_(select(scope.c.collision_id))).group_by(
        Vehicle.vehicle_type_id, VehicleType.canonical_name, VehicleType.display_name)
        .order_by(func.count(func.distinct(Vehicle.collision_id)).desc(),
                  func.count(Vehicle.vehicle_id).desc(),
                  Vehicle.vehicle_type_id.nulls_first())).all()
    return {"items": [{"vehicle_type_id": str(row.vehicle_type_id) if row.vehicle_type_id else None,
                       "canonical_name": row.canonical_name,
                       "display_name": row.display_name,
                       "vehicle_records": row.vehicle_records,
                       "collision_count": row.collision_count} for row in rows],
            "overlap_note": "车型统计同时给出车辆记录数与涉及的不同事故数；同事故多辆同车型时记录数增加而事故数只计一次；未知车型单独成组。"}


def person_groups(session, scope):
    """按原始person_type×person_injury统计明细记录数；缺失保留未知，不与Crashes汇总对齐。"""
    rows = session.execute(select(Person.person_type, Person.person_injury,
                                  func.count().label("record_count")).select_from(Person).where(
        Person.collision_id.in_(select(scope.c.collision_id))).group_by(
        Person.person_type, Person.person_injury)
        .order_by(func.count().desc(), Person.person_type.nulls_first(), Person.person_injury.nulls_first())).all()
    return {"items": [{"person_type": row.person_type, "person_injury": row.person_injury,
                       "record_count": row.record_count} for row in rows],
            "note": "人员明细口径（person表记录数）；缺失类别或伤亡状态保留未知；不与Crashes伤亡汇总强行一致。"}


TASK_STATUS_LABELS = {
    "DRAFT": "草稿", "OPEN": "待执行", "IN_PROGRESS": "执行中",
    "PENDING_REVIEW": "待复核", "COMPLETED": "已完成", "CANCELLED": "已取消",
}


def governance_conditions(status, assignee_id, created_from, created_to):
    """治理统计的业务筛选独立于事故筛选；日期使用工单创建日期（UTC）左闭右开。"""
    conditions = [GovernanceTask.deleted_at.is_(None)]
    if status:
        conditions.append(GovernanceTask.status == status)
    if assignee_id:
        conditions.append(GovernanceTask.assignee_id == assignee_id)
    if created_from:
        conditions.append(GovernanceTask.created_at >= datetime(created_from.year, created_from.month, created_from.day, tzinfo=timezone.utc))
    if created_to:
        conditions.append(GovernanceTask.created_at < datetime(created_to.year, created_to.month, created_to.day, tzinfo=timezone.utc))
    return conditions


def governance_summary(session, status, assignee_id, created_from, created_to):
    """当前未软删除的模拟工单统计；总数不通过连接历史记录重复累计。"""
    conditions = governance_conditions(status, assignee_id, created_from, created_to)
    total = session.scalar(select(func.count()).select_from(GovernanceTask).where(*conditions))
    by_status = dict(session.execute(select(GovernanceTask.status, func.count()).where(*conditions)
                                     .group_by(GovernanceTask.status)).all())
    assignee_rows = session.execute(select(GovernanceTask.assignee_id, func.count().label("task_count"))
                                    .where(*conditions).group_by(GovernanceTask.assignee_id)).all()
    assignee_ids = [row.assignee_id for row in assignee_rows if row.assignee_id is not None]
    names = {user.user_id: user.display_name for user in session.scalars(
        select(AppUser).where(AppUser.user_id.in_(assignee_ids))).all()} if assignee_ids else {}
    assignees = [{"assignee_id": str(row.assignee_id) if row.assignee_id else None,
                  "assignee_name": names.get(row.assignee_id, "未分配") if row.assignee_id else "未分配",
                  "task_count": row.task_count} for row in assignee_rows]
    assignees.sort(key=lambda item: (item["assignee_id"] is None, item["assignee_id"] or 0))
    measure_rows = dict(session.execute(select(GovernanceTask.measure_type, func.count()).where(*conditions)
                                        .group_by(GovernanceTask.measure_type)).all())
    priority_rows = dict(session.execute(select(GovernanceTask.priority, func.count()).where(*conditions)
                                         .group_by(GovernanceTask.priority)).all())
    active = sum(count for state, count in by_status.items() if state in ("OPEN", "IN_PROGRESS", "PENDING_REVIEW"))
    return {"total_tasks": total,
            "by_status": [{"status": state, "label": TASK_STATUS_LABELS.get(state, state), "task_count": count}
                          for state, count in sorted(by_status.items())],
            "by_assignee": assignees,
            "by_measure_type": [{"measure_type": key, "task_count": value} for key, value in sorted(measure_rows.items())],
            "by_priority": [{"priority": key, "task_count": value} for key, value in sorted(priority_rows.items())],
            "handling": {"completed": by_status.get("COMPLETED", 0), "cancelled": by_status.get("CANCELLED", 0),
                         "in_execution": active, "draft": by_status.get("DRAFT", 0)},
            "note": "课程模拟业务统计：仅统计未软删除工单；已完成依据任务状态COMPLETED，不依据生效日期或历史条数；未分配执行人单列；总数不通过历史记录重复累计。",
            "filter_basis": "日期筛选使用工单创建时间（UTC日期，左闭右开），与事故发生日期无关。"}
