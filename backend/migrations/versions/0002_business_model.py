"""M1固定DDL、完整性及读取视图；不包含M2导入或M5工单动作。"""

from pathlib import Path
import re

from alembic import op
from sqlalchemy import text

from app.config import Settings

revision = "0002_business_model"
down_revision = "0001_environment"
branch_labels = None
depends_on = None

TABLES = "borough role app_user import_batch raw_record location intersection location_assignment collision person vehicle_type vehicle contributing_factor collision_factor casualty_stat risk_rule risk_run risk_profile governance_task task_history data_issue audit_log dataset_state".split()
FUNCTIONS = "vz_append_only vz_raw_guard vz_rule_guard vz_run_guard vz_profile_guard vz_intersection_guard vz_location_guard vz_require_casualty vz_source_guard vz_issue_batch_guard vz_user_guard vz_task_basis_guard".split()


def upgrade():
    directory = Path(__file__).resolve().parents[1] / "sql"
    for name in ("0002_tables.sql", "0002_integrity.sql", "0002_views.sql"):
        op.execute(text((directory / name).read_text(encoding="utf-8")))
    settings = Settings()
    app_role = settings.connection_url().username
    worker_role = settings.connection_url(worker=True).username
    quote = op.get_bind().dialect.identifier_preparer.quote
    app, worker = quote(app_role), quote(worker_role)
    for table in TABLES + ["alembic_version", "v_collision_base", "v_risk_profile", "v_governance_task"]:
        op.execute(f"REVOKE ALL ON TABLE public.{table} FROM PUBLIC")
        op.execute(f"GRANT SELECT ON TABLE public.{table} TO {app}")
        if table == "alembic_version":
            op.execute(f"GRANT SELECT ON TABLE public.{table} TO {worker}")
    op.execute(f"GRANT INSERT, UPDATE ON public.app_user TO {app}")
    op.execute(f"GRANT INSERT ON public.audit_log TO {app}")
    op.execute(f"GRANT USAGE ON SEQUENCE public.app_user_user_id_seq, public.audit_log_audit_id_seq TO {app}")
    for function in FUNCTIONS:
        op.execute(f"REVOKE ALL ON FUNCTION public.{function}() FROM PUBLIC")
    op.execute("ALTER DEFAULT PRIVILEGES REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC")


def downgrade():
    # 业务回退仅在随机验证库执行；开发库含账户后禁止破坏性降级。
    name = op.get_bind().scalar(text("SELECT current_database()"))
    if not re.fullmatch(r"vision_zero_m1_test_[0-9a-f]{12}", name):
        raise RuntimeError("业务回退仅允许专用随机验证库；开发库请保留历史并使用前向迁移。")
    for view in ("v_governance_task", "v_risk_profile", "v_collision_base"):
        op.execute(f"DROP VIEW public.{view}")
    for function in FUNCTIONS:
        op.execute(f"DROP FUNCTION public.{function}() CASCADE")
    # 固定依赖顺序，与模型未来新增字段无关。
    for table in "task_history governance_task data_issue audit_log risk_profile risk_run person vehicle collision_factor casualty_stat collision location_assignment raw_record import_batch intersection risk_rule location vehicle_type contributing_factor app_user dataset_state role borough".split():
        op.execute(f"DROP TABLE public.{table}")
