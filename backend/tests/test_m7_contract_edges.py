"""M7合同边界测试；所有输入均为合成数据，数据库用例依赖隔离PG fixture。"""

import csv
import io
from datetime import date, time, timezone
from uuid import uuid4

from app import risks
from app.importing.cleaning import normalized
from conftest import connect_as
from test_m2_imports import END, START, clients, csv_bytes, execute_job, inputs, upload
from test_m4_risks import request_run, risk_client


def _validated_batch(client, admin, files):
    uploaded = upload(client, admin, files)
    assert uploaded.status_code == 202, uploaded.text
    batch_id = uploaded.json()["data"]["batch_id"]
    execute_job()
    detail = client.get(f"/api/v1/imports/{batch_id}", headers=admin).json()["data"]
    assert detail["status"] == "READY", detail
    return batch_id, detail


def _publish_batch(client, admin, batch_id):
    response = client.post(
        f"/api/v1/imports/{batch_id}/publish",
        headers=admin,
        json={"request_id": str(uuid4())},
    )
    assert response.status_code == 202, response.text
    execute_job()
    detail = client.get(f"/api/v1/imports/{batch_id}", headers=admin).json()["data"]
    assert detail["status"] == "SUCCEEDED", detail
    return detail


def _files_with_factors(slot_one, slot_two):
    files = inputs()
    rows = list(csv.DictReader(io.StringIO(files["crashes"].decode("utf-8-sig"))))
    rows[0]["contributing_factor_vehicle_1"] = slot_one
    rows[0]["contributing_factor_vehicle_2"] = slot_two
    files["crashes"] = csv_bytes("CRASHES", rows)
    return files


def test_missing_parent_child_is_rejected_with_issue_and_never_published(clients):
    client, (admin, _, _, _), _ = clients
    batch_id, validated = _validated_batch(client, admin, inputs())

    assert validated["rows_accepted"] == 4
    assert validated["rows_rejected"] == 1
    with connect_as() as connection:
        orphan_id, orphan_status = connection.execute(
            """SELECT raw_record_id, validation_status FROM raw_record
               WHERE batch_id=%s AND source_kind='PERSON' AND source_key='12346'""",
            (batch_id,),
        ).fetchone()
        issue = connection.execute(
            """SELECT issue_code, severity FROM data_issue
               WHERE batch_id=%s AND raw_record_id=%s""",
            (batch_id, orphan_id),
        ).fetchone()
    assert orphan_status == "REJECTED"
    assert issue == ("MISSING_PARENT", "ERROR")

    _publish_batch(client, admin, batch_id)
    with connect_as() as connection:
        people = connection.execute(
            "SELECT person_id FROM person WHERE person_id IN (12345,12346) ORDER BY person_id"
        ).fetchall()
    assert people == [(12345,)]


def test_local_date_time_ignore_session_timezone_while_timestamp_keeps_instant(clients):
    client, (admin, _, _, _), _ = clients
    batch_id, _ = _validated_batch(client, admin, inputs())
    _publish_batch(client, admin, batch_id)

    def read_values(zone):
        with connect_as() as connection:
            connection.execute("SELECT set_config('TimeZone', %s, false)", (zone,))
            return connection.execute(
                """SELECT c.crash_date, c.crash_time, s.updated_at
                   FROM collision c CROSS JOIN dataset_state s
                   WHERE c.collision_id=9007199254740993 AND s.state_id=1"""
            ).fetchone()

    utc_values = read_values("UTC")
    pacific_values = read_values("America/Los_Angeles")
    assert utc_values[:2] == pacific_values[:2] == (date(2025, 1, 1), time(12, 30))
    assert utc_values[2].utcoffset() != pacific_values[2].utcoffset()
    assert utc_values[2].astimezone(timezone.utc) == pacific_values[2].astimezone(timezone.utc)


def test_swapped_latitude_longitude_are_flagged_by_nyc_prefilter():
    row = {
        "collision_id": "9007199254740993",
        "crash_date": "2025-01-01",
        "crash_time": "12:30",
        "latitude": "-74.0",
        "longitude": "40.7",
        "number_of_persons_injured": "0",
        "number_of_persons_killed": "0",
    }
    value, issues, status = normalized("CRASHES", row, {}, START, END)

    assert status == "ACCEPTED"
    assert value["location"]["latitude"] == "-74"
    assert value["location"]["longitude"] == "40.7"
    assert any(issue["issue_code"] == "OUTSIDE_NYC_RECTANGLE" for issue in issues)


def test_manual_location_reassignment_revises_data_and_stales_published_profiles(risk_client):
    client, (admin, manager, viewer), _ = risk_client
    with connect_as() as connection:
        revision_before = connection.execute(
            "SELECT revision FROM dataset_state WHERE state_id=1"
        ).fetchone()[0]
        location_id, old_intersection_id, version = connection.execute(
            """SELECT location_id, intersection_id, version FROM location_assignment
               WHERE intersection_id IS NOT NULL ORDER BY location_id LIMIT 1"""
        ).fetchone()
        target_id = connection.execute(
            """SELECT intersection_id FROM intersection
               WHERE status='CONFIRMED' AND is_active AND intersection_id<>%s
               ORDER BY intersection_id LIMIT 1""",
            (old_intersection_id,),
        ).fetchone()[0]

    queued = request_run(client, manager)
    assert queued.status_code == 202, queued.text
    run_id = queued.json()["data"]["run_id"]
    assert risks.run_once()["status"] == "processed"
    run_url = f"/api/v1/risk-runs/{run_id}"
    assert client.get(run_url, headers=viewer).json()["data"]["is_stale"] is False
    profiles_url = "/api/v1/risk-profiles"
    before = client.get(profiles_url, headers=viewer, params={"run_id": run_id}).json()["data"]["items"]
    assert before and all(not profile["is_stale"] for profile in before)

    changed = client.patch(
        f"/api/v1/location-assignments/{location_id}",
        headers=manager,
        json={
            "version": version,
            "status": "MANUAL_CONFIRMED",
            "intersection_id": str(target_id),
            "reason": "M7合成测试人工改派",
        },
    )
    assert changed.status_code == 200, changed.text
    assert int(changed.json()["data"]["data_revision"]) > revision_before
    assert client.get(run_url, headers=viewer).json()["data"]["is_stale"] is True
    after = client.get(profiles_url, headers=viewer, params={"run_id": run_id}).json()["data"]["items"]
    assert len(after) == len(before) and all(profile["is_stale"] for profile in after)


def test_clearing_one_factor_slot_preserves_another(clients):
    client, (admin, _, _, _), _ = clients
    first_id, _ = _validated_batch(
        client, admin, _files_with_factors("SYNTHETIC FACTOR ONE", "SYNTHETIC FACTOR TWO")
    )
    _publish_batch(client, admin, first_id)

    second_id, _ = _validated_batch(
        client, admin, _files_with_factors("", "SYNTHETIC FACTOR TWO")
    )
    _publish_batch(client, admin, second_id)

    with connect_as() as connection:
        slots = connection.execute(
            """SELECT factor_order FROM collision_factor
               WHERE collision_id=9007199254740993 ORDER BY factor_order"""
        ).fetchall()
    assert slots == [(2,)]
