-- 自定义触发器函数仅供触发器调用；不授予PUBLIC或运行账号直接执行权。
CREATE FUNCTION public.vz_append_only() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp AS $$
BEGIN
    RAISE EXCEPTION '历史和审计记录只允许追加' USING ERRCODE = '23514';
END $$;
CREATE TRIGGER trg_history_append_only BEFORE UPDATE OR DELETE ON public.task_history
    FOR EACH ROW EXECUTE FUNCTION public.vz_append_only();
CREATE TRIGGER trg_audit_append_only BEFORE UPDATE OR DELETE ON public.audit_log
    FOR EACH ROW EXECUTE FUNCTION public.vz_append_only();

CREATE FUNCTION public.vz_raw_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION '原始记录不可删除' USING ERRCODE = '23514';
    END IF;
    IF (to_jsonb(NEW) - 'validation_status') IS DISTINCT FROM (to_jsonb(OLD) - 'validation_status') THEN
        RAISE EXCEPTION '原始输入不可修改' USING ERRCODE = '23514';
    END IF;
    IF NEW.validation_status <> 'ACCEPTED' AND (
        EXISTS (SELECT 1 FROM public.collision WHERE source_record_id = OLD.raw_record_id)
        OR EXISTS (SELECT 1 FROM public.person WHERE source_record_id = OLD.raw_record_id)
        OR EXISTS (SELECT 1 FROM public.vehicle WHERE source_record_id = OLD.raw_record_id)) THEN
        RAISE EXCEPTION '已发布来源行不得重新标记为拒绝或跳过' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER trg_raw_immutable BEFORE UPDATE OR DELETE ON public.raw_record
    FOR EACH ROW EXECUTE FUNCTION public.vz_raw_guard();

CREATE FUNCTION public.vz_rule_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp AS $$
BEGIN
    IF OLD.status IN ('PUBLISHED', 'RETIRED') THEN
        IF TG_OP = 'DELETE' THEN
            RAISE EXCEPTION '已发布规则不可删除' USING ERRCODE = '23514';
        END IF;
        IF (to_jsonb(NEW) - 'status') IS DISTINCT FROM (to_jsonb(OLD) - 'status')
           OR (OLD.status = 'RETIRED' AND NEW.status <> 'RETIRED')
           OR NEW.status = 'DRAFT' THEN
            RAISE EXCEPTION '已发布规则不可改写' USING ERRCODE = '23514';
        END IF;
    END IF;
    IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER trg_rule_immutable BEFORE UPDATE OR DELETE ON public.risk_rule
    FOR EACH ROW EXECUTE FUNCTION public.vz_rule_guard();

CREATE FUNCTION public.vz_run_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp AS $$
BEGIN
    IF TG_OP <> 'INSERT' AND OLD.status = 'SUCCEEDED' THEN
        RAISE EXCEPTION '成功运行快照不可改写或删除' USING ERRCODE = '23514';
    END IF;
    IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
    IF NOT EXISTS (SELECT 1 FROM public.risk_rule WHERE rule_id = NEW.rule_id AND status = 'PUBLISHED') THEN
        RAISE EXCEPTION '计算必须使用已发布规则' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER trg_run_guard BEFORE INSERT OR UPDATE OR DELETE ON public.risk_run
    FOR EACH ROW EXECUTE FUNCTION public.vz_run_guard();

CREATE FUNCTION public.vz_profile_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp AS $$
DECLARE target_run bigint;
BEGIN
    IF TG_OP = 'INSERT' THEN target_run := NEW.run_id; ELSE target_run := OLD.run_id; END IF;
    PERFORM 1 FROM public.risk_run WHERE run_id = target_run FOR UPDATE;
    IF EXISTS (SELECT 1 FROM public.risk_run WHERE run_id = target_run AND status = 'SUCCEEDED') THEN
        RAISE EXCEPTION '成功画像不可改写或追加' USING ERRCODE = '23514';
    END IF;
    IF TG_OP = 'UPDATE' AND NEW.run_id <> OLD.run_id THEN
        RAISE EXCEPTION '画像不能移到其他运行' USING ERRCODE = '23514';
    END IF;
    IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER trg_profile_immutable BEFORE INSERT OR UPDATE OR DELETE ON public.risk_profile
    FOR EACH ROW EXECUTE FUNCTION public.vz_profile_guard();

CREATE FUNCTION public.vz_intersection_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp AS $$
BEGIN
    IF EXISTS (SELECT 1 FROM public.risk_profile p JOIN public.risk_run r USING (run_id)
               WHERE p.intersection_id = OLD.intersection_id AND r.status = 'SUCCEEDED') THEN
        IF TG_OP = 'DELETE' THEN
            RAISE EXCEPTION '已用于成功画像的交叉口不可删除' USING ERRCODE = '23514';
        END IF;
        IF ROW(NEW.intersection_code, NEW.borough_id, NEW.street_a, NEW.street_b, NEW.center_geom, NEW.status)
           IS DISTINCT FROM ROW(OLD.intersection_code, OLD.borough_id, OLD.street_a, OLD.street_b, OLD.center_geom, OLD.status) THEN
            RAISE EXCEPTION '已有成功画像的交叉口身份冻结' USING ERRCODE = '23514';
        END IF;
    END IF;
    IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER trg_intersection_identity BEFORE UPDATE OR DELETE ON public.intersection
    FOR EACH ROW EXECUTE FUNCTION public.vz_intersection_guard();

CREATE FUNCTION public.vz_location_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp AS $$
BEGIN
    IF EXISTS (SELECT 1 FROM public.collision WHERE location_id = OLD.location_id) THEN
        RAISE EXCEPTION '已引用观察地点不可覆盖或删除' USING ERRCODE = '23514';
    END IF;
    IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER trg_location_identity BEFORE UPDATE OR DELETE ON public.location
    FOR EACH ROW EXECUTE FUNCTION public.vz_location_guard();

CREATE FUNCTION public.vz_require_casualty() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp AS $$
DECLARE target_id bigint;
BEGIN
    IF TG_OP = 'DELETE' THEN target_id := OLD.collision_id; ELSE target_id := NEW.collision_id; END IF;
    IF EXISTS (SELECT 1 FROM public.collision WHERE collision_id = target_id)
       AND NOT EXISTS (SELECT 1 FROM public.casualty_stat WHERE collision_id = target_id) THEN
        RAISE EXCEPTION '正式事故必须有伤亡统计行' USING ERRCODE = '23514';
    END IF;
    IF TG_OP = 'UPDATE' AND NEW.collision_id <> OLD.collision_id
       AND EXISTS (SELECT 1 FROM public.collision WHERE collision_id = OLD.collision_id)
       AND NOT EXISTS (SELECT 1 FROM public.casualty_stat WHERE collision_id = OLD.collision_id) THEN
        RAISE EXCEPTION '原事故缺少伤亡统计行' USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER trg_collision_requires_casualty AFTER INSERT OR UPDATE ON public.collision
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.vz_require_casualty();
CREATE CONSTRAINT TRIGGER trg_casualty_required AFTER UPDATE OR DELETE ON public.casualty_stat
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.vz_require_casualty();

CREATE FUNCTION public.vz_source_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp AS $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM public.raw_record WHERE raw_record_id = NEW.source_record_id
                   AND source_kind = TG_ARGV[0] AND validation_status = 'ACCEPTED') THEN
        RAISE EXCEPTION '正式记录必须引用正确来源的已接受原始行' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER trg_collision_source BEFORE INSERT OR UPDATE ON public.collision
    FOR EACH ROW EXECUTE FUNCTION public.vz_source_guard('CRASHES');
CREATE TRIGGER trg_person_source BEFORE INSERT OR UPDATE ON public.person
    FOR EACH ROW EXECUTE FUNCTION public.vz_source_guard('PERSON');
CREATE TRIGGER trg_vehicle_source BEFORE INSERT OR UPDATE ON public.vehicle
    FOR EACH ROW EXECUTE FUNCTION public.vz_source_guard('VEHICLES');

CREATE FUNCTION public.vz_issue_batch_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp AS $$
BEGIN
    IF NEW.raw_record_id IS NOT NULL AND NOT EXISTS
       (SELECT 1 FROM public.raw_record WHERE raw_record_id = NEW.raw_record_id AND batch_id = NEW.batch_id) THEN
        RAISE EXCEPTION '问题与原始行必须属于同一批次' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER trg_issue_batch BEFORE INSERT OR UPDATE ON public.data_issue
    FOR EACH ROW EXECUTE FUNCTION public.vz_issue_batch_guard();

CREATE FUNCTION public.vz_user_guard() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public, pg_temp AS $$
BEGIN
    PERFORM pg_advisory_xact_lock(76301002);
    IF OLD.is_active AND OLD.role_id = 1 THEN
        IF TG_OP = 'DELETE' OR NOT NEW.is_active OR NEW.role_id <> 1 THEN
            IF NOT EXISTS (SELECT 1 FROM public.app_user WHERE user_id <> OLD.user_id AND is_active AND role_id = 1) THEN
                RAISE EXCEPTION '不能移除最后一个可用管理员' USING ERRCODE = '23514';
            END IF;
        END IF;
    END IF;
    IF TG_OP = 'DELETE' OR NOT NEW.is_active OR NEW.role_id <> OLD.role_id THEN
        IF EXISTS (SELECT 1 FROM public.governance_task WHERE assignee_id = OLD.user_id
                   AND deleted_at IS NULL AND status IN ('OPEN', 'IN_PROGRESS', 'PENDING_REVIEW')) THEN
            RAISE EXCEPTION '执行人仍有在办任务' USING ERRCODE = '23514';
        END IF;
    END IF;
    IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
    IF NEW.user_id <> OLD.user_id OR NEW.username <> OLD.username THEN
        RAISE EXCEPTION '账户编号和登录名不可修改' USING ERRCODE = '23514';
    END IF;
    IF ROW(NEW.password_hash, NEW.role_id, NEW.is_active) IS DISTINCT FROM ROW(OLD.password_hash, OLD.role_id, OLD.is_active) THEN
        NEW.auth_version := OLD.auth_version + 1;
    ELSIF NEW.auth_version NOT IN (OLD.auth_version, OLD.auth_version + 1) THEN
        RAISE EXCEPTION '认证版本更新无效' USING ERRCODE = '23514';
    END IF;
    NEW.version := OLD.version + 1;
    NEW.updated_at := now();
    RETURN NEW;
END $$;
CREATE TRIGGER trg_user_boundaries BEFORE UPDATE OR DELETE ON public.app_user
    FOR EACH ROW EXECUTE FUNCTION public.vz_user_guard();

CREATE FUNCTION public.vz_task_basis_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp AS $$
DECLARE incomplete_count bigint;
BEGIN
    PERFORM pg_advisory_xact_lock(76301002);
    SELECT p.incomplete_casualty_collision_count INTO incomplete_count
    FROM public.risk_profile p JOIN public.risk_run r USING (run_id)
    JOIN public.intersection i USING (intersection_id)
    WHERE p.profile_id = NEW.profile_id AND r.status = 'SUCCEEDED'
      AND i.status = 'CONFIRMED' AND (i.is_active OR TG_OP = 'UPDATE');
    IF NOT FOUND THEN
        RAISE EXCEPTION '工单必须基于成功画像和确认交叉口' USING ERRCODE = '23514';
    END IF;
    IF incomplete_count > 0 AND (NEW.status <> 'DRAFT' OR NEW.measure_type <> 'FIELD_SURVEY') THEN
        RAISE EXCEPTION 'UNKNOWN仅允许调查草稿，不得发布' USING ERRCODE = '23514';
    END IF;
    IF TG_OP = 'UPDATE' AND ROW(NEW.profile_id, NEW.assessment_scope, NEW.created_by, NEW.is_simulated)
       IS DISTINCT FROM ROW(OLD.profile_id, OLD.assessment_scope, OLD.created_by, OLD.is_simulated) THEN
        RAISE EXCEPTION '工单建立依据不可替换' USING ERRCODE = '23514';
    END IF;
    IF NEW.status IN ('OPEN', 'IN_PROGRESS', 'PENDING_REVIEW') AND NOT EXISTS
       (SELECT 1 FROM public.app_user WHERE user_id = NEW.assignee_id AND is_active AND role_id IN (1, 2)) THEN
        RAISE EXCEPTION '在办任务必须有启用的管理人员执行' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER trg_task_basis BEFORE INSERT OR UPDATE ON public.governance_task
    FOR EACH ROW EXECUTE FUNCTION public.vz_task_basis_guard();

INSERT INTO public.role (role_id, role_code, role_name) VALUES
    (1, 'ADMIN', '系统管理员'), (2, 'MANAGER', '交通管理人员'), (3, 'VIEWER', '普通查询用户');
INSERT INTO public.borough (borough_id, borough_name, display_name) VALUES
    (1, 'BRONX', '布朗克斯'), (2, 'BROOKLYN', '布鲁克林'), (3, 'MANHATTAN', '曼哈顿'),
    (4, 'QUEENS', '皇后区'), (5, 'STATEN ISLAND', '斯塔滕岛');
INSERT INTO public.dataset_state (state_id, revision, last_change_note) VALUES (1, 0, 'M1空库初始化');
INSERT INTO public.risk_rule (rule_code, version_no, rule_name, weight_collision, weight_injured,
    weight_killed, weight_vru, threshold_medium, threshold_high, status, rationale)
    VALUES ('COURSE_V1', 1, '课程初始规则', 1, 3, 10, 5, 10, 30, 'PUBLISHED', '继承原报告简化权重，仅解释历史碰撞指标');
