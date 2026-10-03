"""为前端验收创建独立随机 PostgreSQL 库；凭据只写入已忽略的本地目录。"""
import json
import os
import sys
from datetime import date
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / ".m6-work/frontend-refactor"
PRIVATE = OUTPUT / "browser-private.json"
if PRIVATE.exists():
    raise RuntimeError("本轮合成库配置已存在；拒绝覆盖，请复用配置或选择新的验收轮次。")
sys.path[:0] = [str(ROOT / "backend"), str(ROOT / "backend/tests")]
os.chdir(ROOT / "backend")
from alembic import command
from conftest import validation_config, alembic_config, connect_as, seed_user, TEST_PASSWORD
from test_m6_statistics import seed_core_fixture, seed_batch, seed_location, seed_collision, seed_task_basis, seed_task, seed_person, seed_vehicle

values = validation_config()
with patch.dict(os.environ, values):
    command.upgrade(alembic_config(), "head")
    with connect_as() as connection:
        data = seed_core_fixture(connection)
        assignee = seed_user(connection, role=2)
        accounts = {**data["users"], "assignee": assignee}
        labels = {"admin": "管理员", "manager": "治理人员", "viewer": "查询用户", "assignee": "执行人员"}
        users = {}
        for key, (user_id, username) in accounts.items():
            connection.execute("UPDATE app_user SET display_name=%s WHERE user_id=%s", ("合成验收 · " + labels[key], user_id))
            users[key] = {"user_id": str(user_id), "username": username}
        admin_id = accounts["admin"][0]
        batch = seed_batch(connection, admin_id)
        place = seed_location(connection, borough_id=3, on_street="FRONTEND SYNTHETIC BROADWAY", geom=True)
        detail_collision_id = None
        for index in range(60):
            collision_id = seed_collision(connection, batch, location_id=place, crash_date=date(2025, 2, 8 + index % 20), injured=0, killed=0)
            if index == 0:
                detail_collision_id = collision_id
                for _ in range(21):
                    seed_person(connection, batch, collision_id, 'Occupant', 'Unspecified')
                    seed_vehicle(connection, batch, collision_id)
        profile_id = seed_task_basis(connection, admin_id)
        run_id = connection.execute("SELECT run_id FROM risk_profile WHERE profile_id=%s", (profile_id,)).fetchone()[0]
        # seed_task_basis 已将批次置为成功；成功快照必须保持不可变。
        # 保留该测试辅助函数提供的原始字段，不能在成功后补写覆盖摘要。
        for status, assigned in [("COMPLETED", assignee[0]), ("OPEN", accounts["manager"][0]), ("DRAFT", None)]:
            seed_task(connection, admin_id, profile_id, status=status, assignee_id=assigned)
        counts = {name: connection.execute("SELECT count(*) FROM " + name).fetchone()[0]
                  for name in ["collision", "person", "vehicle", "governance_task", "risk_profile"]}
OUTPUT.mkdir(parents=True, exist_ok=True)
PRIVATE.write_text(json.dumps({
    "base_url": "http://127.0.0.1:5176",
    "config_file": values["VISION_ZERO_TEST_CONFIG_FILE"],
    "database": values["VISION_ZERO_DATABASE_NAME"],
    "users": users, "password": TEST_PASSWORD,
    "profile_id": str(profile_id), "run_id": str(run_id), "detail_collision_id": str(detail_collision_id),
    "synthetic_only": True,
}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
summary = {"database": values["VISION_ZERO_DATABASE_NAME"], "synthetic_only": True, "counts": counts}
(OUTPUT / "database.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
print(json.dumps(summary))
