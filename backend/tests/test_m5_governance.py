"""M5真实PostgreSQL验收；所有输入均为随机隔离库中的合成数据。"""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

from fastapi.testclient import TestClient
import psycopg
import pytest

from app.main import app
from conftest import connect_as, seed_user
from test_m1_auth import login


def seed_basis(connection, requested_by, *, risk_level):
    suffix = uuid4().hex[:12]
    intersection_id = connection.execute("""
        INSERT INTO public.intersection
            (intersection_code,street_a,street_b,center_geom,status,source_method,
             confirmation_note,confirmed_by,confirmed_at)
        VALUES (%s,%s,%s,ST_SetSRID(ST_MakePoint(-73.99,40.72),4326),'CONFIRMED',
                'MANUAL','M5随机验证交叉口',%s,now()) RETURNING intersection_id
    """, ("M5-" + suffix, "M5 SYNTHETIC A " + suffix, "M5 SYNTHETIC B " + suffix,
          requested_by)).fetchone()[0]
    run_id = connection.execute("""
        INSERT INTO public.risk_run
            (request_id,request_hash,rule_id,period_start,period_end,status,requested_by)
        VALUES (%s,%s,1,'2025-01-01','2026-01-01','QUEUED',%s) RETURNING run_id
    """, (uuid4(), "0" * 64, requested_by)).fetchone()[0]
    collision_count = {"LOW": 1, "MEDIUM": 10, "HIGH": 30, "UNKNOWN": 1}[risk_level]
    incomplete = 1 if risk_level == "UNKNOWN" else 0
    profile_id = connection.execute("""
        INSERT INTO public.risk_profile
            (run_id,intersection_id,collision_count,injured_count,killed_count,
             vulnerable_road_user_count,incomplete_casualty_collision_count)
        VALUES (%s,%s,%s,0,0,0,%s) RETURNING profile_id
    """, (run_id, intersection_id, collision_count, incomplete)).fetchone()[0]
    connection.execute("""
        UPDATE public.risk_run SET status='SUCCEEDED', input_revision=0,
            started_at=now(), finished_at=now() WHERE run_id=%s
    """, (run_id,))
    return {"profile_id": str(profile_id), "intersection_id": str(intersection_id),
            "run_id": str(run_id), "risk_level": risk_level}


@pytest.fixture
def governance_client(isolated_db):
    with connect_as() as connection:
        users = {name: seed_user(connection, role=role)
                 for name, role in (("admin", 1), ("admin2", 1), ("creator", 2),
                                    ("assignee", 2), ("other_manager", 2), ("viewer", 3))}
        profiles = {level.lower(): seed_basis(connection, users["creator"][0], risk_level=level)
                    for level in ("LOW", "MEDIUM", "HIGH", "UNKNOWN")}
    with TestClient(app) as client:
        auth = {name: login(client, account[1]) for name, account in users.items()}
        yield client, auth, users, profiles


def task_payload(profile_id, **changes):
    return {
        "request_id": str(uuid4()),
        "profile_id": profile_id,
        "title": "检查合成路口信号配时",
        "description": "依据随机画像建立的模拟检查任务。",
        "measure_type": "SIGNAL_REVIEW",
        "priority": "HIGH",
        "radius_m": 50,
        **changes,
    }


def create_task(client, headers, profile_id, **changes):
    return client.post("/api/v1/governance-tasks", headers=headers,
                       json=task_payload(profile_id, **changes))


def history_rows(task_id):
    with connect_as() as connection:
        return connection.execute("""
            SELECT sequence_no,event_type,from_status,to_status,actor_id,note
            FROM public.task_history WHERE task_id=%s ORDER BY sequence_no
        """, (int(task_id),)).fetchall()


def test_creation_freezes_confirmed_profile_scope_and_simulation(governance_client):
    client, auth, users, profiles = governance_client
    low = profiles["low"]["profile_id"]

    assert create_task(client, auth["viewer"], low, rationale="有理由").status_code == 403
    assert create_task(client, auth["creator"], low).status_code == 422
    assert create_task(client, auth["creator"], low, rationale="有理由", status="OPEN").status_code == 422
    assert create_task(client, auth["creator"], low, rationale="有理由",
                       assessment_scope={"radius_m": 2}).status_code == 422

    unknown = profiles["unknown"]["profile_id"]
    rejected = create_task(client, auth["creator"], unknown, measure_type="OTHER",
                           priority="MEDIUM", rationale="必须现场核实未知画像")
    assert rejected.status_code == 422, rejected.text
    response = create_task(client, auth["creator"], unknown, measure_type="FIELD_SURVEY",
                           priority="MEDIUM", rationale="必须现场核实未知画像")
    assert response.status_code == 201, response.text
    data = response.json()["data"]
    assert data["task_id"].isdigit() and data["profile_id"] == unknown
    assert data["intersection_id"] == profiles["unknown"]["intersection_id"]
    assert data["task_code"].startswith("GOV-")
    assert data["status"] == "DRAFT" and data["version"] == 1
    assert data["is_simulated"] is True
    assert data["assessment_scope"] == {
        "center": {"latitude": 40.72, "longitude": -73.99},
        "radius_m": 50,
        "selection_reason": "必须现场核实未知画像",
    }
    assert "publish" not in data["allowed_actions"]
    assert "delete_draft" in data["allowed_actions"]
    publish = client.post(f"/api/v1/governance-tasks/{data['task_id']}/publish",
        headers=auth["creator"], json={"request_id": str(uuid4()), "expected_version": 1,
            "assignee_id": str(users["assignee"][0]), "note": "UNKNOWN画像禁止发布"})
    assert publish.status_code == 409, publish.text
    edit = client.patch(f"/api/v1/governance-tasks/{data['task_id']}", headers=auth["creator"],
        json={"request_id": str(uuid4()), "expected_version": 1,
              "measure_type": "OTHER", "note": "UNKNOWN调查方式不可更换"})
    assert edit.status_code == 422, edit.text
    unchanged = client.get(f"/api/v1/governance-tasks/{data['task_id']}", headers=auth["creator"])
    assert unchanged.status_code == 200
    assert unchanged.json()["data"]["version"] == 1
    assert unchanged.json()["data"]["measure_type"] == "FIELD_SURVEY"
    cancelled = client.post(f"/api/v1/governance-tasks/{data['task_id']}/cancel",
        headers=auth["creator"], json={"request_id": str(uuid4()), "expected_version": 1,
                                       "note": "取消未知画像调查草稿"})
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["data"]["status"] == "CANCELLED"

    high = create_task(client, auth["creator"], profiles["high"]["profile_id"])
    assert high.status_code == 201, high.text
    assert high.json()["data"]["risk_level"] == "HIGH"


def test_idempotency_pagination_assignee_projection_and_history(governance_client):
    client, auth, users, profiles = governance_client
    body = task_payload(profiles["low"]["profile_id"], rationale="低风险仍需现场核验")
    first = client.post("/api/v1/governance-tasks", headers=auth["creator"], json=body)
    retry = client.post("/api/v1/governance-tasks", headers=auth["creator"], json=body)
    assert first.status_code == retry.status_code == 201, (first.text, retry.text)
    task = first.json()["data"]
    assert retry.json()["data"]["task_id"] == task["task_id"]
    assert len(history_rows(task["task_id"])) == 1
    changed = {**body, "title": "同一请求编号的不同内容"}
    assert client.post("/api/v1/governance-tasks", headers=auth["creator"],
                       json=changed).status_code == 409

    assert client.get("/api/v1/governance-tasks/assignees", headers=auth["viewer"]).status_code == 403
    assignees = client.get("/api/v1/governance-tasks/assignees", headers=auth["creator"])
    assert assignees.status_code == 200, assignees.text
    rows = assignees.json()["data"]["items"]
    assert {row["role"] for row in rows} == {"ADMIN", "MANAGER"}
    assert all(set(row) == {"user_id", "display_name", "role"} for row in rows)
    assert all(row["user_id"].isdigit() for row in rows)
    assert all("username" not in row and "password_hash" not in row for row in rows)

    assert client.get("/api/v1/governance-tasks", headers=auth["viewer"]).status_code == 403
    listing = client.get("/api/v1/governance-tasks", headers=auth["creator"],
                         params={"page": 1, "page_size": 1, "status": "DRAFT"})
    assert listing.status_code == 200, listing.text
    page = listing.json()["data"]
    assert page["total"] == 1 and page["page"] == 1 and page["page_size"] == 1
    assert page["items"][0]["task_id"] == task["task_id"]


def test_full_workflow_permissions_todo_and_immutable_history(governance_client):
    client, auth, users, profiles = governance_client
    created = create_task(client, auth["creator"], profiles["medium"]["profile_id"],
                          priority="MEDIUM", rationale="画像达到中风险阈值，安排核查")
    assert created.status_code == 201, created.text
    task = created.json()["data"]
    task_id = task["task_id"]

    publish_body = {"request_id": str(uuid4()), "expected_version": 1,
                    "assignee_id": str(users["assignee"][0]), "note": "选择启用管理人员执行"}
    published = client.post(f"/api/v1/governance-tasks/{task_id}/publish",
                            headers=auth["creator"], json=publish_body)
    assert published.status_code == 200, published.text
    assert published.json()["data"]["status"] == "OPEN"
    assert published.json()["data"]["version"] == 2
    todos = client.get("/api/v1/governance-tasks", headers=auth["assignee"],
                       params={"my_todo": True})
    assert todos.status_code == 200 and [row["task_id"] for row in todos.json()["data"]["items"]] == [task_id]

    unrelated_assign = client.post(f"/api/v1/governance-tasks/{task_id}/assign", headers=auth["other_manager"],
        json={"request_id": str(uuid4()), "expected_version": 2,
              "assignee_id": str(users["admin"][0]), "note": "无关管理人员不能重分配"})
    assert unrelated_assign.status_code == 403, unrelated_assign.text
    unrelated_start = client.post(f"/api/v1/governance-tasks/{task_id}/start", headers=auth["other_manager"],
        json={"request_id": str(uuid4()), "expected_version": 2, "note": "无关管理人员不能开始"})
    assert unrelated_start.status_code == 403, unrelated_start.text

    reassigned = client.post(f"/api/v1/governance-tasks/{task_id}/assign", headers=auth["creator"],
        json={"request_id": str(uuid4()), "expected_version": 2,
              "assignee_id": str(users["admin"][0]), "note": "创建者重新指派管理员执行"})
    assert reassigned.status_code == 200, reassigned.text
    assert reassigned.json()["data"]["status"] == "OPEN"
    assert reassigned.json()["data"]["version"] == 3
    old_todos = client.get("/api/v1/governance-tasks", headers=auth["assignee"],
                           params={"my_todo": True})
    admin_todos = client.get("/api/v1/governance-tasks", headers=auth["admin"],
                             params={"my_todo": True})
    assert old_todos.status_code == 200 and old_todos.json()["data"]["items"] == []
    assert admin_todos.status_code == 200
    assert [row["task_id"] for row in admin_todos.json()["data"]["items"]] == [task_id]
    old_executor_start = client.post(f"/api/v1/governance-tasks/{task_id}/start", headers=auth["assignee"],
        json={"request_id": str(uuid4()), "expected_version": 3, "note": "原执行人已撤销"})
    assert old_executor_start.status_code == 403, old_executor_start.text

    start_request_id = str(uuid4())
    start_body = {"request_id": start_request_id, "expected_version": 3, "note": "开始现场执行"}
    start = client.post(f"/api/v1/governance-tasks/{task_id}/start", headers=auth["admin"], json=start_body)
    assert start.status_code == 200 and start.json()["data"]["status"] == "IN_PROGRESS"
    assert client.post(f"/api/v1/governance-tasks/{task_id}/start", headers=auth["creator"],
                       json=start_body).status_code == 409
    progress = client.post(f"/api/v1/governance-tasks/{task_id}/progress", headers=auth["admin"],
                           json={"request_id": str(uuid4()), "expected_version": 4, "note": "已核对现场控制器"})
    assert progress.status_code == 200 and progress.json()["data"]["version"] == 5
    submitted = client.post(f"/api/v1/governance-tasks/{task_id}/submit", headers=auth["admin"],
                            json={"request_id": str(uuid4()), "expected_version": 5, "note": "现场检查完成，请复核"})
    assert submitted.status_code == 200 and submitted.json()["data"]["status"] == "PENDING_REVIEW"
    assert "approve" not in submitted.json()["data"]["allowed_actions"]
    for decision in ("APPROVE", "REJECT"):
        self_review = client.post(f"/api/v1/governance-tasks/{task_id}/review", headers=auth["admin"],
            json={"request_id": str(uuid4()), "expected_version": 6,
                  "decision": decision, "note": "当前执行人不能自审"})
        assert self_review.status_code == 403, self_review.text

    rejected = client.post(f"/api/v1/governance-tasks/{task_id}/review", headers=auth["creator"],
                           json={"request_id": str(uuid4()), "expected_version": 6,
                                 "decision": "REJECT", "note": "请补充夜间时段检查"})
    assert rejected.status_code == 200 and rejected.json()["data"]["status"] == "IN_PROGRESS"
    progress = client.post(f"/api/v1/governance-tasks/{task_id}/progress", headers=auth["admin"],
                           json={"request_id": str(uuid4()), "expected_version": 7, "note": "已补充夜间检查"})
    assert progress.status_code == 200
    submitted = client.post(f"/api/v1/governance-tasks/{task_id}/submit", headers=auth["admin"],
                            json={"request_id": str(uuid4()), "expected_version": 8, "note": "补充后复核"})
    assert submitted.status_code == 200
    approved_request_id = str(uuid4())
    approved_body = {"request_id": approved_request_id, "expected_version": 9,
                     "decision": "APPROVE", "note": "复核通过"}
    approved = client.post(f"/api/v1/governance-tasks/{task_id}/review", headers=auth["creator"],
                           json=approved_body)
    assert approved.status_code == 200 and approved.json()["data"]["status"] == "COMPLETED"
    assert client.post(f"/api/v1/governance-tasks/{task_id}/cancel", headers=auth["creator"],
                       json={"request_id": str(uuid4()), "expected_version": 10, "note": "终态禁止取消"}).status_code == 409
    replay = client.post(f"/api/v1/governance-tasks/{task_id}/review", headers=auth["creator"],
                         json=approved_body)
    assert replay.status_code == 200 and replay.json()["data"]["status"] == "COMPLETED"
    assert replay.json()["data"]["version"] == 10
    assert len(history_rows(task_id)) == 10
    changed_replay = {**approved_body, "note": "同编号不同内容"}
    assert client.post(f"/api/v1/governance-tasks/{task_id}/review", headers=auth["creator"],
                       json=changed_replay).status_code == 409
    assert len(history_rows(task_id)) == 10

    assert client.get(f"/api/v1/governance-tasks/{task_id}", headers=auth["viewer"]).status_code == 403
    assert client.get(f"/api/v1/governance-tasks/{task_id}/history",
                      headers=auth["viewer"]).status_code == 403
    history = client.get(f"/api/v1/governance-tasks/{task_id}/history", headers=auth["creator"])
    assert history.status_code == 200, history.text
    events = history.json()["data"]["items"]
    assert [item["sequence_no"] for item in events] == list(range(1, 11))
    assert [item["event_type"] for item in events] == [
        "CREATE", "PUBLISH", "ASSIGN", "START", "PROGRESS", "SUBMIT", "REJECT",
        "PROGRESS", "SUBMIT", "APPROVE"]
    assert all(item["actor_id"].isdigit() for item in events)
    assert events[1]["changed_fields"]["assignee_id"] == users["assignee"][0].__str__()
    assert events[2]["changed_fields"]["assignee_id"] == users["admin"][0].__str__()
    assert all("assignee_id" not in events[index]["changed_fields"] for index in (3, 4, 5, 6, 7, 8, 9))
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with connect_as("app") as connection:
            connection.execute("UPDATE public.task_history SET note='改写' WHERE task_id=%s", (int(task_id),))


def test_draft_delete_is_logical_and_history_is_retained(governance_client):
    client, auth, users, profiles = governance_client
    created = create_task(client, auth["creator"], profiles["low"]["profile_id"],
                          priority="LOW", rationale="低风险画像仍安排复核")
    assert created.status_code == 201, created.text
    task_id = created.json()["data"]["task_id"]
    deleted = client.request("DELETE", f"/api/v1/governance-tasks/{task_id}", headers=auth["creator"],
        json={"request_id": str(uuid4()), "expected_version": 1, "note": "取消尚未发布的草稿"})
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["data"]["status"] == "DRAFT"
    assert deleted.json()["data"]["deleted_at"] is not None
    assert deleted.json()["data"]["version"] == 2
    assert deleted.json()["data"]["allowed_actions"] == []
    assert [row[1] for row in history_rows(task_id)] == ["CREATE", "DELETE_DRAFT"]
    rejected_edit = client.patch(f"/api/v1/governance-tasks/{task_id}", headers=auth["creator"],
        json={"request_id": str(uuid4()), "expected_version": 2,
              "title": "已删除任务不可修改", "note": "软删除后拒绝新编辑"})
    assert rejected_edit.status_code == 409, rejected_edit.text
    assert [row[1] for row in history_rows(task_id)] == ["CREATE", "DELETE_DRAFT"]
    listing = client.get("/api/v1/governance-tasks", headers=auth["creator"])
    assert all(item["task_id"] != task_id for item in listing.json()["data"]["items"])
    assert client.get(f"/api/v1/governance-tasks/{task_id}", headers=auth["assignee"]).status_code == 404
    assert client.get(f"/api/v1/governance-tasks/{task_id}/history", headers=auth["assignee"]).status_code == 404
    assert client.get(f"/api/v1/governance-tasks/{task_id}", headers=auth["creator"]).status_code == 200
    assert client.get(f"/api/v1/governance-tasks/{task_id}/history", headers=auth["creator"]).status_code == 200


def test_replay_by_downgraded_admin_cannot_read_deleted_foreign_draft(governance_client):
    client, auth, users, profiles = governance_client
    created = create_task(client, auth["creator"], profiles["high"]["profile_id"])
    assert created.status_code == 201, created.text
    task_id = created.json()["data"]["task_id"]

    edit = {"request_id": str(uuid4()), "expected_version": 1,
            "title": "管理员先修改的合成草稿", "note": "记录管理员编辑动作"}
    edited = client.patch(f"/api/v1/governance-tasks/{task_id}", headers=auth["admin"], json=edit)
    assert edited.status_code == 200, edited.text
    assert edited.json()["data"]["version"] == 2

    deleted = client.request("DELETE", f"/api/v1/governance-tasks/{task_id}", headers=auth["creator"],
        json={"request_id": str(uuid4()), "expected_version": 2, "note": "创建者删除草稿"})
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["data"]["version"] == 3

    demoted = client.patch(f"/api/v1/users/{users['admin'][0]}", headers=auth["admin2"],
                           json={"expected_version": 1, "role": "MANAGER"})
    assert demoted.status_code == 200, demoted.text
    downgraded_headers = login(client, users["admin"][1])
    assert client.get(f"/api/v1/governance-tasks/{task_id}", headers=downgraded_headers).status_code == 404

    replay = client.patch(f"/api/v1/governance-tasks/{task_id}", headers=downgraded_headers, json=edit)
    assert replay.status_code == 404, replay.text
    with connect_as() as connection:
        version, history_count = connection.execute("""
            SELECT t.version,(SELECT count(*) FROM public.task_history h WHERE h.task_id=t.task_id)
            FROM public.governance_task t WHERE t.task_id=%s
        """, (int(task_id),)).fetchone()
    assert (version, history_count) == (3, 3)


def test_two_connections_serialize_version_and_account_changes(governance_client):
    client, auth, users, profiles = governance_client
    created = create_task(client, auth["creator"], profiles["low"]["profile_id"],
                          priority="LOW", rationale="低风险仍需说明复核原因")
    assert created.status_code == 201, created.text
    task_id = created.json()["data"]["task_id"]

    barrier = Barrier(2)

    def patch_as(username):
        with TestClient(app) as concurrent_client:
            headers = login(concurrent_client, users[username][1])
            body = {"request_id": str(uuid4()), "expected_version": 1,
                    "title": "并发编辑 " + username, "note": "双连接版本冲突测试"}
            barrier.wait(timeout=15)
            return concurrent_client.patch(f"/api/v1/governance-tasks/{task_id}",
                                           headers=headers, json=body)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(patch_as, ("creator", "admin")))
    assert sorted(result.status_code for result in results) == [200, 409], [r.text for r in results]
    assert len(history_rows(task_id)) == 2

    draft = create_task(client, auth["creator"], profiles["medium"]["profile_id"],
                        priority="MEDIUM", rationale="中风险处置候选需说明依据")
    assert draft.status_code == 201, draft.text
    draft_id = draft.json()["data"]["task_id"]
    race = Barrier(2)

    def publish():
        with TestClient(app) as concurrent_client:
            headers = login(concurrent_client, users["creator"][1])
            race.wait(timeout=15)
            return concurrent_client.post(f"/api/v1/governance-tasks/{draft_id}/publish", headers=headers,
                json={"request_id": str(uuid4()), "expected_version": 1,
                      "assignee_id": str(users["assignee"][0]), "note": "账户状态竞态测试"})

    def disable_assignee():
        with TestClient(app) as concurrent_client:
            headers = login(concurrent_client, users["admin"][1])
            race.wait(timeout=15)
            return concurrent_client.patch(f"/api/v1/users/{users['assignee'][0]}", headers=headers,
                json={"expected_version": 1, "is_active": False})

    with ThreadPoolExecutor(max_workers=2) as pool:
        publish_result, disable_result = list(pool.map(lambda fn: fn(), (publish, disable_assignee)))
    assert ((publish_result.status_code, disable_result.status_code) == (422, 200)
            or (publish_result.status_code, disable_result.status_code) == (200, 409)), (
        publish_result.text, disable_result.text)
    with connect_as() as connection:
        task_status, assigned_user_active = connection.execute("""
            SELECT t.status,u.is_active FROM public.governance_task t
            JOIN public.app_user u ON u.user_id=%s WHERE t.task_id=%s
        """, (users["assignee"][0], int(draft_id))).fetchone()
    assert (task_status == "DRAFT" and not assigned_user_active) or (
        task_status == "OPEN" and assigned_user_active)


def test_history_failure_rolls_back_task_and_version(governance_client):
    client, auth, users, profiles = governance_client
    created = create_task(client, auth["creator"], profiles["low"]["profile_id"],
                          priority="LOW", rationale="低风险说明现场执行理由")
    assert created.status_code == 201, created.text
    task_id = created.json()["data"]["task_id"]
    published = client.post(f"/api/v1/governance-tasks/{task_id}/publish", headers=auth["creator"],
        json={"request_id": str(uuid4()), "expected_version": 1,
              "assignee_id": str(users["assignee"][0]), "note": "发布以便制造历史失败"})
    assert published.status_code == 200, published.text

    with connect_as() as connection:
        connection.execute("""
            CREATE FUNCTION public.m5_fail_history_insert() RETURNS trigger
            LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
            BEGIN
              IF NEW.event_type='START' THEN
                RAISE EXCEPTION 'synthetic M5 history failure' USING ERRCODE='23514';
              END IF;
              RETURN NEW;
            END $$;
            CREATE TRIGGER m5_fail_history_insert BEFORE INSERT ON public.task_history
            FOR EACH ROW EXECUTE FUNCTION public.m5_fail_history_insert()
        """)
    failed = client.post(f"/api/v1/governance-tasks/{task_id}/start", headers=auth["assignee"],
        json={"request_id": str(uuid4()), "expected_version": 2, "note": "此事件被测试触发器拒绝"})
    assert failed.status_code == 409, failed.text
    detail = client.get(f"/api/v1/governance-tasks/{task_id}", headers=auth["creator"])
    assert detail.status_code == 200, detail.text
    assert detail.json()["data"]["status"] == "OPEN"
    assert detail.json()["data"]["version"] == 2
    assert [row[1] for row in history_rows(task_id)] == ["CREATE", "PUBLISH"]


def test_app_and_worker_cannot_directly_write_task_history(governance_client):
    client, auth, users, profiles = governance_client
    created = create_task(client, auth["creator"], profiles["low"]["profile_id"],
                          priority="LOW", rationale="低风险的合成权限测试任务")
    assert created.status_code == 201, created.text
    task_id = int(created.json()["data"]["task_id"])

    for role in ("app", "worker"):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with connect_as(role) as connection:
                connection.execute("UPDATE public.governance_task SET status='COMPLETED' WHERE task_id=%s",
                                   (task_id,))
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with connect_as(role) as connection:
                connection.execute("""
                    INSERT INTO public.task_history
                        (task_id,sequence_no,request_id,request_hash,event_type,from_status,to_status,
                         actor_id,note,changed_fields)
                    VALUES (%s,99,%s,%s,'PROGRESS','DRAFT','DRAFT',%s,'越权写历史','{}'::jsonb)
                """, (task_id, uuid4(), "0" * 64, users["creator"][0]))


def test_database_functions_reject_nulls_and_bind_replays_to_actor_and_target(governance_client):
    client, auth, users, profiles = governance_client
    body = task_payload(profiles["high"]["profile_id"])
    created = client.post("/api/v1/governance-tasks", headers=auth["creator"], json=body)
    assert created.status_code == 201, created.text
    task_id = int(created.json()["data"]["task_id"])
    with connect_as() as connection:
        create_hash = connection.execute("""
            SELECT request_hash FROM public.governance_task WHERE task_id=%s
        """, (task_id,)).fetchone()[0]

    invalid_calls = [
        ("""SELECT public.vz_governance_create(%s,%s,%s,NULL,%s,%s,%s,%s,NULL,NULL,50,NULL)""",
         (users["creator"][0], int(profiles["high"]["profile_id"]), uuid4(),
          "标题", "描述", "SIGNAL_REVIEW", "HIGH")),
        ("""SELECT public.vz_governance_change(%s,1,NULL,%s,%s,%s,%s::jsonb)""",
         (task_id, users["creator"][0], uuid4(), "0" * 64, '{"note":"校验空动作"}')),
        ("""SELECT public.vz_governance_change(%s,1,'CANCEL',%s,%s,NULL,%s::jsonb)""",
         (task_id, users["creator"][0], uuid4(), '{"note":"校验空摘要"}')),
        ("""SELECT public.vz_governance_change(%s,1,'REVIEW',%s,%s,%s,%s::jsonb)""",
         (task_id, users["creator"][0], uuid4(), "0" * 64,
          '{"note":"校验空决策","decision":null}')),
    ]
    for statement, params in invalid_calls:
        with pytest.raises(psycopg.Error, match="VZ_INVALID_INPUT"):
            with connect_as("app") as connection:
                connection.execute(statement, params)

    with pytest.raises(psycopg.Error, match="VZ_REQUEST_CONFLICT"):
        with connect_as("app") as connection:
            connection.execute("""
                SELECT public.vz_governance_create(%s,%s,%s,%s,%s,%s,%s,%s,NULL,NULL,50,NULL)
            """, (users["admin"][0], int(profiles["high"]["profile_id"]),
                  body["request_id"], create_hash, body["title"], body["description"],
                  body["measure_type"], body["priority"]))

    change_request_id = str(uuid4())
    published = client.post(f"/api/v1/governance-tasks/{task_id}/publish", headers=auth["creator"],
        json={"request_id": change_request_id, "expected_version": 1,
              "assignee_id": str(users["assignee"][0]), "note": "建立目标绑定重放记录"})
    assert published.status_code == 200, published.text
    with connect_as() as connection:
        change_hash = connection.execute("""
            SELECT request_hash FROM public.task_history WHERE request_id=%s
        """, (change_request_id,)).fetchone()[0]
    second = create_task(client, auth["creator"], profiles["high"]["profile_id"])
    assert second.status_code == 201, second.text
    with pytest.raises(psycopg.Error, match="VZ_REQUEST_CONFLICT"):
        with connect_as("app") as connection:
            connection.execute("""
                SELECT public.vz_governance_change(%s,1,'PUBLISH',%s,%s,%s,%s::jsonb)
            """, (int(second.json()["data"]["task_id"]), users["creator"][0],
                  change_request_id, change_hash,
                  '{"note":"不能跨目标重放","assignee_id":"' + str(users["assignee"][0]) + '"}'))
