"""M2导入发布请求、重试诊断和最小运行授权；保留M1冻结迁移。"""

from pathlib import Path
import re

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from app.config import Settings

revision = "0003_import_pipeline"
down_revision = "0002_business_model"
branch_labels = None
depends_on = None


def roles():
    settings = Settings()
    quote = op.get_bind().dialect.identifier_preparer.quote
    return quote(settings.connection_url().username), quote(settings.connection_url(worker=True).username)


def upgrade():
    op.add_column("import_batch", sa.Column("publish_request_id", postgresql.UUID(as_uuid=True)))
    op.add_column("import_batch", sa.Column("publish_request_hash", sa.String(64)))
    op.add_column("import_batch", sa.Column("publish_requested_by", sa.BigInteger()))
    op.create_unique_constraint("uq_import_publish_request", "import_batch", ["publish_request_id"])
    op.create_foreign_key("fk_import_publisher", "import_batch", "app_user", ["publish_requested_by"], ["user_id"], ondelete="RESTRICT")
    op.create_check_constraint("ck_import_publish_hash", "import_batch", "publish_request_hash ~ '^[0-9a-f]{64}$'")
    op.create_check_constraint("ck_import_publish_request", "import_batch", "(publish_request_id IS NULL AND publish_request_hash IS NULL AND publish_requested_by IS NULL) OR (publish_request_id IS NOT NULL AND publish_request_hash IS NOT NULL AND publish_requested_by IS NOT NULL)")
    op.create_index("ix_import_lease", "import_batch", ["status", "lease_expires_at"])
    op.create_unique_constraint("uq_issue_diagnostic", "data_issue", ["batch_id", "raw_record_id", "issue_code", "field_name"], postgresql_nulls_not_distinct=True)
    sql = Path(__file__).resolve().parents[1] / "sql/0003_import_guard.sql"
    op.execute(sa.text(sql.read_text(encoding="utf-8")))
    op.execute("REVOKE ALL ON FUNCTION public.vz_import_guard() FROM PUBLIC")
    app, worker = roles()
    op.execute(f"GRANT INSERT ON public.import_batch TO {app}")
    op.execute(f"GRANT UPDATE (status,publish_request_id,publish_request_hash,publish_requested_by,input_manifest,error_summary,finished_at,worker_token,lease_expires_at) ON public.import_batch TO {app}")
    op.execute(f"GRANT UPDATE (status,resolution_note,resolved_by,resolved_at) ON public.data_issue TO {app}")
    for table in ("vehicle_type", "contributing_factor"):
        op.execute(f"GRANT UPDATE (display_name,is_active) ON public.{table} TO {app}")
    op.execute(f"GRANT USAGE ON SEQUENCE public.import_batch_batch_id_seq TO {app}")
    read = "import_batch raw_record location collision person vehicle_type vehicle contributing_factor collision_factor casualty_stat dataset_state data_issue borough".split()
    for table in read:
        op.execute(f"GRANT SELECT ON public.{table} TO {worker}")
    op.execute(f"GRANT SELECT (user_id,role_id,is_active) ON public.app_user TO {worker}")
    op.execute(f"GRANT SELECT (audit_id,created_at) ON public.audit_log TO {worker}")
    for table in ("collision", "person", "vehicle", "casualty_stat"):
        op.execute(f"GRANT INSERT,UPDATE ON public.{table} TO {worker}")
    for table in ("raw_record", "location", "vehicle_type", "contributing_factor", "collision_factor", "data_issue", "audit_log"):
        op.execute(f"GRANT INSERT ON public.{table} TO {worker}")
    op.execute(f"GRANT DELETE ON public.collision_factor TO {worker}")
    op.execute(f"GRANT UPDATE (validation_status) ON public.raw_record TO {worker}")
    op.execute(f"GRANT UPDATE ON public.import_batch,public.dataset_state TO {worker}")
    for table, column in (("raw_record", "raw_record_id"), ("location", "location_id"), ("vehicle_type", "vehicle_type_id"), ("contributing_factor", "factor_id"), ("data_issue", "issue_id"), ("audit_log", "audit_id")):
        op.execute(f"GRANT USAGE ON SEQUENCE public.{table}_{column}_seq TO {worker}")


def downgrade():
    name = op.get_bind().scalar(sa.text("SELECT current_database()"))
    if not re.fullmatch(r"vision_zero_m1_test_[0-9a-f]{12}", name):
        raise RuntimeError("M2降级只允许专用随机验证库；开发库采用前向迁移。")
    app, worker = roles()
    for table in "import_batch raw_record location collision person vehicle_type vehicle contributing_factor collision_factor casualty_stat dataset_state data_issue audit_log borough app_user".split():
        op.execute(f"REVOKE ALL ON public.{table} FROM {worker}")
    op.execute(f"REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM {worker}")
    op.execute(f"REVOKE SELECT (user_id,role_id,is_active) ON public.app_user FROM {worker}")
    op.execute(f"REVOKE SELECT (audit_id,created_at) ON public.audit_log FROM {worker}")
    op.execute(f"REVOKE UPDATE (validation_status) ON public.raw_record FROM {worker}")
    op.execute(f"REVOKE INSERT,UPDATE ON public.import_batch FROM {app}")
    op.execute(f"REVOKE UPDATE (status,publish_request_id,publish_request_hash,publish_requested_by,input_manifest,error_summary,finished_at,worker_token,lease_expires_at) ON public.import_batch FROM {app}")
    op.execute(f"REVOKE UPDATE (status,resolution_note,resolved_by,resolved_at) ON public.data_issue FROM {app}")
    for table in ("vehicle_type", "contributing_factor"):
        op.execute(f"REVOKE UPDATE (display_name,is_active) ON public.{table} FROM {app}")
    op.execute(f"REVOKE UPDATE ON public.data_issue,public.vehicle_type,public.contributing_factor FROM {app}")
    op.execute(f"REVOKE USAGE ON SEQUENCE public.import_batch_batch_id_seq FROM {app}")
    op.execute("DROP FUNCTION public.vz_import_guard() CASCADE")
    op.drop_constraint("uq_issue_diagnostic", "data_issue", type_="unique")
    op.drop_index("ix_import_lease", "import_batch")
    for name, kind in (("ck_import_publish_request", "check"), ("ck_import_publish_hash", "check"), ("fk_import_publisher", "foreignkey"), ("uq_import_publish_request", "unique")):
        op.drop_constraint(name, "import_batch", type_=kind)
    for name in ("publish_requested_by", "publish_request_hash", "publish_request_id"):
        op.drop_column("import_batch", name)
