"""在已验证的隔离恢复库中建立可重复展示的模拟课程数据。"""

from datetime import datetime, timezone
import importlib
import json
import os
from pathlib import Path
import re
import secrets
from uuid import uuid4

from fastapi.testclient import TestClient

from app.config import PROJECT_ROOT, Settings, workspace_path


DATABASE_NAME = re.compile(r"vision_zero_m1_test_[0-9a-f]{12}")
EXPECTED_COLLISIONS = 85_546
EXPECTED_PROFILES = 95
DEMO_USERNAMES = ("demo_admin", "demo_manager", "demo_executor", "demo_viewer")
PROFILE_LEVELS = ("HIGH", "MEDIUM", "LOW", "UNKNOWN")
SOURCE_TABLES = (
    "collision", "location", "intersection", "person", "vehicle",
    "collision_factor", "raw_record", "data_issue", "import_batch",
)


class DemoSeedError(ValueError):
    """不包含账号、配置值或驱动信息的安全错误码。"""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _validate_database_name(database: str) -> None:
    if not isinstance(database, str) or not DATABASE_NAME.fullmatch(database):
        raise DemoSeedError("DATABASE_NOT_ALLOWED")


def _maintenance_module():
    try:
        return importlib.import_module("app.maintenance")
    except ImportError:
        raise DemoSeedError("MAINTENANCE_HELPER_UNAVAILABLE") from None


def _verified_paths(database: str) -> tuple[Path, Path, Path]:
    try:
        restore_file = workspace_path(
            PROJECT_ROOT / ".m7-work" / "restores" / database / "verification.json"
        )
        config_file = workspace_path(
            PROJECT_ROOT / ".m1-work" / "model" / f"{database}.env"
        )
        output_dir = workspace_path(
            PROJECT_ROOT / ".m8-work" / "demo" / database
        )
    except (OSError, ValueError):
        raise DemoSeedError("WORKSPACE_PATH_INVALID") from None
    return restore_file, config_file, output_dir


def _require_restore_verification(path: Path, database: str) -> None:
    try:
        verification = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise DemoSeedError("RESTORE_VERIFICATION_MISSING") from None
    if (not isinstance(verification, dict)
            or verification.get("status") != "completed"
            or verification.get("database") != database):
        raise DemoSeedError("RESTORE_VERIFICATION_MISMATCH")


def _validate_runtime(maintenance, database: str) -> None:
    try:
        settings = Settings()
        if settings.database_name != database:
            raise ValueError
        for migration, worker in ((False, False), (True, False), (False, True)):
            url = settings.connection_url(migration=migration, worker=worker)
            if url.database != database:
                raise ValueError
        settings.signing_key()
        maintenance.assert_local_container(maintenance.root_values())
    except Exception:
        raise DemoSeedError("CONFIGURATION_OR_CONTAINER_INVALID") from None


def _source_profile_snapshot(connection) -> dict:
    source_counts = {}
    for table in SOURCE_TABLES:
        source_counts[table] = int(
            connection.execute(f"SELECT count(*) FROM public.{table}").fetchone()[0]
        )
    revision = connection.execute(
        "SELECT revision FROM public.dataset_state WHERE state_id=1"
    ).fetchone()[0]
    profile_count = int(
        connection.execute("SELECT count(*) FROM public.risk_profile").fetchone()[0]
    )
    profile_counts = {level: 0 for level in PROFILE_LEVELS}
    for level, count in connection.execute(
        "SELECT risk_level,count(*) FROM public.v_risk_profile GROUP BY risk_level"
    ).fetchall():
        if level in profile_counts:
            profile_counts[level] = int(count)
    return {
        "source_facts": {
            "dataset_revision": int(revision),
            "table_counts": source_counts,
        },
        "profile_count": profile_count,
        "profile_counts": profile_counts,
    }


def _inspect_target(maintenance, database: str) -> dict:
    with maintenance.admin_connect(database) as connection:
        connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        snapshot = _source_profile_snapshot(connection)
        task_count = int(
            connection.execute("SELECT count(*) FROM public.governance_task").fetchone()[0]
        )
        demo_user_count = int(connection.execute(
            "SELECT count(*) FROM public.app_user WHERE lower(username)=ANY(%s)",
            (list(DEMO_USERNAMES),),
        ).fetchone()[0])
        high_profiles = [int(row[0]) for row in connection.execute("""
            SELECT p.profile_id
            FROM public.risk_profile p
            JOIN public.v_risk_profile v ON v.profile_id=p.profile_id
            JOIN public.risk_run r ON r.run_id=p.run_id
            JOIN public.intersection i ON i.intersection_id=p.intersection_id
            WHERE v.risk_level='HIGH' AND r.status='SUCCEEDED'
              AND i.status='CONFIRMED' AND i.is_active
            ORDER BY p.profile_id DESC
        """).fetchall()]
        publishable_high_profiles = [int(row[0]) for row in connection.execute("""
            SELECT p.profile_id
            FROM public.risk_profile p
            JOIN public.v_risk_profile v ON v.profile_id=p.profile_id
            JOIN public.risk_run r ON r.run_id=p.run_id
            JOIN public.intersection i ON i.intersection_id=p.intersection_id
            WHERE v.risk_level='HIGH' AND p.incomplete_casualty_collision_count=0
              AND r.status='SUCCEEDED' AND i.status='CONFIRMED' AND i.is_active
            ORDER BY p.profile_id DESC
        """).fetchall()]
    return {
        **snapshot,
        "task_count": task_count,
        "demo_user_count": demo_user_count,
        "high_profiles": high_profiles,
        "publishable_high_profiles": publishable_high_profiles,
    }


def _assert_seedable(state: dict) -> None:
    if state["demo_user_count"]:
        raise DemoSeedError("DEMO_ACCOUNTS_ALREADY_EXIST")
    if state["task_count"]:
        raise DemoSeedError("TARGET_ALREADY_HAS_TASKS")
    if (state["source_facts"]["table_counts"].get("collision") != EXPECTED_COLLISIONS
            or state["profile_count"] != EXPECTED_PROFILES):
        raise DemoSeedError("RESTORED_DATASET_FACTS_MISMATCH")
    if (len(state["high_profiles"]) < 1
            or len(state["publishable_high_profiles"]) < 4):
        raise DemoSeedError("INSUFFICIENT_ELIGIBLE_HIGH_PROFILES")


def _write_json_exclusive(maintenance, path: Path, value: dict) -> None:
    maintenance.write_json(path, value)
    if path.name == "credentials.json" and os.name != "nt":
        path.chmod(0o600)


def _response_data(response, expected_status: int, error_code: str) -> dict:
    if response.status_code != expected_status:
        raise DemoSeedError(error_code)
    try:
        payload = response.json()
        data = payload["data"]
    except (ValueError, TypeError, KeyError):
        raise DemoSeedError(error_code) from None
    if not isinstance(data, dict):
        raise DemoSeedError(error_code)
    return data


def _login(client, username: str, password: str) -> dict:
    data = _response_data(
        client.post("/api/v1/auth/login", json={"username": username, "password": password}),
        200,
        "DEMO_LOGIN_FAILED",
    )
    token = data.get("access_token")
    if not isinstance(token, str) or not token:
        raise DemoSeedError("DEMO_LOGIN_FAILED")
    return {"Authorization": "Bearer " + token}


def _task_action(client, headers: dict, task_id: str, version: int, endpoint: str,
                 note: str, **extra) -> dict:
    body = {
        "request_id": str(uuid4()),
        "expected_version": version,
        "note": "课程模拟：" + note,
        **extra,
    }
    return _response_data(
        client.post(f"/api/v1/governance-tasks/{task_id}/{endpoint}", headers=headers, json=body),
        200,
        "DEMO_TASK_TRANSITION_FAILED",
    )


def _create_task(client, manager_headers: dict, executor_headers: dict,
                 admin_headers: dict, executor_id: str, profile_id: int,
                 target_status: str, measure_type: str, scenario_title: str,
                 progress: dict) -> dict:
    description = "课程模拟工单，仅用于课堂演示，不代表真实施工指令或已批准的工程措施。"
    payload = {
        "request_id": str(uuid4()),
        "profile_id": str(profile_id),
        "title": f"课程模拟：{scenario_title}",
        "description": description,
        "measure_type": measure_type,
        "priority": "HIGH",
        "radius_m": 50,
        "rationale": "课程模拟，不将风险画像解释为因果结论或真实设施缺陷。",
    }
    task = _response_data(
        client.post("/api/v1/governance-tasks", headers=manager_headers, json=payload),
        201,
        "DEMO_TASK_CREATE_FAILED",
    )
    task_id = str(task["task_id"])
    version = int(task["version"])
    item = {"task_id": task_id, "status": "DRAFT"}
    progress["task_items"].append(item)
    status = task.get("status")
    expected_status = "DRAFT"
    if status != expected_status:
        raise DemoSeedError("DEMO_TASK_CREATE_FAILED")

    if target_status == "DRAFT":
        return {"task_id": task_id, "status": target_status}
    if target_status == "CANCELLED":
        result = _task_action(client, manager_headers, task_id, version, "cancel", "取消课程模拟草稿")
        item["status"] = str(result.get("status"))
        if result.get("status") != target_status:
            raise DemoSeedError("DEMO_TASK_TRANSITION_FAILED")
        return item

    result = _task_action(
        client, manager_headers, task_id, version, "publish", "发布课程模拟任务",
        assignee_id=executor_id,
    )
    version = int(result["version"])
    item["status"] = str(result.get("status"))
    if result.get("status") != "OPEN":
        raise DemoSeedError("DEMO_TASK_TRANSITION_FAILED")
    if target_status == "OPEN":
        return item

    result = _task_action(
        client, executor_headers, task_id, version, "start", "执行人员开始模拟检查",
    )
    version = int(result["version"])
    item["status"] = str(result.get("status"))
    if result.get("status") != "IN_PROGRESS":
        raise DemoSeedError("DEMO_TASK_TRANSITION_FAILED")
    if target_status == "IN_PROGRESS":
        return item

    result = _task_action(
        client, executor_headers, task_id, version, "progress", "记录模拟检查进展",
    )
    version = int(result["version"])
    item["status"] = str(result.get("status"))
    if result.get("status") != "IN_PROGRESS":
        raise DemoSeedError("DEMO_TASK_TRANSITION_FAILED")
    result = _task_action(
        client, executor_headers, task_id, version, "submit", "提交模拟检查结果等待复核",
    )
    version = int(result["version"])
    item["status"] = str(result.get("status"))
    if result.get("status") != "PENDING_REVIEW":
        raise DemoSeedError("DEMO_TASK_TRANSITION_FAILED")
    if target_status == "PENDING_REVIEW":
        return item

    result = _task_action(
        client, admin_headers, task_id, version, "review", "管理员完成独立复核",
        decision="APPROVE",
    )
    item["status"] = str(result.get("status"))
    if result.get("status") != "COMPLETED":
        raise DemoSeedError("DEMO_TASK_REVIEW_FAILED")
    return item


def _run_demo(maintenance, database: str, credentials: dict, profile_ids: dict,
              progress: dict) -> dict:
    from app.auth import password_hasher
    from app.main import app

    accounts = {account["username"]: account for account in credentials["accounts"]}
    admin_password = accounts["demo_admin"]["password"]
    admin_hash = password_hasher.hash(admin_password)
    with maintenance.admin_connect(database) as connection:
        admin_id = connection.execute("""
            INSERT INTO public.app_user (username,password_hash,display_name,role_id)
            VALUES (%s,%s,%s,1) RETURNING user_id
        """, ("demo_admin", admin_hash, "课程模拟管理员")).fetchone()[0]
    progress["created_user_count"] = 1

    task_items = progress["task_items"]
    disabled_count = 0
    with TestClient(app) as client:
        admin_headers = _login(client, "demo_admin", admin_password)
        user_ids = {"demo_admin": str(admin_id)}
        role_by_name = {
            "demo_manager": "MANAGER",
            "demo_executor": "MANAGER",
            "demo_viewer": "VIEWER",
        }
        for username, role in role_by_name.items():
            account = accounts[username]
            data = _response_data(client.post("/api/v1/users", headers=admin_headers, json={
                "username": username,
                "display_name": "课程模拟管理人员" if username == "demo_manager" else
                                "课程模拟执行人员" if username == "demo_executor" else
                                "课程模拟只读人员",
                "role": role,
                "password": account["password"],
            }), 201, "DEMO_ACCOUNT_CREATE_FAILED")
            user_ids[username] = str(data["user_id"])
            progress["created_user_count"] = len(user_ids)

        manager_headers = _login(client, "demo_manager", accounts["demo_manager"]["password"])
        executor_headers = _login(client, "demo_executor", accounts["demo_executor"]["password"])
        _login(client, "demo_viewer", accounts["demo_viewer"]["password"])
        executor_id = user_ids["demo_executor"]

        cases = (
            ("DRAFT", "FIELD_SURVEY", profile_ids["draft"], "现场调查草稿"),
            ("OPEN", "SIGNAL_REVIEW", profile_ids["open"], "信号配时复核"),
            ("IN_PROGRESS", "PEDESTRIAN_FACILITY_REVIEW", profile_ids["in_progress"], "行人设施核查"),
            ("PENDING_REVIEW", "MARKING_MAINTENANCE", profile_ids["pending_review"], "标线维护检查"),
            ("COMPLETED", "SIGNAL_REVIEW", profile_ids["completed"], "信号配时复核"),
            ("CANCELLED", "FIELD_SURVEY", profile_ids["cancelled"], "临时现场调查"),
        )
        for target_status, measure_type, profile_id, scenario_title in cases:
            item = _create_task(
                client, manager_headers, executor_headers, admin_headers, executor_id,
                profile_id, target_status, measure_type, scenario_title, progress,
            )

        # 仅通过管理员API停用恢复库中的旧账户，触发版本递增并保留审计历史。
        page = 1
        page_size = 100
        total = None
        while total is None or (page - 1) * page_size < total:
            users = _response_data(client.get(
                "/api/v1/users", headers=admin_headers,
                params={"page": page, "page_size": page_size},
            ), 200, "RESTORED_ACCOUNT_READ_FAILED")
            total = int(users["total"])
            for user in users["items"]:
                user_id = str(user["user_id"])
                if user_id in user_ids.values() or not user["is_active"]:
                    continue
                _response_data(client.patch(
                    f"/api/v1/users/{user_id}", headers=admin_headers,
                    json={"expected_version": int(user["version"]), "is_active": False},
                ), 200, "RESTORED_ACCOUNT_DISABLE_FAILED")
                disabled_count += 1
                progress["disabled_count"] = disabled_count
            page += 1

    return {
        "task_items": task_items,
        "user_ids": user_ids,
        "disabled_count": disabled_count,
    }


def _verify_result(maintenance, database: str, run: dict) -> dict:
    task_ids = [int(item["task_id"]) for item in run["task_items"]]
    with maintenance.admin_connect(database) as connection:
        connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        rows = connection.execute("""
            SELECT task_id,status,is_simulated,assignee_id,created_by
            FROM public.governance_task WHERE task_id=ANY(%s)
            ORDER BY task_id
        """, (task_ids,)).fetchall()
        histories = connection.execute("""
            SELECT task_id,event_type,actor_id FROM public.task_history
            WHERE task_id=ANY(%s) ORDER BY task_id,sequence_no
        """, (task_ids,)).fetchall()
        active_users = int(connection.execute(
            "SELECT count(*) FROM public.app_user WHERE is_active"
        ).fetchone()[0])
    if len(rows) != 6:
        raise DemoSeedError("DEMO_TASK_COUNT_MISMATCH")

    row_by_id = {int(row[0]): row for row in rows}
    events_by_id = {task_id: [] for task_id in task_ids}
    for task_id, event_type, actor_id in histories:
        events_by_id[int(task_id)].append((event_type, int(actor_id)))
    expected_events = {
        "DRAFT": ["CREATE"],
        "OPEN": ["CREATE", "PUBLISH"],
        "IN_PROGRESS": ["CREATE", "PUBLISH", "START"],
        "PENDING_REVIEW": ["CREATE", "PUBLISH", "START", "PROGRESS", "SUBMIT"],
        "COMPLETED": ["CREATE", "PUBLISH", "START", "PROGRESS", "SUBMIT", "APPROVE"],
        "CANCELLED": ["CREATE", "CANCEL"],
    }
    public_items = []
    status_counts = {status: 0 for status in expected_events}
    for item in run["task_items"]:
        task_id = int(item["task_id"])
        row = row_by_id.get(task_id)
        events = events_by_id.get(task_id, [])
        if (row is None or row[1] != item["status"] or not row[2]
                or [event[0] for event in events] != expected_events[item["status"]]):
            raise DemoSeedError("DEMO_TASK_HISTORY_MISMATCH")
        if item["status"] == "COMPLETED":
            executor = row[3]
            submit_actor = next(actor for event, actor in events if event == "SUBMIT")
            reviewer = next(actor for event, actor in events if event == "APPROVE")
            if executor is None or int(executor) != submit_actor or int(executor) == reviewer:
                raise DemoSeedError("DEMO_REVIEWER_MUST_DIFFER_FROM_EXECUTOR")
        status_counts[item["status"]] += 1
        public_items.append({
            "task_id": str(task_id),
            "status": item["status"],
            "history_count": len(events),
        })
    if status_counts != {status: 1 for status in expected_events}:
        raise DemoSeedError("DEMO_TASK_STATUS_MISMATCH")
    if active_users != 4:
        raise DemoSeedError("RESTORED_ACCOUNTS_REMAIN_ACTIVE")
    return {
        "items": public_items,
        "status_counts": status_counts,
        "active_account_count": active_users,
    }


def _make_summary(database: str, *, status: str, before: dict, after: dict | None,
                  public_tasks: dict | None, created_user_count: int,
                  disabled_account_count: int, error_code: str | None = None,
                  phase: str | None = None) -> dict:
    summary = {
        "format": "vision-zero-demo-summary-v1",
        "status": status,
        "database": database,
        "simulated": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_facts_before": before["source_facts"],
        "source_facts_after": after["source_facts"] if after else None,
        "profile_counts_before": before["profile_counts"],
        "profile_counts_after": after["profile_counts"] if after else None,
        "profile_count_before": before["profile_count"],
        "profile_count_after": after["profile_count"] if after else None,
        "accounts": {
            "created_count": created_user_count,
            "restored_accounts_disabled": disabled_account_count,
            "active_account_count": public_tasks["active_account_count"] if public_tasks else None,
        },
        "tasks": {
            "count": len(public_tasks["items"]) if public_tasks else 0,
            "status_counts": public_tasks["status_counts"] if public_tasks else {
                status: 0 for status in ("DRAFT", "OPEN", "IN_PROGRESS", "PENDING_REVIEW", "COMPLETED", "CANCELLED")
            },
            "items": public_tasks["items"] if public_tasks else [],
        },
    }
    if error_code:
        summary["error_code"] = error_code
    if phase:
        summary["failed_phase"] = phase
    return summary


def seed_demo(database: str) -> dict:
    """创建四个演示账户和六个课程模拟工单，只返回不含凭据的摘要。"""
    _validate_database_name(database)
    restore_file, config_file, output_dir = _verified_paths(database)
    if output_dir.exists():
        raise DemoSeedError("DEMO_TARGET_ALREADY_EXISTS")
    _require_restore_verification(restore_file, database)
    if not config_file.is_file():
        raise DemoSeedError("TARGET_CONFIGURATION_MISSING")

    maintenance = _maintenance_module()
    try:
        with maintenance.isolated_environment(config_file):
            _validate_runtime(maintenance, database)
            try:
                before = _inspect_target(maintenance, database)
            except DemoSeedError:
                raise
            except Exception:
                raise DemoSeedError("TARGET_DATABASE_PREFLIGHT_FAILED") from None
            _assert_seedable(before)

            try:
                output_dir.parent.mkdir(parents=True, exist_ok=True)
                output_dir.mkdir(exist_ok=False)
            except FileExistsError:
                raise DemoSeedError("DEMO_TARGET_ALREADY_EXISTS") from None
            except OSError:
                raise DemoSeedError("DEMO_OUTPUT_DIRECTORY_FAILED") from None
            try:
                maintenance.protect_directory(output_dir)
            except Exception:
                raise DemoSeedError("DEMO_OUTPUT_PROTECTION_FAILED") from None

            credentials = {
                "format": "vision-zero-demo-credentials-v1",
                "database": database,
                "accounts": [
                    {"username": username, "role": role, "password": secrets.token_urlsafe(32)}
                    for username, role in (
                        ("demo_admin", "ADMIN"),
                        ("demo_manager", "MANAGER"),
                        ("demo_executor", "MANAGER"),
                        ("demo_viewer", "VIEWER"),
                    )
                ],
            }
            phase = "credentials"
            progress = {"created_user_count": 0, "disabled_count": 0}
            progress["task_items"] = []
            created_user_count = 0
            disabled_count = 0
            run = None
            after = None
            public_tasks = None
            error_code = None
            try:
                _write_json_exclusive(maintenance, output_dir / "credentials.json", credentials)
                phase = "accounts_and_tasks"
                run = _run_demo(maintenance, database, credentials, _assign_profiles(before), progress)
                created_user_count = progress["created_user_count"]
                disabled_count = run["disabled_count"]
                phase = "verification"
                public_tasks = _verify_result(maintenance, database, run)
                with maintenance.admin_connect(database) as connection:
                    connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                    after = _source_profile_snapshot(connection)
                if (before["source_facts"] != after["source_facts"]
                        or before["profile_counts"] != after["profile_counts"]
                        or before["profile_count"] != after["profile_count"]):
                    raise DemoSeedError("SOURCE_OR_PROFILE_FACTS_CHANGED")
            except DemoSeedError as exc:
                error_code = exc.code
            except Exception:
                error_code = "DEMO_INITIALIZATION_FAILED"

            if error_code is not None:
                created_user_count = progress["created_user_count"]
                disabled_count = progress["disabled_count"]
                if after is None and created_user_count:
                    try:
                        with maintenance.admin_connect(database) as connection:
                            connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                            after = _source_profile_snapshot(connection)
                    except Exception:
                        after = None
                if public_tasks is None and progress["task_items"]:
                    partial_counts = {
                        state: sum(item["status"] == state for item in progress["task_items"])
                        for state in ("DRAFT", "OPEN", "IN_PROGRESS", "PENDING_REVIEW", "COMPLETED", "CANCELLED")
                    }
                    public_tasks = {
                        "items": [dict(item) for item in progress["task_items"]],
                        "status_counts": partial_counts,
                        "active_account_count": None,
                    }

            summary = _make_summary(
                database,
                status="completed" if error_code is None else "failed",
                before=before,
                after=after,
                public_tasks=public_tasks,
                created_user_count=created_user_count,
                disabled_account_count=disabled_count,
                error_code=error_code,
                phase=None if error_code is None else phase,
            )
            try:
                _write_json_exclusive(maintenance, output_dir / "demo-summary.json", summary)
            except Exception:
                raise DemoSeedError("DEMO_SUMMARY_WRITE_FAILED") from None
            return summary
    except DemoSeedError:
        raise
    except Exception:
        raise DemoSeedError("DEMO_PREFLIGHT_FAILED") from None


def _assign_profiles(state: dict) -> dict:
    publishable = state["publishable_high_profiles"]
    high = state["high_profiles"]
    return {
        "draft": high[0],
        "open": publishable[0],
        "in_progress": publishable[1],
        "pending_review": publishable[2],
        "completed": publishable[3],
        "cancelled": high[1] if len(high) > 1 else high[0],
    }
