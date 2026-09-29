"""固定nyc-csv-v1契约；保留源值，缺失与异常不补零。"""

from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
import hashlib
import json
import re

from app.config import PROJECT_ROOT

CLEANING_VERSION = "nyc-clean-v1"
MAPPING = json.loads((PROJECT_ROOT / "configs/field_mapping_v1.json").read_text(encoding="utf-8"))
HEADERS = json.loads((PROJECT_ROOT / "configs/csv_headers_v1.json").read_text(encoding="utf-8"))["sources"]
KINDS = ("CRASHES", "PERSON", "VEHICLES")
CASUALTIES = {key: value.split(".")[-1] for key, value in MAPPING["CRASHES"]["fields"].items() if value.startswith("casualty_stat.")}
BOROUGHS = {name: index + 1 for index, name in enumerate(("BRONX", "BROOKLYN", "MANHATTAN", "QUEENS", "STATEN ISLAND"))}


class ImportProblem(Exception):
    """只携带可公开的固定错误代码，禁止携带源值/路径。"""


def digest(value):
    body = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def required_fields(kind):
    required = set(MAPPING[kind]["keys"]) | set(MAPPING[kind]["fields"]) | {"crash_date", "crash_time"}
    if kind == "CRASHES":
        required.update(MAPPING[kind]["factor_slots"])
    return required


def resolve_headers(kind, headers, mode="auto"):
    if not headers or len(headers) != len(set(headers)) or any(not item or len(item) > 160 for item in headers):
        raise ImportProblem("CSV_HEADERS_INVALID")
    candidates = ("api", "display") if mode == "auto" else (mode,)
    matches = []
    for candidate in candidates:
        mapping = {header: header for header in headers} if candidate == "api" else {header: HEADERS[kind].get(header, header) for header in headers}
        if required_fields(kind).issubset(mapping.values()) and len(set(mapping.values())) == len(mapping):
            matches.append((candidate, mapping))
    if not matches:
        raise ImportProblem("CSV_REQUIRED_COLUMNS_MISSING")
    # 若两个映射完全相同，优先API；混合表头不能补猜含义。
    candidate, mapping = matches[0]
    if candidate == "api" and any(header in HEADERS[kind] and HEADERS[kind][header] != header for header in headers):
        raise ImportProblem("CSV_HEADERS_MIXED")
    if candidate == "display" and any(header in required_fields(kind) and header not in HEADERS[kind] for header in headers):
        raise ImportProblem("CSV_HEADERS_MIXED")
    return candidate, mapping


def canonical_row(kind, payload, mode):
    if mode == "api":
        return payload
    return {HEADERS[kind].get(key, key): value for key, value in payload.items()}


def text_value(value, *, normalize=False):
    if value is None or not str(value).strip():
        return None
    value = str(value).strip()
    return " ".join(value.split()).upper() if normalize else value


def source_id(value):
    value = text_value(value)
    if value is None or not value.isascii() or not re.fullmatch(r"[0-9]{1,19}", value):
        raise ValueError("source_id")
    number = int(value)
    if not 0 < number <= 9223372036854775807:
        raise ValueError("source_id")
    return number


def local_date(value):
    value = text_value(value)
    if value is None:
        raise ValueError("date")
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}(T00:00:00(?:\.0+)?)?", value):
        return date.fromisoformat(value[:10])
    return datetime.strptime(value, "%m/%d/%Y").date()


def quantity(value, *, minimum=0, maximum=2147483647):
    value = text_value(value)
    if value is None:
        return None
    number = Decimal(value)
    if not number.is_finite() or number != number.to_integral_value() or not minimum <= number <= maximum:
        raise ValueError("quantity")
    return int(number)


def normalized(kind, row, parents, start, end):
    """返回规范化行、诊断和ACCEPTED/REJECTED/SKIPPED；父行来自本批及正式库。"""
    issues = []
    def issue(code, field, severity="WARNING"):
        issues.append({"issue_code": code, "field_name": field, "severity": severity})
    try:
        key = source_id(row.get("collision_id" if kind == "CRASHES" else "unique_id"))
    except ValueError:
        issue("SOURCE_KEY_INVALID", "collision_id" if kind == "CRASHES" else "unique_id", "ERROR")
        return None, issues, "REJECTED"
    if kind == "CRASHES":
        try:
            crash_date = local_date(row.get("crash_date"))
        except ValueError:
            issue("CRASH_DATE_INVALID", "crash_date", "ERROR")
            return None, issues, "REJECTED"
        if not start <= crash_date < end:
            issue("OUTSIDE_REQUESTED_RANGE", "crash_date", "INFO")
            return None, issues, "SKIPPED"
        crash_time = None
        if text_value(row.get("crash_time")):
            try:
                value = str(row["crash_time"]).strip()
                crash_time = datetime.strptime(value, "%H:%M").time() if len(value.split(":")) == 2 else time.fromisoformat(value)
                if crash_time.tzinfo is not None: raise ValueError("timezone")
            except ValueError:
                issue("CRASH_TIME_INVALID", "crash_time")
                crash_time = None
        borough = text_value(row.get("borough"), normalize=True)
        if borough and borough not in BOROUGHS:
            issue("BOROUGH_UNKNOWN", "borough")
        latitude, longitude = None, None
        lat, lon = text_value(row.get("latitude")), text_value(row.get("longitude"))
        if lat is not None or lon is not None:
            try:
                a, b = Decimal(lat), Decimal(lon)
                if not a.is_finite() or not b.is_finite() or not (-90 <= a <= 90 and -180 <= b <= 180) or a == 0 or b == 0:
                    raise ValueError("coordinates")
                latitude, longitude = str(a.normalize()), str(b.normalize())
                if not (Decimal("40.45") <= a <= Decimal("40.95") and Decimal("-74.3") <= b <= Decimal("-73.65")):
                    issue("OUTSIDE_NYC_RECTANGLE", "coordinates")
            except (ValueError, InvalidOperation, TypeError):
                issue("COORDINATES_INVALID", "coordinates")
        else:
            issue("COORDINATES_MISSING", "coordinates")
        location = {"borough_id": BOROUGHS.get(borough), "zip_code": text_value(row.get("zip_code")),
                    "on_street_name": text_value(row.get("on_street_name"), normalize=True),
                    "cross_street_name": text_value(row.get("off_street_name"), normalize=True),
                    "off_street_name": text_value(row.get("cross_street_name"), normalize=True),
                    "latitude": latitude, "longitude": longitude}
        key_input = {"version": CLEANING_VERSION, **location}
        if not any(value is not None for value in location.values()):
            key_input["collision_id"] = str(key)
        casualty = {}
        for source, target in CASUALTIES.items():
            try:
                casualty[target] = quantity(row.get(source))
                if casualty[target] is None: issue("CASUALTY_MISSING", source)
            except (ValueError, InvalidOperation):
                casualty[target] = None
                issue("CASUALTY_INVALID", source)
        factors = {slot: text_value(row.get(f"contributing_factor_vehicle_{slot}"), normalize=True) for slot in range(1, 6)}
        return {"id": key, "crash_date": crash_date, "crash_time": crash_time,
                "location": location, "key_input": key_input, "location_key": digest(key_input),
                "casualty": casualty, "factors": factors}, issues, "ACCEPTED"
    try:
        parent = source_id(row.get("collision_id"))
    except ValueError:
        issue("PARENT_KEY_INVALID", "collision_id", "ERROR")
        return None, issues, "REJECTED"
    if parent not in parents:
        try:
            outside = not start <= local_date(row.get("crash_date")) < end
        except ValueError:
            outside = False
        issue("PARENT_OUTSIDE_RANGE" if outside else "MISSING_PARENT", "collision_id", "INFO" if outside else "ERROR")
        return None, issues, "SKIPPED" if outside else "REJECTED"
    if not start <= parents[parent] < end:
        issue("PARENT_OUTSIDE_RANGE", "collision_id", "INFO")
        return None, issues, "SKIPPED"
    try:
        if local_date(row.get("crash_date")) != parents[parent]: issue("CHILD_DATE_MISMATCH", "crash_date")
    except ValueError:
        issue("CHILD_DATE_INVALID", "crash_date")
    fields = {target.split(".")[-1]: text_value(row.get(source)) for source, target in MAPPING[kind]["fields"].items()}
    field, lower, upper = ("person_age", 0, 120) if kind == "PERSON" else ("vehicle_year", 1886, 2100)
    try:
        fields[field] = quantity(row.get(field), minimum=lower, maximum=upper)
    except (ValueError, InvalidOperation):
        fields[field] = None
        issue("AGE_INVALID" if kind == "PERSON" else "VEHICLE_YEAR_INVALID", field)
    if kind == "VEHICLES":
        fields["canonical_name"] = text_value(row.get("vehicle_type"), normalize=True)
    return {"id": key, "collision_id": parent, **fields}, issues, "ACCEPTED"


MESSAGES = {
    "SOURCE_KEY_INVALID": "来源主键缺失或不是有效正整数，已隔离。",
    "PARENT_KEY_INVALID": "父事故编号无效，已隔离。",
    "CRASH_DATE_INVALID": "事故日期缺失或格式无效，已隔离。",
    "OUTSIDE_REQUESTED_RANGE": "事故日期在声明范围外，已跳过。",
    "CRASH_TIME_INVALID": "事故时间格式无效，规范值保留缺失。",
    "BOROUGH_UNKNOWN": "行政区不在固定字典，保留源值并标记缺失。",
    "COORDINATES_INVALID": "坐标缺半边、越界、非有限或为零，地点保留且坐标为空。",
    "COORDINATES_MISSING": "来源没有坐标，事故仍保留。",
    "OUTSIDE_NYC_RECTANGLE": "有效坐标在课程矩形预筛外；此矩形不等于纽约行政边界。",
    "CASUALTY_MISSING": "来源伤亡字段缺失，保留NULL，不补零。",
    "CASUALTY_INVALID": "伤亡值无效，规范值置NULL并保留源值。",
    "MISSING_PARENT": "父事故在本批和正式库中均不存在，明细已隔离。",
    "PARENT_OUTSIDE_RANGE": "父事故在声明范围外，明细已跳过。",
    "CHILD_DATE_MISMATCH": "明细报告日期与父事故不同，查询使用父事故日期。",
    "CHILD_DATE_INVALID": "明细日期无效，查询使用父事故日期。",
    "AGE_INVALID": "年龄超出课程质量范围或格式无效，规范值置NULL。",
    "VEHICLE_YEAR_INVALID": "车辆年份超出课程质量范围或格式无效，规范值置NULL。",
    "DUPLICATE_IDENTICAL": "本批来源键及内容重复，正式处理一次。",
    "DUPLICATE_CONFLICT": "同一来源键内容冲突，隔离该组且阻断整批发布。",
    "SOURCE_UNCHANGED": "来源内容与清洗版本均未改变，正式事实不重复写入。",
}
