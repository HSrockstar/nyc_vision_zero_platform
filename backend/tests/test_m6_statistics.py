"""M6统计与导出的真实PostgreSQL验收；所有输入均为随机隔离库中的合成数据。

手算夹具（区间[2025-01-01, 2025-02-01)）：
  c1 受伤2死亡0；2辆同车型A；2条人员；原因A占两个槽位。
  c2 受伤2死亡1；1辆A+1辆B；1条人员；原因A、B。
  c3 受伤NULL死亡NULL；1辆未知车型；1条人员；无原因记录；缺时间、缺行政区、缺坐标。
预期：事故3；已知受伤4/缺失1；已知死亡1/缺失1；车辆5；人员4；
      原因A涉及2起不同事故、B涉及1起；无原因事故1；车型A记录3条涉及2起事故。
2月的7起转义/格式样本与6月的5001行批量样本在核心区间之外，不影响手算断言。
"""

import csv
import io
import json
import os
from datetime import date, datetime, time, timedelta, timezone
from itertools import count
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from app.main import app
from conftest import alembic_config, connect_as, seed_user, validation_config
from test_m1_auth import login

COLLISION_IDS = count(910000)
PERSON_IDS = count(810000)
VEHICLE_IDS = count(870000)
ROW_NOS = count(1)

CORE_PARAMS = {"start": "2025-01-01", "end": "2025-02-01"}
ESCAPE_PARAMS = {"start": "2025-02-01", "end": "2025-03-01"}


def raw_record(connection, batch_id, kind):
    return connection.execute("""
        INSERT INTO public.raw_record (batch_id, source_kind, row_no, source_key, payload, row_hash, validation_status)
        VALUES (%s, %s, %s, %s, '{}'::jsonb, %s, 'ACCEPTED') RETURNING raw_record_id
    """, (batch_id, kind, next(ROW_NOS), "m6-" + uuid4().hex, "0" * 64)).fetchone()[0]


def seed_batch(connection, created_by, *, declared=("2025-01-01", "2026-01-01")):
    """按导入守卫状态机推进到SUCCEEDED；manifest声明范围仅用于覆盖标注测试。"""
    manifest = {"files": [{"source_kind": "CRASHES"}],
                "validation": {"coverage": {"method": "M6合成批次", "selected_range": list(declared)}}}
    batch_id = connection.execute("""
        INSERT INTO public.import_batch
            (request_id, request_hash, manifest_hash, cleaning_version, input_manifest, status, created_by)
        VALUES (%s, %s, %s, 'm6-synthetic-v1', %s::jsonb, 'UPLOADED', %s) RETURNING batch_id
    """, (uuid4(), "0" * 64, "1" * 64, json.dumps(manifest), created_by)).fetchone()[0]
    for step in ("VALIDATING", "READY"):
        connection.execute("UPDATE public.import_batch SET status=%s WHERE batch_id=%s", (step, batch_id))
    connection.execute("""UPDATE public.import_batch SET status='PUBLISHING', publish_request_id=%s,
                          publish_request_hash=%s, publish_requested_by=%s WHERE batch_id=%s""",
                       (uuid4(), "0" * 64, created_by, batch_id))
    connection.execute("""UPDATE public.import_batch SET status='SUCCEEDED', published_revision=1,
                          finished_at=now() WHERE batch_id=%s""", (batch_id,))
    return batch_id


def seed_location(connection, *, borough_id=None, on_street=None, geom=False):
    point = "ST_SetSRID(ST_MakePoint(-73.99,40.72),4326)" if geom else "NULL"
    return connection.execute(f"""
        INSERT INTO public.location (location_key, key_input, borough_id, on_street_name, geom)
        VALUES (%s, '{{}}'::jsonb, %s, %s, {point}) RETURNING location_id
    """, ("m6-" + uuid4().hex, borough_id, on_street)).fetchone()[0]


def seed_collision(connection, batch_id, *, location_id, crash_date, crash_time=None,
                   injured=None, killed=None, factors=()):
    raw = raw_record(connection, batch_id, "CRASHES")
    collision_id = connection.execute("""
        INSERT INTO public.collision (collision_id, location_id, crash_date, crash_time, source_record_id)
        VALUES (%s, %s, %s, %s, %s) RETURNING collision_id
    """, (next(COLLISION_IDS), location_id, crash_date, crash_time, raw)).fetchone()[0]
    connection.execute("INSERT INTO public.casualty_stat (collision_id, persons_injured, persons_killed) VALUES (%s,%s,%s)",
                       (collision_id, injured, killed))
    for order, factor_id in factors:
        connection.execute("INSERT INTO public.collision_factor (collision_id, factor_order, factor_id) VALUES (%s,%s,%s)",
                           (collision_id, order, factor_id))
    return collision_id


def seed_person(connection, batch_id, collision_id, person_type=None, person_injury=None):
    raw = raw_record(connection, batch_id, "PERSON")
    return connection.execute("""
        INSERT INTO public.person (person_id, collision_id, person_type, person_injury, source_record_id)
        VALUES (%s, %s, %s, %s, %s) RETURNING person_id
    """, (next(PERSON_IDS), collision_id, person_type, person_injury, raw)).fetchone()[0]


def seed_vehicle(connection, batch_id, collision_id, vehicle_type_id=None):
    raw = raw_record(connection, batch_id, "VEHICLES")
    return connection.execute("""
        INSERT INTO public.vehicle (vehicle_id, collision_id, vehicle_type_id, source_record_id)
        VALUES (%s, %s, %s, %s) RETURNING vehicle_id
    """, (next(VEHICLE_IDS), collision_id, vehicle_type_id, raw)).fetchone()[0]


def seed_factor(connection, name):
    return connection.execute("INSERT INTO public.contributing_factor (canonical_name) VALUES (%s) RETURNING factor_id",
                              (name,)).fetchone()[0]


def seed_vehicle_type(connection, name):
    return connection.execute("INSERT INTO public.vehicle_type (canonical_name) VALUES (%s) RETURNING vehicle_type_id",
                              (name,)).fetchone()[0]


def seed_task_basis(connection, created_by):
    """与M5一致的合成画像依据：确认路口+成功批次+画像。"""
    suffix = uuid4().hex[:12]
    intersection_id = connection.execute("""
        INSERT INTO public.intersection
            (intersection_code, street_a, street_b, center_geom, status, source_method,
             confirmation_note, confirmed_by, confirmed_at)
        VALUES (%s, 'M6 SYNTH A ' || %s, 'M6 SYNTH B ' || %s, ST_SetSRID(ST_MakePoint(-73.99,40.72),4326),
                'CONFIRMED', 'MANUAL', 'M6随机验证交叉口', %s, now()) RETURNING intersection_id
    """, ("M6-" + suffix, suffix, suffix, created_by)).fetchone()[0]
    run_id = connection.execute("""
        INSERT INTO public.risk_run (request_id, request_hash, rule_id, period_start, period_end, status, requested_by)
        VALUES (%s, %s, 1, '2025-01-01', '2026-01-01', 'QUEUED', %s) RETURNING run_id
    """, (uuid4(), "0" * 64, created_by)).fetchone()[0]
    profile_id = connection.execute("""
        INSERT INTO public.risk_profile (run_id, intersection_id, collision_count, injured_count, killed_count,
                                         vulnerable_road_user_count, incomplete_casualty_collision_count)
        VALUES (%s, %s, 30, 2, 1, 1, 0) RETURNING profile_id
    """, (run_id, intersection_id)).fetchone()[0]
    connection.execute("UPDATE public.risk_run SET status='SUCCEEDED', input_revision=0, started_at=now(), finished_at=now() WHERE run_id=%s",
                       (run_id,))
    return profile_id


def seed_task(connection, created_by, profile_id, *, status, assignee_id=None, deleted=False):
    suffix = uuid4().hex[:12]
    task_id = connection.execute("""
        INSERT INTO public.governance_task
            (task_code, request_id, request_hash, profile_id, title, description, measure_type, priority,
             status, created_by, assignee_id, deleted_at)
        VALUES (%s, %s, %s, %s, 'M6模拟统计工单', 'M6合成工单描述', 'FIELD_SURVEY', 'MEDIUM', %s, %s, %s, %s)
        RETURNING task_id
    """, ("GOV-M6-" + suffix, uuid4(), "0" * 64, profile_id, status, created_by, assignee_id,
          datetime.now(timezone.utc) if deleted else None)).fetchone()[0]
    for sequence in range(1, {"COMPLETED": 3, "OPEN": 1, "DRAFT": 1}.get(status, 1) + 1):
        connection.execute("""
            INSERT INTO public.task_history (task_id, sequence_no, request_id, request_hash, event_type,
                                             from_status, to_status, actor_id, note)
            VALUES (%s, %s, %s, %s, 'PROGRESS', %s, %s, %s, 'M6合成历史')
        """, (task_id, sequence, uuid4(), "0" * 64, status, status, created_by))
    return task_id


@pytest.fixture(scope="module")
def m6_env():
    if os.getenv("VISION_ZERO_RUN_DB_TESTS") != "1":
        pytest.skip("需显式启用真实PostgreSQL验证")
    values = validation_config()
    with patch.dict(os.environ, values):
        from alembic import command
        command.upgrade(alembic_config(), "head")
    yield values


def seed_core_fixture(connection):
    """c1/c2/c3手算夹具 + 街道转义与公式注入样本 + 2024年末F01/F07样本。"""
    users = {name: seed_user(connection, role=role)
             for name, role in (("admin", 1), ("manager", 2), ("viewer", 3))}
    batch = seed_batch(connection, users["admin"][0])
    factor_a = seed_factor(connection, "M6 SYNTHETIC FACTOR A")
    factor_b = seed_factor(connection, "M6 SYNTHETIC FACTOR B")
    type_a = seed_vehicle_type(connection, "M6 SYNTHTYPE A")
    type_b = seed_vehicle_type(connection, "M6 SYNTHTYPE B")
    city_location = seed_location(connection, borough_id=1, on_street="M6 MAIN ST", geom=True)
    unknown_location = seed_location(connection, borough_id=None, on_street="M6 UNKNOWN ST")
    percent_location = seed_location(connection, borough_id=2, on_street="M6 ESC 100% ST")
    under_location = seed_location(connection, borough_id=2, on_street="M6 ESC _UNDER ST")
    control_location = seed_location(connection, borough_id=2, on_street="M6 ESC 100X ST")
    slash_location = seed_location(connection, borough_id=2, on_street="M6 ESC \\SLASH ST")
    formula_location = seed_location(connection, borough_id=2, on_street='=HYPERLINK("http://m6.invalid")')
    plus_location = seed_location(connection, borough_id=2, on_street=" +SUM(A1)")
    quote_location = seed_location(connection, borough_id=2, on_street='中文名称,含"引号"与\n换行')
    # F01/F07样本：三个街道字段全NULL的事故（borough 3=MANHATTAN）及borough 4/5对照。
    streetless_location = seed_location(connection, borough_id=3)
    queens_location = seed_location(connection, borough_id=4, on_street="M6 QUEENS ST")
    staten_location = seed_location(connection, borough_id=5, on_street="M6 STATEN ST")

    c1 = seed_collision(connection, batch, location_id=city_location, crash_date=date(2025, 1, 5),
                        crash_time=time(8, 30), injured=2, killed=0, factors=[(1, factor_a), (2, factor_a)])
    seed_person(connection, batch, c1, "driver", "Injured")
    seed_person(connection, batch, c1, "passenger", "Uninjured")
    seed_vehicle(connection, batch, c1, type_a)
    seed_vehicle(connection, batch, c1, type_a)
    c2 = seed_collision(connection, batch, location_id=city_location, crash_date=date(2025, 1, 6),
                        crash_time=time(0, 15), injured=2, killed=1, factors=[(1, factor_a), (2, factor_b)])
    seed_person(connection, batch, c2, "driver", "Killed")
    seed_vehicle(connection, batch, c2, type_a)
    seed_vehicle(connection, batch, c2, type_b)
    c3 = seed_collision(connection, batch, location_id=unknown_location, crash_date=date(2025, 1, 7))
    seed_person(connection, batch, c3)
    seed_vehicle(connection, batch, c3)
    escape = seed_collision(connection, batch, location_id=percent_location, crash_date=date(2025, 2, 1), injured=0, killed=0)
    under = seed_collision(connection, batch, location_id=under_location, crash_date=date(2025, 2, 2))
    control = seed_collision(connection, batch, location_id=control_location, crash_date=date(2025, 2, 3))
    slash = seed_collision(connection, batch, location_id=slash_location, crash_date=date(2025, 2, 4))
    formula = seed_collision(connection, batch, location_id=formula_location, crash_date=date(2025, 2, 5), injured=1, killed=0)
    plus = seed_collision(connection, batch, location_id=plus_location, crash_date=date(2025, 2, 6))
    quoted = seed_collision(connection, batch, location_id=quote_location, crash_date=date(2025, 2, 7))
    streetless = seed_collision(connection, batch, location_id=streetless_location, crash_date=date(2024, 12, 31), injured=0, killed=0)
    queens = seed_collision(connection, batch, location_id=queens_location, crash_date=date(2024, 12, 30), injured=0, killed=0)
    staten = seed_collision(connection, batch, location_id=staten_location, crash_date=date(2024, 12, 29), injured=0, killed=0)
    return {"users": users, "factor_a": factor_a, "factor_b": factor_b, "type_a": type_a,
            "type_b": type_b, "collisions": {"c1": c1, "c2": c2, "c3": c3, "escape": escape,
            "under": under, "control": control, "slash": slash, "formula": formula,
            "plus": plus, "quoted": quoted, "streetless": streetless, "queens": queens, "staten": staten}}


@pytest.fixture(scope="module")
def m6_client(m6_env):
    with patch.dict(os.environ, m6_env):
        with connect_as() as connection:
            data = seed_core_fixture(connection)
        with TestClient(app) as client:
            auth = {name: login(client, account[1]) for name, account in data["users"].items()}
            yield client, auth, data


def parse_csv(response):
    text = response.content.decode("utf-8-sig")
    rows = list(csv.reader(io.StringIO(text, newline="")))
    data_rows = [row for row in rows if row and not row[0].startswith("#")]
    return text, rows, data_rows


def test_manual_fixture_overview_and_groups(m6_client):
    """手算夹具：总览、行政区、原因、车型、人员逐项对照。"""
    client, auth, data = m6_client
    headers = auth["manager"]
    overview = client.get("/api/v1/statistics/overview", headers=headers, params=CORE_PARAMS)
    assert overview.status_code == 200, overview.text
    body = overview.json()["data"]
    assert body["collision_count"] == 3
    assert body["known_injured_count"] == 4 and body["injured_missing_count"] == 1
    assert body["known_killed_count"] == 1 and body["killed_missing_count"] == 1
    assert body["person_records"] == 4 and body["vehicle_records"] == 5
    assert body["geocoded_count"] == 2 and body["missing_coordinates_count"] == 1
    assert body["confirmed_assigned_count"] == 0 and body["assignment_coverage_ratio"] == "0.000000"

    boroughs = client.get("/api/v1/statistics/boroughs", headers=headers, params=CORE_PARAMS).json()["data"]["items"]
    assert boroughs[0]["borough_id"] == "1" and boroughs[0]["collision_count"] == 2
    assert boroughs[0]["known_injured_count"] == 4 and boroughs[0]["known_killed_count"] == 1
    assert boroughs[0]["injured_missing_count"] == 0
    assert boroughs[1]["borough_id"] is None and boroughs[1]["borough_name"] == "未知行政区"
    assert boroughs[1]["collision_count"] == 1 and boroughs[1]["known_injured_count"] is None
    assert boroughs[1]["injured_missing_count"] == 1

    factors = client.get("/api/v1/statistics/factors", headers=headers, params=CORE_PARAMS).json()["data"]
    counts = {item["canonical_name"]: item["collision_count"] for item in factors["items"]}
    assert counts == {"M6 SYNTHETIC FACTOR A": 2, "M6 SYNTHETIC FACTOR B": 1}
    assert factors["no_factor_collision_count"] == 1

    vehicles = client.get("/api/v1/statistics/vehicle-types", headers=headers, params=CORE_PARAMS).json()["data"]["items"]
    by_name = {item["canonical_name"]: item for item in vehicles}
    assert by_name["M6 SYNTHTYPE A"]["vehicle_records"] == 3 and by_name["M6 SYNTHTYPE A"]["collision_count"] == 2
    assert by_name["M6 SYNTHTYPE B"]["vehicle_records"] == 1 and by_name["M6 SYNTHTYPE B"]["collision_count"] == 1
    unknown = by_name[None]
    assert unknown["vehicle_type_id"] is None and unknown["vehicle_records"] == 1 and unknown["collision_count"] == 1

    persons = client.get("/api/v1/statistics/persons", headers=headers, params=CORE_PARAMS).json()["data"]["items"]
    assert {(item["person_type"], item["person_injury"], item["record_count"]) for item in persons} == {
        ("driver", "Injured", 1), ("passenger", "Uninjured", 1), ("driver", "Killed", 1), (None, None, 1)}


def test_filters_do_not_amplify_and_unknown_scope(m6_client):
    """原因/车型筛选不放大伤亡；未知组合计保持NULL。"""
    client, auth, data = m6_client
    headers = auth["admin"]
    by_factor = client.get("/api/v1/statistics/overview", headers=headers,
                           params={**CORE_PARAMS, "factor_id": str(data["factor_a"])}).json()["data"]
    assert by_factor["collision_count"] == 2
    assert by_factor["known_injured_count"] == 4 and by_factor["known_killed_count"] == 1
    by_vehicle = client.get("/api/v1/statistics/overview", headers=headers,
                            params={**CORE_PARAMS, "vehicle_type_id": str(data["type_a"])}).json()["data"]
    assert by_vehicle["collision_count"] == 2
    # 口径验证：车型筛选只选出事故；明细统计这些事故内的全部车辆（3辆A+1辆B=4条）。
    assert by_vehicle["vehicle_records"] == 4
    assert by_vehicle["known_injured_count"] == 4
    combined = client.get("/api/v1/statistics/overview", headers=headers,
                          params={**CORE_PARAMS, "factor_id": str(data["factor_a"]),
                                  "vehicle_type_id": str(data["type_b"])}).json()["data"]
    assert combined["collision_count"] == 1 and combined["known_injured_count"] == 2
    assert combined["known_killed_count"] == 1
    c3_only = client.get("/api/v1/statistics/overview", headers=headers,
                         params={**CORE_PARAMS, "street": "M6 UNKNOWN"}).json()["data"]
    assert c3_only["collision_count"] == 1
    assert c3_only["known_injured_count"] is None and c3_only["known_killed_count"] is None
    assert c3_only["injured_missing_count"] == 1 and c3_only["person_records"] == 1
    zero_case = client.get("/api/v1/statistics/overview", headers=headers,
                           params={**ESCAPE_PARAMS, "street": "M6 ESC 100%"}).json()["data"]
    assert zero_case["collision_count"] == 1 and zero_case["known_injured_count"] == 0
    assert zero_case["injured_missing_count"] == 0


def test_trends_months_hours_and_coverage(m6_client):
    """月度覆盖标注与小时分布：NULL时间不并入0点。"""
    client, auth, data = m6_client
    headers = auth["manager"]
    months = client.get("/api/v1/statistics/trends", headers=headers,
                        params={"start": "2025-01-01", "end": "2025-03-01"}).json()["data"]
    by_month = {item["month"]: item for item in months["months"]}
    assert by_month["2025-01"]["collision_count"] == 3
    assert by_month["2025-01"]["known_injured_count"] == 4 and by_month["2025-01"]["coverage"] == "WITH_DATA"
    # 月度响应补齐伤亡缺失事故数（c3伤亡全NULL → 1月缺失1）。
    assert by_month["2025-01"]["injured_missing_count"] == 1 and by_month["2025-01"]["killed_missing_count"] == 1
    # 2月含7起转义/格式样本（见seed_core_fixture），不在核心手算区间[2025-01-01, 2025-02-01)内。
    assert by_month["2025-02"]["collision_count"] == 7 and by_month["2025-02"]["coverage"] == "WITH_DATA"
    # 2月中escape与formula伤亡值完整（0/0与1/0），其余5起伤亡为NULL。
    assert by_month["2025-02"]["injured_missing_count"] == 5 and by_month["2025-02"]["killed_missing_count"] == 5
    assert months["zero_fill"] is False

    empty_inside = client.get("/api/v1/statistics/trends", headers=headers,
                              params={"start": "2025-06-01", "end": "2025-08-01"}).json()["data"]
    assert all(item["collision_count"] is None for item in empty_inside["months"])
    assert {item["coverage"] for item in empty_inside["months"]} == {"NO_RECORDS_COVERAGE_UNCONFIRMED"}
    outside = client.get("/api/v1/statistics/trends", headers=headers,
                         params={"start": "2026-05-01", "end": "2026-07-01"}).json()["data"]
    assert {item["coverage"] for item in outside["months"]} == {"OUTSIDE_DECLARED_RANGES"}

    hours = client.get("/api/v1/statistics/trends", headers=headers,
                       params={**CORE_PARAMS, "granularity": "hours"}).json()["data"]
    counts = {item["hour"]: item["collision_count"] for item in hours["hours"]}
    assert counts[0] == 1 and counts[8] == 1 and sum(counts.values()) == 2
    assert hours["unknown_time_collision_count"] == 1


def test_street_wildcard_escaping(m6_client):
    """street中% _ \\按字面匹配；转义后不会把字面通配符当模式。"""
    client, auth, data = m6_client
    headers = auth["manager"]
    cases = {"M6 ESC 100%": 1, "M6 ESC _UNDER": 1, "M6 ESC 100X": 1, "M6 ESC \\SLASH": 1,
             "M6 ESC": 4, "UNDER%": 0}
    for street, expected in cases.items():
        result = client.get("/api/v1/statistics/overview", headers=headers, params={**ESCAPE_PARAMS, "street": street})
        assert result.status_code == 200, result.text
        assert result.json()["data"]["collision_count"] == expected, street


def test_invalid_ranges_and_empty_scope(m6_client):
    client, auth, data = m6_client
    headers = auth["manager"]
    for path in ("/api/v1/statistics/overview", "/api/v1/statistics/trends", "/api/v1/statistics/factors",
                 "/api/v1/statistics/vehicle-types", "/api/v1/statistics/persons",
                 "/api/v1/exports/collisions.csv", "/api/v1/exports/statistics.csv"):
        result = client.get(path, headers=headers, params={"start": "2025-02-01", "end": "2025-02-01"})
        assert result.status_code == 422, (path, result.text)
        assert result.json()["error"]["code"] == "INVALID_RANGE"
    too_many_months = client.get("/api/v1/statistics/trends", headers=headers,
                                 params={"start": "2000-01-01", "end": "2030-01-01"})
    assert too_many_months.status_code == 422, too_many_months.text

    empty = client.get("/api/v1/statistics/overview", headers=headers,
                       params={"start": "2030-01-01", "end": "2030-02-01"}).json()["data"]
    assert empty["collision_count"] == 0 and empty["known_injured_count"] is None
    assert empty["injured_missing_count"] == 0 and empty["person_records"] == 0
    assert empty["vehicle_records"] == 0 and empty["assignment_coverage_ratio"] is None
    empty_months = client.get("/api/v1/statistics/trends", headers=headers,
                              params={"start": "2030-01-01", "end": "2030-02-01"}).json()["data"]
    assert empty_months["months"][0]["collision_count"] is None
    assert empty_months["months"][0]["coverage"] == "OUTSIDE_DECLARED_RANGES"
    empty_hours = client.get("/api/v1/statistics/trends", headers=headers,
                             params={"start": "2030-01-01", "end": "2030-02-01", "granularity": "hours"}).json()["data"]
    assert all(item["collision_count"] == 0 for item in empty_hours["hours"])
    assert empty_hours["unknown_time_collision_count"] == 0


def test_revision_snapshot_and_read_only(m6_client):
    """同一响应revision与聚合一致；统计GET不修改事实、revision或工单。"""
    client, auth, data = m6_client
    headers = auth["manager"]
    first = client.get("/api/v1/statistics/overview", headers=headers, params=CORE_PARAMS)
    second = client.get("/api/v1/statistics/overview", headers=headers, params=CORE_PARAMS)
    assert first.status_code == second.status_code == 200
    assert first.json()["data"] == second.json()["data"]
    assert (first.json()["meta"]["data_revision"] == second.json()["meta"]["data_revision"] == "0")
    revision = first.json()["meta"]["data_revision"]
    assert revision.isdigit()
    governance = client.get("/api/v1/statistics/governance", headers=headers).json()["data"]
    with connect_as() as connection:
        state = connection.execute("SELECT revision FROM public.dataset_state WHERE state_id=1").fetchone()[0]
        counts = connection.execute("""SELECT (SELECT count(*) FROM public.collision WHERE collision_id < 920000),
               (SELECT count(*) FROM public.person), (SELECT count(*) FROM public.vehicle),
               (SELECT count(*) FROM public.governance_task), (SELECT count(*) FROM public.task_history)""").fetchone()
    assert revision == str(state)
    assert counts == (13, 4, 5, 0, 0)
    assert governance["total_tasks"] == 0


def test_permissions(m6_client):
    """未登录401；VIEWER基础统计可读、人员细分/治理/统计报表403且无部分数据。"""
    client, auth, data = m6_client
    open_paths = [("/api/v1/statistics/overview", CORE_PARAMS), ("/api/v1/statistics/boroughs", CORE_PARAMS),
                  ("/api/v1/statistics/trends", CORE_PARAMS), ("/api/v1/statistics/factors", CORE_PARAMS),
                  ("/api/v1/statistics/vehicle-types", CORE_PARAMS),
                  ("/api/v1/exports/collisions.csv", CORE_PARAMS)]
    restricted = [("/api/v1/statistics/persons", CORE_PARAMS), ("/api/v1/statistics/governance", {}),
                  ("/api/v1/exports/statistics.csv", CORE_PARAMS)]
    for path, params in open_paths:
        assert client.get(path, params=params).status_code == 401, path
        viewer = client.get(path, headers=auth["viewer"], params=params)
        assert viewer.status_code == 200, (path, viewer.text)
    for path, params in restricted:
        assert client.get(path, params=params).status_code == 401, path
        viewer = client.get(path, headers=auth["viewer"], params=params)
        assert viewer.status_code == 403, (path, viewer.text)
        assert b"collision_id" not in viewer.content
        assert client.get(path, headers=auth["manager"], params=params).status_code == 200, path
        assert client.get(path, headers=auth["admin"], params=params).status_code == 200, path


def test_collision_csv_content_and_escaping(m6_client):
    """CSV转义、公式防护、NULL为空、数值与日期不被文本化、稳定排序。"""
    client, auth, data = m6_client
    result = client.get("/api/v1/exports/collisions.csv", headers=auth["manager"], params=CORE_PARAMS)
    assert result.status_code == 200, result.text
    assert result.headers["content-type"].startswith("text/csv")
    assert "attachment" in result.headers["content-disposition"]
    assert result.content.startswith(b"\xef\xbb\xbf")
    text, rows, data_rows = parse_csv(result)
    header = data_rows[0]
    assert header[0] == "collision_id" and "persons_injured" in header and "persons_killed" in header
    body = data_rows[1:]
    assert len(body) == 3
    dates = [row[1] for row in body]
    assert dates == sorted(dates) and dates[0] == "2025-01-05"
    injured_index, killed_index = header.index("persons_injured"), header.index("persons_killed")
    c3_row = [row for row in body if row[1] == "2025-01-07"][0]
    assert c3_row[injured_index] == "" and c3_row[killed_index] == ""
    c1_row = [row for row in body if row[1] == "2025-01-05"][0]
    assert c1_row[injured_index] == "2" and c1_row[killed_index] == "0"
    assert ",2025-01-05," in text and f"\r\n{c1_row[0]},2025-01-05," in text

    escape_result = client.get("/api/v1/exports/collisions.csv", headers=auth["manager"], params=ESCAPE_PARAMS)
    text, rows, data_rows = parse_csv(escape_result)
    header, body = data_rows[0], data_rows[1:]
    street_index = header.index("on_street_name")
    streets = {row[street_index] for row in body}
    assert "M6 ESC 100% ST" in streets
    assert "'=HYPERLINK(\"http://m6.invalid\")" in streets
    assert "' +SUM(A1)" in streets
    assert '中文名称,含"引号"与\n换行' in streets
    assert len(body) == 7


def test_csv_row_limit_and_consistency(m6_env):
    """恰好5000行可导出、5001行明确拒绝；列表/统计/导出同一筛选集合。"""
    with patch.dict(os.environ, dict(m6_env)):
        with connect_as() as connection:
            users = {name: seed_user(connection, role=role) for name, role in (("admin", 1), ("viewer", 3))}
            batch = seed_batch(connection, users["admin"][0])
            location = seed_location(connection, borough_id=1, on_street="M6 BULK ST")
            connection.execute("""
                INSERT INTO public.raw_record (batch_id, source_kind, row_no, source_key, payload, row_hash, validation_status)
                SELECT %s, 'CRASHES', g, 'bulk-' || g, '{}'::jsonb, %s, 'ACCEPTED' FROM generate_series(1, 5001) g
            """, (batch, "0" * 64))
            connection.execute("""
                INSERT INTO public.collision (collision_id, location_id, crash_date, crash_time, source_record_id)
                SELECT 920000 + g, %s, CASE WHEN g <= 5000 THEN DATE '2025-06-01' ELSE DATE '2025-06-02' END,
                       NULL, r.raw_record_id
                FROM generate_series(1, 5001) g JOIN public.raw_record r
                  ON r.batch_id = %s AND r.source_kind = 'CRASHES' AND r.row_no = g
            """, (location, batch))
            connection.execute("""
                INSERT INTO public.casualty_stat (collision_id, persons_injured, persons_killed)
                SELECT 920000 + g, NULL, NULL FROM generate_series(1, 5001) g
            """)
        with TestClient(app) as client:
            admin = login(client, users["admin"][1])
            viewer = login(client, users["viewer"][1])
            exact = client.get("/api/v1/exports/collisions.csv", headers=admin,
                               params={"start": "2025-06-01", "end": "2025-06-02"})
            assert exact.status_code == 200, exact.text
            _, _, data_rows = parse_csv(exact)
            header, body = data_rows[0], data_rows[1:]
            assert len(body) == 5000
            listing = client.get("/api/v1/collisions", headers=admin,
                                 params={"start": "2025-06-01", "end": "2025-06-02", "include_total": "true"}).json()
            assert listing["data"]["total"] == 5000
            scoped = client.get("/api/v1/statistics/overview", headers=admin,
                                params={"start": "2025-06-01", "end": "2025-06-02"}).json()["data"]
            assert scoped["collision_count"] == 5000
            assert scoped["known_injured_count"] is None and scoped["injured_missing_count"] == 5000
            ids = [row[0] for row in body]
            assert ids == sorted(ids)
            over_limit = client.get("/api/v1/exports/collisions.csv", headers=admin,
                                    params={"start": "2025-06-01", "end": "2025-06-03"})
            assert over_limit.status_code == 400, over_limit.text
            assert over_limit.json()["error"]["code"] == "EXPORT_ROW_LIMIT"
            assert "5000" in over_limit.json()["error"]["message"]
            assert client.get("/api/v1/exports/collisions.csv", headers=viewer,
                              params={"start": "2025-06-01", "end": "2025-06-02"}).status_code == 200
            empty_export = client.get("/api/v1/exports/collisions.csv", headers=admin,
                                      params={"start": "2030-06-01", "end": "2030-06-02"})
            assert empty_export.status_code == 200
            _, _, empty_rows = parse_csv(empty_export)
            assert len(empty_rows) == 1


def test_statistics_csv_report(m6_client):
    """统一统计报表：同一快照、含人员节、分节结构。"""
    client, auth, data = m6_client
    result = client.get("/api/v1/exports/statistics.csv", headers=auth["manager"], params=CORE_PARAMS)
    assert result.status_code == 200, result.text
    assert result.content.startswith(b"\xef\xbb\xbf")
    text, rows, data_rows = parse_csv(result)
    assert ["# Vision Zero 课程项目 · 统计报表导出"] in rows
    assert any(row[0] == "# 数据版本 revision: 0" for row in rows)
    assert any(row[0].startswith("# 统计区间: [2025-01-01, 2025-02-01)") for row in rows)
    assert ["不同事故数", "3"] in rows
    assert ["已知受伤合计", "4"] in rows and ["已知死亡合计", "1"] in rows
    assert ["人员明细记录数", "4"] in rows and ["车辆明细记录数", "5"] in rows
    assert any(len(row) == 7 and row[1] == "未知行政区" and row[2] == "1" for row in rows)
    assert any(len(row) == 4 and row[1] == "M6 SYNTHETIC FACTOR A" and row[3] == "2" for row in rows)
    assert any(len(row) == 4 and row[1] == "(无原因记录的事故)" and row[3] == "1" for row in rows)
    hours_index = rows.index(["# [小时分布] 单位：事故数；缺失时间单列，不并入0点"])
    assert ["unknown", "1"] in rows[hours_index:]
    person_header = rows.index(["# [人员类别与伤亡状态] 单位：人员明细记录数；不与Crashes伤亡汇总对齐"])
    assert ["driver", "Injured", "1"] in rows[person_header:]
    assert ["", "", "1"] in rows[person_header:]
    assert any(len(row) == 5 and row[1] == "M6 SYNTHTYPE A" and row[3] == "3" and row[4] == "2" for row in rows)


def test_governance_statistics(m6_env):
    """工单统计：排除软删除、未分配单列、不随历史条数重复累计、状态/执行人/日期筛选。"""
    with patch.dict(os.environ, dict(m6_env)):
        with connect_as() as connection:
            users = {name: seed_user(connection, role=role)
                     for name, role in (("admin", 1), ("manager", 2), ("assignee", 2), ("viewer", 3))}
            profile = seed_task_basis(connection, users["admin"][0])
            seed_task(connection, users["admin"][0], profile, status="COMPLETED",
                      assignee_id=users["assignee"][0])
            seed_task(connection, users["admin"][0], profile, status="OPEN",
                      assignee_id=users["manager"][0])
            seed_task(connection, users["admin"][0], profile, status="DRAFT")
            seed_task(connection, users["admin"][0], profile, status="DRAFT", deleted=True)
        with TestClient(app) as client:
            admin = login(client, users["admin"][1])
            manager = login(client, users["manager"][1])
            viewer = login(client, users["viewer"][1])
            result = client.get("/api/v1/statistics/governance", headers=admin)
            assert result.status_code == 200, result.text
            body = result.json()["data"]
            assert body["total_tasks"] == 3
            statuses = {item["status"]: item["task_count"] for item in body["by_status"]}
            assert statuses == {"COMPLETED": 1, "OPEN": 1, "DRAFT": 1}
            assert body["handling"] == {"completed": 1, "cancelled": 0, "in_execution": 1, "draft": 1}
            assignees = {item["assignee_id"]: item for item in body["by_assignee"]}
            assert assignees[None]["assignee_name"] == "未分配" and assignees[None]["task_count"] == 1
            assert assignees[str(users["assignee"][0])]["task_count"] == 1
            with connect_as() as connection:
                history_total = connection.execute("SELECT count(*) FROM public.task_history").fetchone()[0]
            assert history_total == 6
            assert body["total_tasks"] != history_total
            filtered = client.get("/api/v1/statistics/governance", headers=manager,
                                  params={"status": "OPEN"}).json()["data"]
            assert filtered["total_tasks"] == 1
            assignee_only = client.get("/api/v1/statistics/governance", headers=manager,
                                       params={"assignee_id": str(users["assignee"][0])}).json()["data"]
            assert assignee_only["total_tasks"] == 1
            assert client.get("/api/v1/statistics/governance", headers=viewer).status_code == 403
            bad_range = client.get("/api/v1/statistics/governance", headers=admin,
                                   params={"created_from": "2026-01-02", "created_to": "2026-01-01"})
            assert bad_range.status_code == 422
            today = date.today()
            dated = client.get("/api/v1/statistics/governance", headers=admin,
                               params={"created_from": today.isoformat(),
                                       "created_to": (today + timedelta(days=1)).isoformat()})
            assert dated.status_code == 200 and dated.json()["data"]["total_tasks"] == 3
            before_today = client.get("/api/v1/statistics/governance", headers=admin,
                                      params={"created_to": today.isoformat()})
            assert before_today.status_code == 200 and before_today.json()["data"]["total_tasks"] == 0


def test_month_span_sequence_and_boundaries():
    """F04/F05/F06纯函数边界：月份跨度不逐月构造，序列与月末界在9999-12安全。"""
    from app import statistics as stats
    assert stats.month_span(date(2025, 6, 1), date(2025, 6, 2)) == 1
    assert stats.month_span(date(2025, 1, 31), date(2025, 2, 1)) == 1
    assert stats.month_span(date(2025, 12, 31), date(2026, 1, 1)) == 1
    assert stats.month_span(date(2024, 2, 1), date(2024, 3, 1)) == 1
    assert stats.month_span(date(2024, 1, 1), date(2024, 3, 1)) == 2
    assert stats.month_span(date(2020, 1, 1), date(2030, 1, 1)) == 120
    assert stats.month_span(date(2020, 1, 1), date(2030, 2, 1)) == 121
    assert stats.month_span(date(9999, 12, 1), date(9999, 12, 31)) == 1
    assert stats.month_sequence(date(9999, 12, 1), date(9999, 12, 31)) == [date(9999, 12, 1)]
    assert stats.month_sequence(date(2024, 1, 1), date(2024, 3, 1)) == [date(2024, 1, 1), date(2024, 2, 1)]
    assert len(stats.month_sequence(date(2020, 1, 1), date(2030, 1, 1))) == 120
    assert stats.month_end_bound(date(9999, 12, 1)) == date(9999, 12, 31)
    assert stats.month_end_bound(date(2025, 12, 1)) == date(2026, 1, 1)


def test_date_boundaries_and_future_limit(m6_client):
    """F04年末/月末/闰年/单日左闭右开；F05临近日期上界不再500。"""
    client, auth, data = m6_client
    headers = auth["manager"]
    nye = client.get("/api/v1/statistics/overview", headers=headers,
                     params={"start": "2024-12-31", "end": "2025-01-01"}).json()["data"]
    assert nye["collision_count"] == 1
    month_end = client.get("/api/v1/statistics/overview", headers=headers,
                           params={"start": "2025-02-01", "end": "2025-02-02"}).json()["data"]
    assert month_end["collision_count"] == 1
    single = client.get("/api/v1/statistics/overview", headers=headers,
                        params={"start": "2025-01-05", "end": "2025-01-06"}).json()["data"]
    assert single["collision_count"] == 1
    leap = client.get("/api/v1/statistics/trends", headers=headers,
                      params={"start": "2024-02-01", "end": "2024-03-01"}).json()["data"]
    assert [item["month"] for item in leap["months"]] == ["2024-02"]
    far = client.get("/api/v1/statistics/trends", headers=headers,
                     params={"start": "9999-12-01", "end": "9999-12-31"})
    assert far.status_code == 200, far.text
    assert [item["month"] for item in far.json()["data"]["months"]] == ["9999-12"]
    far_hours = client.get("/api/v1/statistics/trends", headers=headers,
                           params={"start": "9999-12-01", "end": "9999-12-31", "granularity": "hours"})
    assert far_hours.status_code == 200, far_hours.text
    far_csv = client.get("/api/v1/exports/statistics.csv", headers=headers,
                         params={"start": "9999-12-01", "end": "9999-12-31"})
    assert far_csv.status_code == 200, far_csv.text
    _, rows, _ = parse_csv(far_csv)
    assert any(row and row[0] == "9999-12" for row in rows)


def test_month_limit_consistency(m6_client):
    """F06：趋势与统计CSV的月度节共用120个月上限。"""
    client, auth, data = m6_client
    headers = auth["manager"]
    exact = client.get("/api/v1/statistics/trends", headers=headers,
                       params={"start": "2020-01-01", "end": "2030-01-01"})
    assert exact.status_code == 200, exact.text
    assert len(exact.json()["data"]["months"]) == 120
    over = client.get("/api/v1/statistics/trends", headers=headers,
                      params={"start": "2020-01-01", "end": "2030-02-01"})
    assert over.status_code == 422 and over.json()["error"]["code"] == "INVALID_RANGE"
    thirty = client.get("/api/v1/statistics/trends", headers=headers,
                        params={"start": "2000-01-01", "end": "2030-01-01"})
    assert thirty.status_code == 422
    csv_exact = client.get("/api/v1/exports/statistics.csv", headers=headers,
                           params={"start": "2020-01-01", "end": "2030-01-01"})
    assert csv_exact.status_code == 200, csv_exact.text
    csv_over = client.get("/api/v1/exports/statistics.csv", headers=headers,
                          params={"start": "2020-01-01", "end": "2030-02-01"})
    assert csv_over.status_code == 422 and csv_over.json()["error"]["code"] == "INVALID_RANGE"
    csv_thirty = client.get("/api/v1/exports/statistics.csv", headers=headers,
                            params={"start": "2000-01-01", "end": "2030-01-01"})
    assert csv_thirty.status_code == 422


def test_blank_street_filter(m6_client):
    """F07：无条件、空字符串、纯空格同集合；街道全NULL事故不丢失。"""
    client, auth, data = m6_client
    headers = auth["manager"]
    base = {"start": "2024-12-01", "end": "2025-01-01"}
    none_result = client.get("/api/v1/statistics/overview", headers=headers, params=base).json()
    empty_result = client.get("/api/v1/statistics/overview", headers=headers,
                              params={**base, "street": ""}).json()
    blank_result = client.get("/api/v1/statistics/overview", headers=headers,
                              params={**base, "street": "   "}).json()
    assert none_result["data"]["collision_count"] == 3
    assert empty_result["data"] == none_result["data"]
    assert blank_result["data"] == none_result["data"]
    assert blank_result["data"]["filters"]["street_filter"] is False
    listing = client.get("/api/v1/collisions", headers=headers,
                         params={**base, "street": "   ", "include_total": "true"}).json()
    assert listing["data"]["total"] == 3
    csv_result = client.get("/api/v1/exports/collisions.csv", headers=headers,
                            params={**base, "street": "   "})
    _, _, data_rows = parse_csv(csv_result)
    assert len(data_rows) - 1 == 3
    literal = client.get("/api/v1/statistics/overview", headers=headers,
                         params={**base, "street": "M6 STATEN"}).json()["data"]
    assert literal["collision_count"] == 1


def test_borough_ids_match_database(m6_client):
    """F01后端口径：borough_id与数据库映射一致（1=BRONX、2=BROOKLYN、3=MANHATTAN、4=QUEENS、5=STATEN ISLAND）。"""
    client, auth, data = m6_client
    headers = auth["manager"]
    expected = {1: "BRONX", 2: "BROOKLYN", 3: "MANHATTAN", 4: "QUEENS", 5: "STATEN ISLAND"}
    counts = {1: 0, 2: 0, 3: 1, 4: 1, 5: 1}
    for borough_id, name in expected.items():
        params = {"start": "2024-12-01", "end": "2025-01-01", "borough_id": str(borough_id)}
        result = client.get("/api/v1/statistics/overview", headers=headers, params=params)
        assert result.status_code == 200, result.text
        body = result.json()["data"]
        assert body["filters"]["borough_id"] == str(borough_id)
        assert body["collision_count"] == counts[borough_id]
        groups = client.get("/api/v1/statistics/boroughs", headers=headers, params=params).json()["data"]["items"]
        if counts[borough_id]:
            assert [item["borough_name"] for item in groups] == [name], (borough_id, groups)
