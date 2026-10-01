"""M5治理任务受控事务和追加历史。"""

import re
from pathlib import Path

from alembic import op
from sqlalchemy import text

from app.config import Settings

revision = "0007_governance"
down_revision = "0006_risk_worker"
branch_labels = None
depends_on = None


def roles():
    settings = Settings()
    quote = op.get_bind().dialect.identifier_preparer.quote
    return quote(settings.connection_url().username), quote(settings.connection_url(worker=True).username)


def _sql_file(name):
    return Path(__file__).resolve().parents[1] / "sql" / name


def _function_signature(name):
    if name == "vz_governance_create":
        return "(bigint,bigint,uuid,text,text,text,text,text,date,date,integer,text)"
    return "(bigint,integer,text,bigint,uuid,text,jsonb)"


def upgrade():
    app, worker = roles()
    op.execute(text(_sql_file("0007_governance.sql").read_text(encoding="utf-8")))

    for table in ("governance_task", "task_history"):
        op.execute(f"REVOKE INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER ON public.{table} FROM {app}, {worker}")
    op.execute(f"GRANT SELECT ON public.governance_task, public.task_history TO {app}")
    op.execute(f"REVOKE ALL ON SEQUENCE public.governance_task_task_id_seq, public.task_history_history_id_seq FROM {app}, {worker}")

    op.execute("REVOKE ALL ON FUNCTION public.vz_task_basis_guard() FROM PUBLIC")
    for function in ("vz_governance_create", "vz_governance_change"):
        signature = _function_signature(function)
        op.execute(f"REVOKE ALL ON FUNCTION public.{function}{signature} FROM PUBLIC")
        op.execute(f"REVOKE ALL ON FUNCTION public.{function}{signature} FROM {app}, {worker}")
        op.execute(f"GRANT EXECUTE ON FUNCTION public.{function}{signature} TO {app}")


def downgrade():
    database = op.get_bind().scalar(text("SELECT current_database()"))
    if not re.fullmatch(r"vision_zero_m1_test_[0-9a-f]{12}", database):
        raise RuntimeError("M5降级只允许专用随机验证库；开发库请保留历史并使用前向迁移。")

    for function in ("vz_governance_create", "vz_governance_change"):
        signature = _function_signature(function)
        op.execute(f"DROP FUNCTION public.{function}{signature}")

    source = _sql_file("0002_integrity.sql").read_text(encoding="utf-8")
    start = source.index("CREATE FUNCTION public.vz_task_basis_guard()")
    end = source.index("CREATE TRIGGER trg_task_basis", start)
    guard = source[start:end]
    op.execute(text(guard.replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1)))

    # M1只授予SELECT，恢复其权限边界；治理相关序列不暴露给应用或worker。
    app, worker = roles()
    for table in ("governance_task", "task_history"):
        op.execute(f"REVOKE INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER ON public.{table} FROM {app}, {worker}")
