"""M3交叉口工作流最小权限和米制查询索引。"""

from pathlib import Path
import re

from alembic import op
import sqlalchemy as sa

from app.config import Settings

revision = "0005_intersection_workflow"
down_revision = "0004_import_role_guard"
branch_labels = None
depends_on = None


def app_role():
    name = Settings().connection_url().username
    return op.get_bind().dialect.identifier_preparer.quote(name)


def upgrade():
    source = Path(__file__).resolve().parents[1] / "sql/0005_intersection_workflow.sql"
    op.execute(sa.text(source.read_text(encoding="utf-8")))
    for name in ("vz_intersection_state_guard", "vz_assignment_guard", "vz_m3_revision_guard"):
        op.execute(f"REVOKE ALL ON FUNCTION public.{name}() FROM PUBLIC")
    role = app_role()
    op.execute(f"GRANT INSERT ON public.intersection, public.location_assignment TO {role}")
    op.execute(f"GRANT UPDATE (status,confirmation_note,confirmed_by,confirmed_at,updated_at,version) ON public.intersection TO {role}")
    op.execute(f"GRANT UPDATE (intersection_id,match_status,match_method,algorithm_version,distance_m,evidence,reviewed_by,reviewed_at,updated_at,version) ON public.location_assignment TO {role}")
    op.execute(f"GRANT UPDATE (revision,updated_at,last_change_note) ON public.dataset_state TO {role}")
    op.execute(f"GRANT USAGE ON SEQUENCE public.intersection_intersection_id_seq TO {role}")


def downgrade():
    name = op.get_bind().scalar(sa.text("SELECT current_database()"))
    if not re.fullmatch(r"vision_zero_m1_test_[0-9a-f]{12}", name):
        raise RuntimeError("M3降级只允许专用随机验证库；开发库使用前向迁移。")
    role = app_role()
    op.execute(f"REVOKE INSERT ON public.intersection, public.location_assignment FROM {role}")
    op.execute(f"REVOKE UPDATE (status,confirmation_note,confirmed_by,confirmed_at,updated_at,version) ON public.intersection FROM {role}")
    op.execute(f"REVOKE UPDATE (intersection_id,match_status,match_method,algorithm_version,distance_m,evidence,reviewed_by,reviewed_at,updated_at,version) ON public.location_assignment FROM {role}")
    op.execute(f"REVOKE UPDATE (revision,updated_at,last_change_note) ON public.dataset_state FROM {role}")
    op.execute(f"REVOKE USAGE ON SEQUENCE public.intersection_intersection_id_seq FROM {role}")
    op.execute("DROP TRIGGER trg_m3_revision ON public.dataset_state")
    op.execute("DROP FUNCTION public.vz_m3_revision_guard()")
    op.execute("DROP TRIGGER trg_assignment_guard ON public.location_assignment")
    op.execute("DROP FUNCTION public.vz_assignment_guard()")
    op.execute("DROP TRIGGER trg_intersection_state ON public.intersection")
    op.execute("DROP FUNCTION public.vz_intersection_state_guard()")
    op.execute("DROP INDEX public.ix_intersection_geography")
