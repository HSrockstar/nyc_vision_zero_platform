"""M6导出：与统计/列表同一筛选集合的CSV导出；默认上限5000行数据，超限明确拒绝。

CSV使用UTF-8 BOM与CRLF改善Windows表格软件兼容；说明行以#开头，不计入数据行数。
用户可控文本在导出前做公式起始字符防护；NULL导出为空字段，不导出为0。
"""

import csv
import io
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import current_user, database_session, fail
from app.data_api import collision_statement
from app.models import Collision, DatasetState
from app.spatial_api import manager
from app import statistics as stats

router = APIRouter(prefix="/api/v1")
DB = Depends(database_session, scope="function")
USER = Depends(current_user)
MANAGER = Depends(manager)
EXPORT_ROW_LIMIT = 5000

FORMULA_PREFIXES = ("=", "+", "-", "@")
LEADING_SKIP = "".join(chr(code) for code in range(33))


def csv_safe(value):
    """文本列公式防护：跳过前导空白与控制字符后命中=+-@时前置单引号。"""
    if not isinstance(value, str) or value == "":
        return value
    if value.lstrip(LEADING_SKIP).startswith(FORMULA_PREFIXES):
        return "'" + value
    return value


def csv_cell(value, guard):
    if value is None:
        return ""
    if isinstance(value, str):
        return csv_safe(value) if guard else value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def csv_response(filename, buffer):
    return Response(buffer.getvalue().encode("utf-8"), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


def new_csv():
    buffer = io.StringIO(newline="")
    buffer.write("\ufeff")
    return buffer, csv.writer(buffer, lineterminator="\r\n")


def comment(writer, lines):
    for line in lines:
        writer.writerow(["# " + line])


def export_notes(writer, title, filters, revision, extra):
    comment(writer, ["Vision Zero 课程项目 · " + title])
    comment(writer, ["生成时间（UTC）: " + datetime.now(timezone.utc).isoformat(timespec="seconds"),
                     f"数据版本 revision: {revision}",
                     f"统计区间: [{filters['start']}, {filters['end']}) ，结束日期为排他上界（不含当天）",
                     f"行政区筛选: {filters['borough_id'] or '全部'}；街道筛选: {'已应用' if filters['street_filter'] else '无'}；"
                     f"车型筛选: {filters['vehicle_type_id'] or '全部'}；原因筛选: {filters['factor_id'] or '全部'}",
                     "车型/原因筛选用于选出涉及的事故；车辆与人员明细统计这些事故内的全部记录。",
                     "伤亡为Crashes汇总口径（casualty_stat）；人员明细不完整不代表没有伤亡。",
                     "NULL导出为空字段，表示数值缺失，不是0。", *extra])


COLLISION_COLUMNS = [("collision_id", False), ("crash_date", False), ("crash_time", False),
                     ("borough_name", True), ("on_street_name", True), ("cross_street_name", True),
                     ("off_street_name", True), ("latitude", False), ("longitude", False),
                     ("persons_injured", False), ("persons_killed", False),
                     ("pedestrians_injured", False), ("pedestrians_killed", False),
                     ("cyclists_injured", False), ("cyclists_killed", False),
                     ("motorists_injured", False), ("motorists_killed", False)]


@router.get("/exports/collisions.csv")
def collisions_csv(request: Request, start: date = date(2025, 1, 1), end: date = date(2026, 1, 1),
                   borough_id: int | None = Query(None, ge=1, le=5), street: str | None = Query(None, max_length=160),
                   vehicle_type_id: int | None = Query(None, gt=0), factor_id: int | None = Query(None, gt=0),
                   user=USER, session: Session = DB):
    """当前筛选范围的事故列表CSV；与/collisions同一筛选实现，稳定排序crash_date、collision_id。"""
    if start >= end:
        fail(422, "INVALID_RANGE", "结束日期必须晚于开始日期；结束日期不包含在范围内。")
    statement = stats.apply_collision_filters(collision_statement().where(
        Collision.crash_date >= start, Collision.crash_date < end),
        borough_id, street, vehicle_type_id, factor_id)
    rows = session.execute(statement.order_by(Collision.crash_date, Collision.collision_id)
                           .limit(EXPORT_ROW_LIMIT + 1)).all()
    if len(rows) > EXPORT_ROW_LIMIT:
        fail(400, "EXPORT_ROW_LIMIT",
             f"当前筛选范围的导出结果超过{EXPORT_ROW_LIMIT}行上限，请缩小日期范围或其他筛选条件后重试。")
    filters = stats.filters_summary(start, end, borough_id, street, vehicle_type_id, factor_id)
    revision = session.scalar(select_revision())
    buffer, writer = new_csv()
    export_notes(writer, "事故列表导出", filters, revision,
                 [f"数据行数: {len(rows)}（不含#说明行）；排序: crash_date、collision_id 升序"])
    writer.writerow([name for name, _ in COLLISION_COLUMNS])
    for row in rows:
        mapping = row._mapping
        writer.writerow([csv_cell(mapping[name], guard) for name, guard in COLLISION_COLUMNS])
    return csv_response("vision-zero-collisions.csv", buffer)


def select_revision():
    return select(DatasetState.revision).where(DatasetState.state_id == 1)


@router.get("/exports/statistics.csv")
def statistics_csv(request: Request, start: date = date(2025, 1, 1), end: date = date(2026, 1, 1),
                   borough_id: int | None = Query(None, ge=1, le=5), street: str | None = Query(None, max_length=160),
                   vehicle_type_id: int | None = Query(None, gt=0), factor_id: int | None = Query(None, gt=0),
                   user=MANAGER, session: Session = DB):
    """统一统计报表CSV：含人员细分节，权限为ADMIN/MANAGER；同一快照内一次生成。

    报表为聚合结果（组数受字典大小约束），不设事故CSV的5000行数据上限；
    月度节与月度趋势接口共用同一月份范围校验。
    """
    if start >= end:
        fail(422, "INVALID_RANGE", "结束日期必须晚于开始日期；结束日期不包含在范围内。")
    stats.checked_month_limit(start, end)
    scope = stats.collision_scope(start, end, borough_id, street, vehicle_type_id, factor_id)
    filters = stats.filters_summary(start, end, borough_id, street, vehicle_type_id, factor_id)
    revision = session.scalar(select_revision())
    buffer, writer = new_csv()
    export_notes(writer, "统计报表导出", filters, revision,
                 ["本报表在同一数据库快照内一次生成；各节数据对应GET /statistics/*接口。",
                  "本报表为聚合结果，不设事故CSV的5000行数据上限；事故列表导出上限仍为5000行数据。",
                  "原因/车型组别之间存在重叠（同一事故可属于多个组），各组计数之和可能大于事故总数。",
                  "月度空月份不补零，coverage列说明其覆盖证据状态。"])
    overview = stats.overview(session, scope)
    comment(writer, ["[总览] 单位：事故数/记录数/人数"])
    writer.writerow(["指标", "值"])
    for label, key in (("不同事故数", "collision_count"), ("已知受伤合计", "known_injured_count"),
                       ("受伤缺失事故数", "injured_missing_count"), ("已知死亡合计", "known_killed_count"),
                       ("死亡缺失事故数", "killed_missing_count"), ("人员明细记录数", "person_records"),
                       ("车辆明细记录数", "vehicle_records"), ("有坐标事故数", "geocoded_count"),
                       ("缺坐标事故数", "missing_coordinates_count"),
                       ("正式归属已确认交叉口事故数", "confirmed_assigned_count"),
                       ("归属覆盖率", "assignment_coverage_ratio")):
        writer.writerow([label, csv_cell(overview[key], False)])
    comment(writer, ["[行政区] 单位：事故数/人数；未知行政区单独成组"])
    writer.writerow(["borough_id", "borough_name", "collision_count", "known_injured_count",
                     "injured_missing_count", "known_killed_count", "killed_missing_count"])
    for item in stats.boroughs(session, scope)["items"]:
        writer.writerow([item["borough_id"] or "", csv_cell(item["borough_name"], True),
                         item["collision_count"], csv_cell(item["known_injured_count"], False),
                         item["injured_missing_count"], csv_cell(item["known_killed_count"], False),
                         item["killed_missing_count"]])
    months = stats.trends_months(session, scope, start, end)
    comment(writer, ["[月度趋势] 单位：事故数/人数；空月份计数为空，coverage说明覆盖证据；缺失列为伤亡值缺失的事故数"])
    writer.writerow(["month", "collision_count", "known_injured_count", "injured_missing_count",
                     "known_killed_count", "killed_missing_count", "coverage"])
    for item in months["months"]:
        writer.writerow([item["month"], csv_cell(item["collision_count"], False),
                         csv_cell(item["known_injured_count"], False),
                         csv_cell(item["injured_missing_count"], False),
                         csv_cell(item["known_killed_count"], False),
                         csv_cell(item["killed_missing_count"], False), item["coverage"]])
    hours = stats.trends_hours(session, scope)
    comment(writer, ["[小时分布] 单位：事故数；缺失时间单列，不并入0点"])
    writer.writerow(["hour", "collision_count"])
    for item in hours["hours"]:
        writer.writerow([item["hour"], item["collision_count"]])
    writer.writerow(["unknown", hours["unknown_time_collision_count"]])
    factor_data = stats.factors(session, scope)
    comment(writer, ["[原因分析] 单位：不同事故数；组别可重叠"])
    writer.writerow(["factor_id", "canonical_name", "display_name", "collision_count"])
    for item in factor_data["items"]:
        writer.writerow([item["factor_id"], csv_cell(item["canonical_name"], True),
                         csv_cell(item["display_name"], True), item["collision_count"]])
    writer.writerow(["", csv_cell("(无原因记录的事故)", True), "",
                     factor_data["no_factor_collision_count"]])
    vehicle_data = stats.vehicle_types(session, scope)
    comment(writer, ["[车辆类型] 单位：车辆记录数 / 不同事故数；未知车型单独成组"])
    writer.writerow(["vehicle_type_id", "canonical_name", "display_name", "vehicle_records", "collision_count"])
    for item in vehicle_data["items"]:
        writer.writerow([item["vehicle_type_id"] or "", csv_cell(item["canonical_name"], True),
                         csv_cell(item["display_name"], True), item["vehicle_records"], item["collision_count"]])
    person_data = stats.person_groups(session, scope)
    comment(writer, ["[人员类别与伤亡状态] 单位：人员明细记录数；不与Crashes伤亡汇总对齐"])
    writer.writerow(["person_type", "person_injury", "record_count"])
    for item in person_data["items"]:
        writer.writerow([csv_cell(item["person_type"], True), csv_cell(item["person_injury"], True),
                         item["record_count"]])
    return csv_response("vision-zero-statistics.csv", buffer)
