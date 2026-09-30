"""M4风险作业最小权限；已有规则和统一评分视图沿用M1。"""

import re
from pathlib import Path

from alembic import op
from sqlalchemy import text

from app.config import Settings

revision = "0006_risk_worker"
down_revision = "0005_intersection_workflow"
branch_labels = None
depends_on = None


def roles():
    settings = Settings()
    quote = op.get_bind().dialect.identifier_preparer.quote
    return quote(settings.connection_url().username), quote(settings.connection_url(worker=True).username)


def upgrade():
    app, worker = roles()
    op.execute(f"GRANT INSERT ON public.risk_run TO {app}")
    op.execute(f"GRANT USAGE ON SEQUENCE public.risk_run_run_id_seq TO {app}")
    op.execute(f"GRANT SELECT ON public.risk_run, public.risk_rule, public.intersection, public.location_assignment TO {worker}")
    op.execute(f"GRANT UPDATE (status,started_at,finished_at,worker_token,lease_expires_at,attempt_no,error_summary,input_revision,input_manifest,coverage_summary) ON public.risk_run TO {worker}")
    op.execute(f"GRANT INSERT ON public.risk_profile, public.audit_log TO {worker}")
    op.execute(f"GRANT USAGE ON SEQUENCE public.risk_profile_profile_id_seq, public.audit_log_audit_id_seq TO {worker}")
    op.execute(text("""
        CREATE OR REPLACE FUNCTION public.vz_run_guard() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp AS $$
        BEGIN
          IF TG_OP <> 'INSERT' AND OLD.status = 'SUCCEEDED' THEN
            RAISE EXCEPTION '成功运行快照不可改写或删除' USING ERRCODE='23514';
          END IF;
          IF TG_OP='DELETE' THEN RETURN OLD; END IF;
          IF TG_OP='INSERT' AND NOT EXISTS (SELECT 1 FROM public.risk_rule
              WHERE rule_id=NEW.rule_id AND status='PUBLISHED') THEN
            RAISE EXCEPTION '计算必须使用已发布规则' USING ERRCODE='23514';
          END IF;
          IF TG_OP='UPDATE' AND NEW.rule_id <> OLD.rule_id THEN
            RAISE EXCEPTION '运行规则不可替换' USING ERRCODE='23514';
          END IF;
          RETURN NEW;
        END $$;
        CREATE FUNCTION public.vz_m4_request_guard() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp AS $$
        BEGIN
          IF current_user = current_database() || '_app' THEN
            IF NEW.status <> 'QUEUED' OR NEW.input_revision IS NOT NULL
               OR NEW.input_manifest <> '{}'::jsonb OR NEW.coverage_summary <> '{}'::jsonb
               OR NEW.started_at IS NOT NULL OR NEW.finished_at IS NOT NULL
               OR NEW.worker_token IS NOT NULL OR NEW.lease_expires_at IS NOT NULL
               OR NEW.attempt_no <> 0 OR NEW.error_summary IS NOT NULL
               OR NOT EXISTS (SELECT 1 FROM public.app_user
                 WHERE user_id=NEW.requested_by AND is_active AND role_id IN (1,2)) THEN
              RAISE EXCEPTION '风险请求必须由有效管理账户排队' USING ERRCODE='23514';
            END IF;
          END IF;
          RETURN NEW;
        END $$;
        CREATE TRIGGER trg_m4_request BEFORE INSERT ON public.risk_run
          FOR EACH ROW EXECUTE FUNCTION public.vz_m4_request_guard();
        REVOKE ALL ON FUNCTION public.vz_m4_request_guard() FROM PUBLIC;
        CREATE FUNCTION public.vz_m4_worker_guard() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp AS $$
        BEGIN
          IF current_user = current_database() || '_worker' THEN
            IF ROW(NEW.run_id,NEW.request_id,NEW.request_hash,NEW.rule_id,NEW.period_start,
                   NEW.period_end,NEW.requested_by,NEW.created_at)
               IS DISTINCT FROM ROW(OLD.run_id,OLD.request_id,OLD.request_hash,OLD.rule_id,OLD.period_start,
                   OLD.period_end,OLD.requested_by,OLD.created_at)
               OR NOT ((OLD.status='QUEUED' AND NEW.status='RUNNING')
                  OR (OLD.status='RUNNING' AND NEW.status IN ('RUNNING','SUCCEEDED','FAILED'))) THEN
              RAISE EXCEPTION 'worker不能替换风险请求或改写终态' USING ERRCODE='23514';
            END IF;
            IF NEW.status='RUNNING' AND (NEW.worker_token IS NULL OR NEW.lease_expires_at IS NULL
                OR NEW.started_at IS NULL OR NEW.finished_at IS NOT NULL) THEN
              RAISE EXCEPTION '运行必须持有有效租约' USING ERRCODE='23514';
            END IF;
            IF NEW.status IN ('SUCCEEDED','FAILED') AND (NEW.worker_token IS NOT NULL
                OR NEW.lease_expires_at IS NOT NULL OR NEW.finished_at IS NULL) THEN
              RAISE EXCEPTION '终态必须结束租约' USING ERRCODE='23514';
            END IF;
          END IF;
          RETURN NEW;
        END $$;
        CREATE TRIGGER trg_m4_worker BEFORE UPDATE ON public.risk_run
          FOR EACH ROW EXECUTE FUNCTION public.vz_m4_worker_guard();
        REVOKE ALL ON FUNCTION public.vz_m4_worker_guard() FROM PUBLIC;
    """))


def downgrade():
    name = op.get_bind().scalar(text("SELECT current_database()"))
    if not re.fullmatch(r"vision_zero_m1_test_[0-9a-f]{12}", name):
        raise RuntimeError("M4降级只允许专用随机验证库；开发库使用前向迁移。")
    app, worker = roles()
    op.execute("DROP TRIGGER trg_m4_request ON public.risk_run")
    op.execute("DROP FUNCTION public.vz_m4_request_guard()")
    op.execute("DROP TRIGGER trg_m4_worker ON public.risk_run")
    op.execute("DROP FUNCTION public.vz_m4_worker_guard()")
    source = (Path(__file__).resolve().parents[1] / "sql/0002_integrity.sql").read_text(encoding="utf-8")
    guard = source[source.index("CREATE FUNCTION public.vz_run_guard()"):source.index("CREATE TRIGGER trg_run_guard")]
    op.execute(text(guard.replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1)))
    op.execute(f"REVOKE INSERT ON public.risk_run FROM {app}")
    op.execute(f"REVOKE USAGE ON SEQUENCE public.risk_run_run_id_seq FROM {app}")
    op.execute(f"REVOKE SELECT ON public.risk_run, public.risk_rule, public.intersection, public.location_assignment FROM {worker}")
    op.execute(f"REVOKE UPDATE (status,started_at,finished_at,worker_token,lease_expires_at,attempt_no,error_summary,input_revision,input_manifest,coverage_summary) ON public.risk_run FROM {worker}")
    op.execute(f"REVOKE INSERT ON public.risk_profile, public.audit_log FROM {worker}")
    op.execute(f"REVOKE USAGE ON SEQUENCE public.risk_profile_profile_id_seq, public.audit_log_audit_id_seq FROM {worker}")
