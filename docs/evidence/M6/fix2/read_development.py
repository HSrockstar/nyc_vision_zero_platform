"""只读快照：开发库前后核对和R04范围确认；只输出聚合，不复制真实记录。"""
import json
import sys
from pathlib import Path
import psycopg
from dotenv import dotenv_values

root = Path.cwd()
output = Path(sys.argv[1])
if output.exists():
    raise RuntimeError("输出已存在，请指定新轮次文件")
values = dotenv_values(root / ".env")
queries = {
    "alembic_version": "SELECT version_num FROM alembic_version",
    "revision": "SELECT revision FROM dataset_state WHERE state_id=1",
    **{table: f"SELECT count(*) FROM {table}" for table in (
        "collision", "person", "vehicle", "location", "risk_profile", "governance_task", "task_history", "app_user")},
    "confirmed": "SELECT count(*) FROM intersection WHERE status='CONFIRMED'",
    "candidate": "SELECT count(*) FROM intersection WHERE status='CANDIDATE'",
    "rejected": "SELECT count(*) FROM intersection WHERE status='REJECTED'",
    "risk_runs_succeeded": "SELECT count(*) FROM risk_run WHERE status='SUCCEEDED'",
    "january": "SELECT count(*) FROM collision WHERE crash_date >= '2025-01-01' AND crash_date < '2025-02-01'",
    "first_week": "SELECT count(*) FROM collision WHERE crash_date >= '2025-01-01' AND crash_date < '2025-01-08'",
    "year": "SELECT count(*) FROM collision WHERE crash_date >= '2025-01-01' AND crash_date < '2026-01-01'",
}
with psycopg.connect(host="127.0.0.1", port=int(values["VISION_ZERO_DB_PORT"]),
                     dbname=values["VISION_ZERO_DATABASE_NAME"], user="postgres",
                     password=values["POSTGRES_PASSWORD"], connect_timeout=5,
                     options="-c default_transaction_read_only=on") as conn:
    conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
    result = {key: conn.execute(sql).fetchone()[0] for key, sql in queries.items()}
    result["transaction_read_only"] = conn.execute("SHOW transaction_read_only").fetchone()[0]
output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps(result, ensure_ascii=False, indent=2))
