"""M2清洗契约与真实PG导入/权限/幂等/回滚验收；输入全部为人工合成。"""

import csv
from datetime import date
import io
from uuid import uuid4
from unittest.mock import patch

from fastapi.testclient import TestClient
import pytest
import psycopg
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db.connection import database_engine
from app.importing.cleaning import HEADERS, ImportProblem, normalized, quantity, required_fields, resolve_headers, source_id
from app.importing import jobs
from app.main import app
from app.models import ImportBatch
from conftest import connect_as, seed_user
from test_m1_auth import login

START, END = date(2025, 1, 1), date(2026, 1, 1)


@pytest.mark.parametrize("value", ["1.0", "1e3", "-1", "0", "１２", "9223372036854775808", ""])
def test_source_identifiers_are_exact_positive_integers(value):
    with pytest.raises(ValueError): source_id(value)


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-1", "1.1", "2147483648"])
def test_counts_cannot_be_invalid_or_silently_rounded(value):
    with pytest.raises((ValueError, ArithmeticError)): quantity(value)


def test_fixed_header_modes_and_missing_cause_columns():
    for kind in HEADERS:
        display = list(HEADERS[kind])
        api = list(HEADERS[kind].values())
        assert resolve_headers(kind, api)[0] == "api"
        assert resolve_headers(kind, display)[0] == "display"
        with pytest.raises(ImportProblem): resolve_headers(kind, api + [display[0]])
    headers = list(required_fields("CRASHES") - {"contributing_factor_vehicle_5"})
    with pytest.raises(ImportProblem): resolve_headers("CRASHES", headers)


def test_null_zero_coordinates_and_display_streets():
    row = {"collision_id": "9007199254740993", "crash_date": "2025-01-01T00:00:00.000", "crash_time": "bad",
           "latitude": "0", "longitude": "0", "number_of_persons_injured": "0", "number_of_persons_killed": "",
           "off_street_name": " Cross road ", "cross_street_name": "123 address"}
    value, issues, status = normalized("CRASHES", row, {}, START, END)
    assert status == "ACCEPTED" and value["id"] == 9007199254740993
    assert value["casualty"]["persons_injured"] == 0 and value["casualty"]["persons_killed"] is None
    assert value["location"]["latitude"] is None and value["crash_time"] is None
    assert value["location"]["cross_street_name"] == "CROSS ROAD"
    assert value["location"]["off_street_name"] == "123 ADDRESS"
    assert issues


def csv_bytes(kind, rows):
    stream = io.StringIO(newline="")
    fields = list(HEADERS[kind].values()) + ["unmapped_test_note"]
    writer = csv.DictWriter(stream, fields)
    writer.writeheader()
    for row in rows: writer.writerow({name: row.get(name, "") for name in fields})
    return stream.getvalue().encode("utf-8-sig")


def inputs(*, street="SYNTHETIC A", factor="SYNTHETIC FACTOR", conflicts=False):
    crash = {"collision_id": "9007199254740993", "crash_date": "2025-01-01", "crash_time": "12:30", "borough": "MANHATTAN",
             "on_street_name": street, "off_street_name": "SYNTHETIC CROSS", "latitude": "40.7", "longitude": "-74.0",
             "number_of_persons_injured": "0", "contributing_factor_vehicle_1": factor,
             "unmapped_test_note": '合成引号"与\n多行'}
    other = {**crash, "collision_id": "9007199254740994", "crash_date": "2025-01-02"}
    crashes = [crash, other]
    if conflicts: crashes.append({**crash, "on_street_name": "CONFLICT"})
    person = {"unique_id": "12345", "collision_id": crash["collision_id"], "crash_date": "2025-01-01", "person_type": "Pedestrian",
              "person_injury": "Unspecified", "person_age": "30", "person_sex": "F", "person_id": "TEXT-CODE", "vehicle_id": "NOT-FK"}
    vehicle = {"unique_id": "67890", "collision_id": crash["collision_id"], "crash_date": "2025-01-01", "vehicle_type": " synthetic car ", "vehicle_year": "2020"}
    return {"crashes": csv_bytes("CRASHES", crashes), "persons": csv_bytes("PERSON", [person, {**person, "unique_id": "12346", "collision_id": "999999"}]),
            "vehicles": csv_bytes("VEHICLES", [vehicle])}


def upload(client, headers, files, request_id=None):
    return client.post("/api/v1/imports", headers=headers,
                       data={"request_id": str(request_id or uuid4()), "requested_start": str(START), "requested_end": str(END), "header_mode": "api"},
                       files={name: (name + ".csv", value, "text/csv") for name, value in files.items()})


def execute_job():
    engine = database_engine(Settings(), worker=True)
    try:
        job = jobs.claim(engine)
        assert job
        (jobs.publish if job[2] == "publish" else jobs.validate)(engine, job[0], job[1])
    finally: engine.dispose()


@pytest.fixture
def clients(isolated_db):
    with connect_as() as connection:
        names = [seed_user(connection, role=role)[1] for role in (1, 1, 2, 3)]
    with TestClient(app) as client:
        yield client, [login(client, name) for name in names], names


def test_pipeline_roles_repeat_content_revision_and_trace(clients):
    client, (admin, _, manager, viewer), _ = clients
    files, request_id = inputs(), uuid4()
    result = upload(client, admin, files, request_id)
    assert result.status_code == 202, result.text
    number = result.json()["data"]["batch_id"]
    assert upload(client, admin, files, request_id).json()["data"]["batch_id"] == number
    assert upload(client, admin, inputs(street="CHANGED"), request_id).status_code == 409
    assert client.get("/api/v1/imports", headers=viewer).status_code == 403
    assert client.post(f"/api/v1/imports/{number}/publish", headers=manager, json={"request_id": str(uuid4())}).status_code == 403
    execute_job()
    detail = client.get(f"/api/v1/imports/{number}", headers=admin).json()["data"]
    assert detail["status"] == "READY" and detail["rows_read"] == 5 and detail["rows_accepted"] == 4 and detail["rows_rejected"] == 1
    assert "input_manifest" not in client.get(f"/api/v1/imports/{number}", headers=manager).json()["data"]
    assert client.get(f"/api/v1/imports/{number}/issues", headers=manager).status_code == 403
    publish_id = str(uuid4())
    assert client.post(f"/api/v1/imports/{number}/publish", headers=admin, json={"request_id": publish_id}).status_code == 202
    execute_job()
    assert client.post(f"/api/v1/imports/{number}/publish", headers=admin, json={"request_id": publish_id}).json()["data"]["status"] == "SUCCEEDED"
    listing = client.get("/api/v1/collisions", headers=viewer, params={"page_size": 1, "include_total": True}).json()
    assert listing["data"]["total"] == 2 and listing["meta"]["data_revision"] == "1"
    from app import data_api
    original_data = data_api.collision_data
    changed_revision = False
    def advance_revision(row):
        nonlocal changed_revision
        if not changed_revision:
            with connect_as() as connection: connection.execute("UPDATE dataset_state SET revision=revision+1")
            changed_revision = True
        return original_data(row)
    with patch.object(data_api, "collision_data", side_effect=advance_revision):
        assert client.get("/api/v1/collisions", headers=viewer).json()["meta"]["data_revision"] == "1"
    with connect_as() as connection: connection.execute("UPDATE dataset_state SET revision=revision-1")
    cursor = listing["data"]["next_cursor"]
    assert listing["data"]["items"][0]["collision_id"] == "9007199254740994"
    assert client.get("/api/v1/collisions", headers=viewer, params={"page_size": 1, "cursor": cursor}).json()["data"]["items"][0]["collision_id"] == "9007199254740993"
    assert client.get("/api/v1/collisions", headers=viewer, params={"page_size": 1, "cursor": cursor, "street": "OTHER"}).status_code == 409
    person_path = "/api/v1/collisions/9007199254740993/persons"
    minimal = client.get(person_path, headers=viewer).json()["data"]["items"][0]
    assert set(minimal) == {"person_id", "collision_id", "person_type", "person_injury"}
    assert client.get(person_path, headers=manager).json()["data"]["items"][0]["person_age"] == 30
    detail = client.get("/api/v1/collisions/9007199254740993", headers=viewer).json()["data"]
    assert detail["persons_injured"] == 0 and detail["persons_killed"] is None
    raw_id = detail["source"]["raw_record_id"]
    assert client.get(f"/api/v1/raw-records/{raw_id}", headers=viewer).status_code == 403
    assert client.get(f"/api/v1/raw-records/{raw_id}", headers=admin).json()["data"]["payload"]["unmapped_test_note"] == '合成引号"与\n多行'
    type_id = client.get("/api/v1/dictionaries/vehicle-types", headers=viewer).json()["data"]["items"][0]["id"]
    assert client.get("/api/v1/collisions", headers=viewer, params={"vehicle_type_id": type_id, "include_total": True}).json()["data"]["total"] == 1
    issue = client.get(f"/api/v1/imports/{number}/issues", headers=admin).json()["data"]["items"][0]
    assert client.patch(f'/api/v1/data-issues/{issue["issue_id"]}', headers=admin, json={"status": "RESOLVED", "resolution_note": "合成测试人工确认"}).status_code == 200
    repeat = upload(client, admin, files).json()["data"]["batch_id"]
    execute_job()
    client.post(f"/api/v1/imports/{repeat}/publish", headers=admin, json={"request_id": str(uuid4())})
    execute_job()
    assert client.get(f"/api/v1/imports/{repeat}", headers=admin).json()["data"]["input_manifest"]["publication"] == {"inserted": 0, "updated": 0, "unchanged": 4, "revision": "1", "no_change": True}
    changed = upload(client, admin, inputs(street="UPDATED ROAD", factor="")).json()["data"]["batch_id"]
    execute_job()
    client.post(f"/api/v1/imports/{changed}/publish", headers=admin, json={"request_id": str(uuid4())})
    execute_job()
    current = client.get("/api/v1/collisions/9007199254740993", headers=viewer).json()["data"]
    assert current["on_street_name"] == "UPDATED ROAD" and current["factors"] == []
    assert current["source"]["raw_record_id"] != raw_id
    assert client.get(f"/api/v1/raw-records/{raw_id}", headers=admin).json()["data"]["payload"]["on_street_name"] == "SYNTHETIC A"
    with connect_as() as connection:
        assert connection.execute("SELECT count(*) FROM collision").fetchone()[0] == 2
        assert connection.execute("SELECT count(*) FROM casualty_stat").fetchone()[0] == 2
        assert connection.execute("SELECT count(*) FROM location").fetchone()[0] == 2
        assert connection.execute("SELECT revision FROM dataset_state").fetchone()[0] == 2


@pytest.mark.parametrize("header_mode", ["api", "display"])
def test_child_only_import_matches_existing_parent_with_trimmed_identifier(clients, header_mode):
    client, (admin, _, _, _), _ = clients
    initial = upload(client, admin, inputs()).json()["data"]["batch_id"]
    execute_job()
    client.post(f"/api/v1/imports/{initial}/publish", headers=admin, json={"request_id": str(uuid4())})
    execute_job()
    parent = "\t\u00a0 09007199254740993\n\u3000"
    rows = {"CRASHES": [], "PERSON": [{"unique_id": "23456", "collision_id": parent, "crash_date": "2025-01-01"}],
            "VEHICLES": [{"unique_id": "78901", "collision_id": parent, "crash_date": "2025-01-01"}]}
    files = {}
    for kind, values in rows.items():
        stream = io.StringIO(newline="")
        fields = list(HEADERS[kind]) if header_mode == "display" else list(HEADERS[kind].values())
        writer = csv.DictWriter(stream, fields)
        writer.writeheader()
        for row in values:
            writer.writerow({name: row.get(HEADERS[kind][name] if header_mode == "display" else name, "") for name in fields})
        files[{"CRASHES": "crashes", "PERSON": "persons", "VEHICLES": "vehicles"}[kind]] = (kind + ".csv", stream.getvalue().encode("utf-8-sig"), "text/csv")
    result = client.post("/api/v1/imports", headers=admin,
        data={"request_id": str(uuid4()), "requested_start": str(START), "requested_end": str(END), "header_mode": header_mode}, files=files)
    assert result.status_code == 202
    number = result.json()["data"]["batch_id"]
    execute_job()
    detail = client.get(f"/api/v1/imports/{number}", headers=admin).json()["data"]
    assert detail["status"] == "READY" and detail["rows_accepted"] == 2 and detail["rows_rejected"] == 0
    client.post(f"/api/v1/imports/{number}/publish", headers=admin, json={"request_id": str(uuid4())})
    execute_job()
    with connect_as() as connection:
        assert connection.execute("SELECT collision_id FROM person WHERE person_id=23456").fetchone()[0] == 9007199254740993
        assert connection.execute("SELECT collision_id FROM vehicle WHERE vehicle_id=78901").fetchone()[0] == 9007199254740993


def test_conflicting_keys_block_and_retry_preserves_resolution(clients):
    client, (admin, _, _, _), _ = clients
    number = upload(client, admin, inputs(conflicts=True)).json()["data"]["batch_id"]
    execute_job()
    assert client.get(f"/api/v1/imports/{number}", headers=admin).json()["data"]["status"] == "FAILED"
    assert client.post(f"/api/v1/imports/{number}/publish", headers=admin, json={"request_id": str(uuid4())}).status_code == 409
    issue = client.get(f"/api/v1/imports/{number}/issues", headers=admin).json()["data"]["items"][0]
    client.patch(f'/api/v1/data-issues/{issue["issue_id"]}', headers=admin, json={"status": "RESOLVED", "resolution_note": "人工测试"})
    before = client.get(f"/api/v1/imports/{number}/issues", headers=admin).json()["data"]["total"]
    retry_id = str(uuid4())
    assert client.post(f"/api/v1/imports/{number}/retry", headers=admin, json={"request_id": retry_id}).status_code == 202
    execute_job()
    issues = client.get(f"/api/v1/imports/{number}/issues", headers=admin).json()["data"]
    assert issues["total"] == before and issues["items"][0]["status"] == "RESOLVED"
    assert client.post(f"/api/v1/imports/{number}/retry", headers=admin, json={"request_id": retry_id}).json()["data"]["status"] == "FAILED"


def test_publish_authorization_rechecked_and_atomic_rollback(clients):
    client, (admin, _, _, _), names = clients
    number = upload(client, admin, inputs()).json()["data"]["batch_id"]
    execute_job()
    client.post(f"/api/v1/imports/{number}/publish", headers=admin, json={"request_id": str(uuid4())})
    with connect_as() as connection: connection.execute("UPDATE app_user SET role_id=2 WHERE username=%s", (names[0],))
    assert jobs.run_once()["error_code"] == "PUBLISHER_NO_LONGER_AUTHORIZED"
    with connect_as() as connection:
        assert connection.execute("SELECT count(*) FROM collision").fetchone()[0] == 0
        connection.execute("UPDATE app_user SET role_id=1 WHERE username=%s", (names[0],))
    admin = login(client, names[0])
    client.post(f"/api/v1/imports/{number}/retry", headers=admin, json={"request_id": str(uuid4())})
    execute_job()
    client.post(f"/api/v1/imports/{number}/publish", headers=admin, json={"request_id": str(uuid4())})
    original = jobs.write_facts
    def fail_after_write(*args):
        original(*args)
        raise ImportProblem("SYNTHETIC_FAILURE")
    with patch.object(jobs, "write_facts", side_effect=fail_after_write):
        assert jobs.run_once()["error_code"] == "SYNTHETIC_FAILURE"
    with connect_as() as connection:
        assert connection.execute("SELECT count(*) FROM collision").fetchone()[0] == 0
        assert connection.execute("SELECT count(*) FROM location").fetchone()[0] == 0
        assert connection.execute("SELECT revision FROM dataset_state").fetchone()[0] == 0


def test_expired_token_is_fenced_and_worker_recovers_failed(clients):
    client, (admin, _, _, _), _ = clients
    number = upload(client, admin, inputs()).json()["data"]["batch_id"]
    engine = database_engine(Settings(), worker=True)
    try:
        job = jobs.claim(engine)
        with connect_as() as connection: connection.execute("UPDATE import_batch SET lease_expires_at=clock_timestamp()-interval '1 second' WHERE batch_id=%s", (int(number),))
        assert jobs.claim(engine) is None
        with pytest.raises(ImportProblem, match="JOB_LEASE_LOST"): jobs.validate(engine, job[0], job[1])
        with connect_as() as connection:
            assert connection.execute("SELECT status FROM import_batch WHERE batch_id=%s", (int(number),)).fetchone()[0] == "FAILED"
            assert connection.execute("SELECT count(*) FROM raw_record").fetchone()[0] == 0
    finally: engine.dispose()


def test_upload_bounds_bad_headers_and_unauthorized_access(clients):
    client, (admin, _, manager, viewer), _ = clients
    files = inputs()
    assert upload(client, admin, {**files, "crashes": b"collision_id\n1\n"}).status_code == 422
    for role in (manager, viewer): assert upload(client, role, files).status_code == 403
    assert client.post("/api/v1/imports", headers={"Content-Type": "multipart/form-data"}, content=b"bad-form").status_code == 401
    for role in (manager, viewer):
        assert client.post("/api/v1/imports", headers={**role, "Content-Type": "multipart/form-data"}, content=b"bad-form").status_code == 403
    result = client.post("/api/v1/imports", headers={**admin, "Content-Length": str(300 * 1024 * 1024)}, content=b"x")
    assert result.status_code == 413
    assert result.headers["X-Request-ID"] == result.json()["meta"]["request_id"]
    assert client.get("/api/v1/audit-logs", headers=viewer).status_code == 403


def test_runtime_cannot_skip_states_or_mutate_saved_input(clients):
    client, (admin, _, _, _), _ = clients
    number = upload(client, admin, inputs()).json()["data"]["batch_id"]
    for kind, statement in [("app", "UPDATE import_batch SET status='VALIDATING' WHERE batch_id=%s"),
                            ("worker", "UPDATE import_batch SET input_manifest=jsonb_set(input_manifest,'{files}','[]') WHERE batch_id=%s")]:
        with pytest.raises(psycopg.errors.CheckViolation):
            with connect_as(kind) as connection: connection.execute(statement, (int(number),))
    execute_job()
    with pytest.raises(psycopg.errors.CheckViolation):
        with connect_as("worker") as connection:
            connection.execute("UPDATE import_batch SET status='PUBLISHING' WHERE batch_id=%s", (int(number),))


def test_invalid_upload_cleanup_and_chunked_body_limit(clients):
    from app.config import PROJECT_ROOT
    from app import upload_limit
    client, (admin, _, _, _), _ = clients
    root = PROJECT_ROOT / "data/raw" / Settings().database_name
    before = set(root.iterdir()) if root.exists() else set()
    assert upload(client, admin, {**inputs(), "vehicles": b"wrong\n1\n"}).status_code == 422
    assert set(root.iterdir()) == before
    with patch.object(upload_limit, "MAX_BYTES", 16):
        body = b'--test\r\nContent-Disposition: form-data; name="crashes"; filename="file.csv"\r\nContent-Type: text/csv\r\n\r\n' + b'x' * (2 * 1024 * 1024) + b'\r\n--test--\r\n'
        result = client.post("/api/v1/imports", headers={**admin, "Content-Type": "multipart/form-data; boundary=test"}, content=iter([body]))
        assert result.status_code == 413, result.text


def test_malformed_csv_is_failed_and_leaves_no_facts(clients):
    client, (admin, _, _, _), _ = clients
    files = inputs()
    files["crashes"] = files["crashes"] + b'"unterminated\n'
    number = upload(client, admin, files).json()["data"]["batch_id"]
    assert jobs.run_once()["error_code"] == "CSV_READ_FAILED"
    assert client.get(f"/api/v1/imports/{number}", headers=admin).json()["data"]["status"] == "FAILED"
    with connect_as() as connection: assert connection.execute("SELECT count(*) FROM collision").fetchone()[0] == 0
