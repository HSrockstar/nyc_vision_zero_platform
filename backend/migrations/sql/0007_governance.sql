-- M5允许UNKNOWN调查草稿取消为终态，同时禁止发布或改为其他措施。
CREATE OR REPLACE FUNCTION public.vz_task_basis_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
DECLARE incomplete_count bigint;
BEGIN
    PERFORM pg_advisory_xact_lock(76301002);
    SELECT p.incomplete_casualty_collision_count INTO incomplete_count
    FROM public.risk_profile p JOIN public.risk_run r USING (run_id)
    JOIN public.intersection i USING (intersection_id)
    WHERE p.profile_id = NEW.profile_id AND r.status = 'SUCCEEDED'
      AND i.status = 'CONFIRMED' AND (i.is_active OR TG_OP = 'UPDATE');
    IF NOT FOUND THEN
        RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='工单必须基于成功画像和确认交叉口';
    END IF;
    IF incomplete_count > 0 AND NEW.measure_type <> 'FIELD_SURVEY' THEN
        RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='UNKNOWN画像仅允许现场调查';
    END IF;
    IF incomplete_count > 0 AND NEW.status NOT IN ('DRAFT','CANCELLED') THEN
        RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='UNKNOWN调查草稿不能发布或进入执行流程';
    END IF;
    IF TG_OP = 'UPDATE' AND ROW(NEW.profile_id, NEW.assessment_scope, NEW.created_by, NEW.is_simulated)
       IS DISTINCT FROM ROW(OLD.profile_id, OLD.assessment_scope, OLD.created_by, OLD.is_simulated) THEN
        RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='工单建立依据不可替换';
    END IF;
    IF NEW.status IN ('OPEN', 'IN_PROGRESS', 'PENDING_REVIEW') AND NOT EXISTS
       (SELECT 1 FROM public.app_user WHERE user_id = NEW.assignee_id AND is_active AND role_id IN (1, 2)) THEN
        RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='在办任务必须有启用的管理人员执行';
    END IF;
    RETURN NEW;
END $$;


CREATE FUNCTION public.vz_governance_create(
    p_actor_id bigint,
    p_profile_id bigint,
    p_request_id uuid,
    p_request_hash text,
    p_title text,
    p_description text,
    p_measure_type text,
    p_priority text,
    p_due_date date,
    p_effective_on date,
    p_radius_m integer,
    p_rationale text
) RETURNS bigint
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
DECLARE
    v_actor_role smallint;
    v_actor_active boolean;
    v_existing_task_id bigint;
    v_existing_hash text;
    v_existing_created_by bigint;
    v_existing_profile_id bigint;
    v_incomplete_count bigint;
    v_risk_level text;
    v_latitude double precision;
    v_longitude double precision;
    v_reason text;
    v_scope jsonb;
    v_task_id bigint;
    v_task_code text;
    v_note text;
BEGIN
    PERFORM pg_advisory_xact_lock(76301002);

    IF p_actor_id IS NULL OR p_actor_id <= 0 OR p_profile_id IS NULL OR p_profile_id <= 0
       OR p_request_id IS NULL OR p_request_hash IS NULL OR p_request_hash !~ '^[0-9a-f]{64}$'
       OR p_title IS NULL OR char_length(btrim(p_title)) NOT BETWEEN 1 AND 160
       OR p_description IS NULL OR char_length(btrim(p_description)) NOT BETWEEN 1 AND 10000
       OR p_measure_type IS NULL OR p_measure_type NOT IN
          ('MARKING_MAINTENANCE','SIGNAL_REVIEW','PEDESTRIAN_FACILITY_REVIEW','FIELD_SURVEY','OTHER')
       OR p_priority IS NULL OR p_priority NOT IN ('LOW','MEDIUM','HIGH','URGENT')
       OR p_radius_m IS NULL OR p_radius_m NOT BETWEEN 1 AND 1000
       OR (p_rationale IS NOT NULL AND char_length(btrim(p_rationale)) > 2000) THEN
        RAISE EXCEPTION USING ERRCODE='P0001', MESSAGE='VZ_INVALID_INPUT';
    END IF;

    SELECT u.role_id,u.is_active INTO v_actor_role,v_actor_active
    FROM public.app_user u WHERE u.user_id=p_actor_id FOR UPDATE;
    IF NOT FOUND OR v_actor_active IS DISTINCT FROM true OR v_actor_role IS NULL OR v_actor_role NOT IN (1,2) THEN
        RAISE EXCEPTION USING ERRCODE='P0001', MESSAGE='VZ_FORBIDDEN';
    END IF;

    SELECT t.task_id,t.request_hash,t.created_by,t.profile_id
    INTO v_existing_task_id,v_existing_hash,v_existing_created_by,v_existing_profile_id
    FROM public.governance_task t WHERE t.request_id=p_request_id FOR UPDATE;
    IF FOUND THEN
        IF v_existing_hash IS DISTINCT FROM p_request_hash
           OR v_existing_created_by IS DISTINCT FROM p_actor_id
           OR v_existing_profile_id IS DISTINCT FROM p_profile_id THEN
            RAISE EXCEPTION USING ERRCODE='P0001', MESSAGE='VZ_REQUEST_CONFLICT';
        END IF;
        IF NOT EXISTS (SELECT 1 FROM public.task_history h
                       WHERE h.request_id=p_request_id AND h.task_id=v_existing_task_id
                         AND h.actor_id=p_actor_id AND h.request_hash=p_request_hash) THEN
            RAISE EXCEPTION USING ERRCODE='P0001', MESSAGE='VZ_REQUEST_CONFLICT';
        END IF;
        RETURN v_existing_task_id;
    END IF;
    IF EXISTS (SELECT 1 FROM public.task_history h WHERE h.request_id=p_request_id) THEN
        RAISE EXCEPTION USING ERRCODE='P0001', MESSAGE='VZ_REQUEST_CONFLICT';
    END IF;

    SELECT p.incomplete_casualty_collision_count,
           v.risk_level,
           ST_Y(i.center_geom),ST_X(i.center_geom)
    INTO v_incomplete_count,v_risk_level,v_latitude,v_longitude
    FROM public.risk_profile p
    JOIN public.risk_run r USING (run_id)
    JOIN public.v_risk_profile v USING (profile_id)
    JOIN public.intersection i ON i.intersection_id=p.intersection_id
    WHERE p.profile_id=p_profile_id AND r.status='SUCCEEDED'
      AND i.status='CONFIRMED' AND i.is_active
    FOR SHARE OF p,r,i;
    IF NOT FOUND THEN
        IF NOT EXISTS (SELECT 1 FROM public.risk_profile WHERE profile_id=p_profile_id) THEN
            RAISE EXCEPTION USING ERRCODE='P0001', MESSAGE='VZ_PROFILE_NOT_FOUND';
        END IF;
        RAISE EXCEPTION USING ERRCODE='P0001', MESSAGE='VZ_PROFILE_CONFLICT';
    END IF;
    IF v_risk_level='UNKNOWN' AND p_measure_type <> 'FIELD_SURVEY' THEN
        RAISE EXCEPTION USING ERRCODE='P0001', MESSAGE='VZ_UNKNOWN_REQUIRES_SURVEY';
    END IF;
    IF v_risk_level IN ('LOW','MEDIUM') AND nullif(btrim(p_rationale),'') IS NULL THEN
        RAISE EXCEPTION USING ERRCODE='P0001', MESSAGE='VZ_RATIONALE_REQUIRED';
    END IF;

    v_reason := coalesce(nullif(btrim(p_rationale),''),'基于成功画像及已确认交叉口建立模拟评价范围。');
    v_scope := jsonb_build_object(
        'center',jsonb_build_object('latitude',v_latitude,'longitude',v_longitude),
        'radius_m',p_radius_m,'selection_reason',v_reason);
    v_task_id := nextval('public.governance_task_task_id_seq'::regclass);
    v_task_code := 'GOV-' || to_char(clock_timestamp(),'YYYYMMDD') || '-' || v_task_id::text;
    v_note := coalesce(nullif(btrim(p_rationale),''),'根据成功风险画像建立模拟治理草稿。');

    INSERT INTO public.governance_task
        (task_id,task_code,request_id,request_hash,profile_id,title,description,measure_type,
         priority,status,created_by,due_date,effective_on,assessment_scope,is_simulated,version)
    VALUES
        (v_task_id,v_task_code,p_request_id,p_request_hash,p_profile_id,btrim(p_title),btrim(p_description),
         p_measure_type,p_priority,'DRAFT',p_actor_id,p_due_date,p_effective_on,v_scope,true,1);
    INSERT INTO public.task_history
        (task_id,sequence_no,request_id,request_hash,event_type,from_status,to_status,actor_id,note,changed_fields)
    VALUES
        (v_task_id,1,p_request_id,p_request_hash,'CREATE',NULL,'DRAFT',p_actor_id,v_note,
         jsonb_build_object('profile_id',p_profile_id::text,'title',btrim(p_title),
           'description',btrim(p_description),'measure_type',p_measure_type,'priority',p_priority,
           'due_date',p_due_date,'effective_on',p_effective_on,'assessment_scope',v_scope,
           'is_simulated',true));
    RETURN v_task_id;
END $$;


CREATE FUNCTION public.vz_governance_change(
    p_task_id bigint,
    p_expected_version integer,
    p_action text,
    p_actor_id bigint,
    p_request_id uuid,
    p_request_hash text,
    p_payload jsonb
) RETURNS bigint
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
DECLARE
    v_actor_role smallint;
    v_actor_active boolean;
    v_candidate_id bigint;
    v_candidate_role smallint;
    v_candidate_active boolean;
    v_locked_user_id bigint;
    v_existing_task_id bigint;
    v_existing_hash text;
    v_existing_actor_id bigint;
    v_incomplete_count bigint;
    v_task public.governance_task%ROWTYPE;
    v_from_status text;
    v_to_status text;
    v_event_type text;
    v_note text;
    v_changed_fields jsonb;
    v_is_admin boolean;
    v_is_creator boolean;
    v_is_assignee boolean;
BEGIN
    -- 此锁与认证、账户变更和画像依据触发器共用；必须先于任务行锁。
    PERFORM pg_advisory_xact_lock(76301002);

    IF p_task_id IS NULL OR p_task_id <= 0 OR p_expected_version IS NULL OR p_expected_version <= 0
       OR p_actor_id IS NULL OR p_actor_id <= 0 OR p_request_id IS NULL
       OR p_request_hash IS NULL OR p_request_hash !~ '^[0-9a-f]{64}$'
       OR jsonb_typeof(p_payload) IS DISTINCT FROM 'object'
       OR p_action IS NULL OR p_action NOT IN ('EDIT','PUBLISH','ASSIGN','START','PROGRESS','SUBMIT','REVIEW','CANCEL','DELETE_DRAFT') THEN
        RAISE EXCEPTION USING ERRCODE='P0001', MESSAGE='VZ_INVALID_INPUT';
    END IF;

    SELECT u.role_id,u.is_active INTO v_actor_role,v_actor_active
    FROM public.app_user u WHERE u.user_id=p_actor_id FOR UPDATE;
    IF NOT FOUND OR v_actor_active IS DISTINCT FROM true OR v_actor_role IS NULL OR v_actor_role NOT IN (1,2) THEN
        RAISE EXCEPTION USING ERRCODE='P0001', MESSAGE='VZ_FORBIDDEN';
    END IF;

    SELECT h.task_id,h.request_hash,h.actor_id
    INTO v_existing_task_id,v_existing_hash,v_existing_actor_id
    FROM public.task_history h WHERE h.request_id=p_request_id;
    IF FOUND THEN
        IF v_existing_hash IS DISTINCT FROM p_request_hash
           OR v_existing_actor_id IS DISTINCT FROM p_actor_id
           OR v_existing_task_id IS DISTINCT FROM p_task_id THEN
            RAISE EXCEPTION USING ERRCODE='P0001', MESSAGE='VZ_REQUEST_CONFLICT';
        END IF;
        RETURN v_existing_task_id;
    END IF;
    IF EXISTS (SELECT 1 FROM public.governance_task t WHERE t.request_id=p_request_id) THEN
        RAISE EXCEPTION USING ERRCODE='P0001', MESSAGE='VZ_REQUEST_CONFLICT';
    END IF;

    SELECT t.* INTO v_task FROM public.governance_task t
    WHERE t.task_id=p_task_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION USING ERRCODE='P0001', MESSAGE='VZ_TASK_NOT_FOUND';
    END IF;

    IF p_action IN ('PUBLISH','ASSIGN') THEN
        BEGIN
            v_candidate_id := nullif(p_payload->>'assignee_id','')::bigint;
        EXCEPTION WHEN invalid_text_representation THEN
            RAISE EXCEPTION USING ERRCODE='P0001', MESSAGE='VZ_INVALID_INPUT';
        END;
    END IF;
    FOR v_locked_user_id IN
        SELECT u.user_id FROM public.app_user u
        WHERE u.user_id IN (p_actor_id,v_task.created_by,v_task.assignee_id,v_candidate_id)
        ORDER BY u.user_id FOR UPDATE
    LOOP
        NULL;
    END LOOP;
    v_is_admin := v_actor_role=1;
    v_is_creator := v_task.created_by=p_actor_id;
    v_is_assignee := v_task.assignee_id=p_actor_id;
    v_from_status := v_task.status;
    v_to_status := v_task.status;
    v_note := nullif(btrim(p_payload->>'note'),'');
    IF v_note IS NULL THEN
        RAISE EXCEPTION USING ERRCODE='P0001', MESSAGE='VZ_INVALID_INPUT';
    END IF;

    IF v_task.version <> p_expected_version THEN
        RAISE EXCEPTION USING ERRCODE='P0001', MESSAGE='VZ_VERSION_CONFLICT';
    END IF;
    IF v_task.deleted_at IS NOT NULL OR v_task.status IN ('COMPLETED','CANCELLED') THEN
        RAISE EXCEPTION USING ERRCODE='P0001', MESSAGE='VZ_STATE_CONFLICT';
    END IF;

    IF p_action='EDIT' THEN
        IF v_task.status <> 'DRAFT' THEN
            RAISE EXCEPTION USING ERRCODE='P0001', MESSAGE='VZ_STATE_CONFLICT';
        END IF;
        IF NOT (v_is_admin OR v_is_creator) THEN
            RAISE EXCEPTION USING ERRCODE='P0001', MESSAGE='VZ_FORBIDDEN';
        END IF;
        IF EXISTS (SELECT 1 FROM jsonb_object_keys(p_payload) AS keys(key_name)
                   WHERE key_name <> ALL(ARRAY['note','title','description','measure_type','priority','due_date','effective_on']))
           OR p_payload-'note'='{}'::jsonb THEN
            RAISE EXCEPTION USING ERRCODE='P0001', MESSAGE='VZ_INVALID_INPUT';
        END IF;
        IF (p_payload?'title' AND nullif(btrim(p_payload->>'title'),'') IS NULL)
           OR (p_payload?'description' AND nullif(btrim(p_payload->>'description'),'') IS NULL)
           OR (p_payload?'measure_type' AND (p_payload->>'measure_type' IS NULL OR p_payload->>'measure_type' NOT IN
               ('MARKING_MAINTENANCE','SIGNAL_REVIEW','PEDESTRIAN_FACILITY_REVIEW','FIELD_SURVEY','OTHER')))
           OR (p_payload?'priority' AND (p_payload->>'priority' IS NULL OR p_payload->>'priority' NOT IN ('LOW','MEDIUM','HIGH','URGENT'))) THEN
            RAISE EXCEPTION USING ERRCODE='P0001', MESSAGE='VZ_INVALID_INPUT';
        END IF;
        SELECT p.incomplete_casualty_collision_count INTO v_incomplete_count
        FROM public.risk_profile p WHERE p.profile_id=v_task.profile_id;
        IF v_incomplete_count > 0 AND p_payload?'measure_type'
           AND p_payload->>'measure_type' <> 'FIELD_SURVEY' THEN
            RAISE EXCEPTION USING ERRCODE='P0001', MESSAGE='VZ_UNKNOWN_REQUIRES_SURVEY';
        END IF;
        v_event_type := 'EDIT';
    ELSIF p_action='PUBLISH' THEN
        IF v_task.status <> 'DRAFT' THEN
            RAISE EXCEPTION USING ERRCODE='P0001', MESSAGE='VZ_STATE_CONFLICT';
        END IF;
        IF NOT (v_is_admin OR v_is_creator) THEN
            RAISE EXCEPTION USING ERRCODE='P0001', MESSAGE='VZ_FORBIDDEN';
        END IF;
        IF EXISTS (SELECT 1 FROM jsonb_object_keys(p_payload) AS keys(key_name)
                   WHERE key_name <> ALL(ARRAY['note','assignee_id']))
           OR v_candidate_id IS NULL THEN
            RAISE EXCEPTION USING ERRCODE='P0001', MESSAGE='VZ_INVALID_INPUT';
        END IF;
        IF EXISTS (SELECT 1 FROM public.risk_profile p
                   WHERE p.profile_id=v_task.profile_id AND p.incomplete_casualty_collision_count>0) THEN
            RAISE EXCEPTION USING ERRCODE='P0001', MESSAGE='VZ_STATE_CONFLICT';
        END IF;
        SELECT u.role_id,u.is_active INTO v_candidate_role,v_candidate_active
        FROM public.app_user u WHERE u.user_id=v_candidate_id;
        IF NOT FOUND OR v_candidate_active IS DISTINCT FROM true OR v_candidate_role NOT IN (1,2) THEN
            RAISE EXCEPTION USING ERRCODE='P0001', MESSAGE='VZ_ASSIGNEE_INVALID';
        END IF;
        v_to_status := 'OPEN';
        v_event_type := 'PUBLISH';
    ELSIF p_action='ASSIGN' THEN
        IF v_task.status <> 'OPEN' THEN
            RAISE EXCEPTION USING ERRCODE='P0001', MESSAGE='VZ_STATE_CONFLICT';
        END IF;
        IF NOT (v_is_admin OR v_is_creator) THEN
            RAISE EXCEPTION USING ERRCODE='P0001', MESSAGE='VZ_FORBIDDEN';
        END IF;
        IF EXISTS (SELECT 1 FROM jsonb_object_keys(p_payload) AS keys(key_name)
                   WHERE key_name <> ALL(ARRAY['note','assignee_id']))
           OR v_candidate_id IS NULL THEN
            RAISE EXCEPTION USING ERRCODE='P0001', MESSAGE='VZ_INVALID_INPUT';
        END IF;
        SELECT u.role_id,u.is_active INTO v_candidate_role,v_candidate_active
        FROM public.app_user u WHERE u.user_id=v_candidate_id;
        IF NOT FOUND OR v_candidate_active IS DISTINCT FROM true OR v_candidate_role NOT IN (1,2) THEN
            RAISE EXCEPTION USING ERRCODE='P0001', MESSAGE='VZ_ASSIGNEE_INVALID';
        END IF;
        v_event_type := 'ASSIGN';
    ELSIF p_action='START' THEN
        IF EXISTS (SELECT 1 FROM jsonb_object_keys(p_payload) AS keys(key_name) WHERE key_name <> 'note') THEN
            RAISE EXCEPTION USING ERRCODE='P0001', MESSAGE='VZ_INVALID_INPUT';
        END IF;
        IF v_task.status <> 'OPEN' THEN
            RAISE EXCEPTION USING ERRCODE='P0001', MESSAGE='VZ_STATE_CONFLICT';
        END IF;
        IF NOT v_is_assignee THEN
            RAISE EXCEPTION USING ERRCODE='P0001', MESSAGE='VZ_FORBIDDEN';
        END IF;
        v_to_status := 'IN_PROGRESS';
        v_event_type := 'START';
    ELSIF p_action='PROGRESS' THEN
        IF EXISTS (SELECT 1 FROM jsonb_object_keys(p_payload) AS keys(key_name) WHERE key_name <> 'note') THEN
            RAISE EXCEPTION USING ERRCODE='P0001', MESSAGE='VZ_INVALID_INPUT';
        END IF;
        IF v_task.status <> 'IN_PROGRESS' THEN
            RAISE EXCEPTION USING ERRCODE='P0001', MESSAGE='VZ_STATE_CONFLICT';
        END IF;
        IF NOT v_is_assignee THEN
            RAISE EXCEPTION USING ERRCODE='P0001', MESSAGE='VZ_FORBIDDEN';
        END IF;
        v_event_type := 'PROGRESS';
    ELSIF p_action='SUBMIT' THEN
        IF EXISTS (SELECT 1 FROM jsonb_object_keys(p_payload) AS keys(key_name) WHERE key_name <> 'note') THEN
            RAISE EXCEPTION USING ERRCODE='P0001', MESSAGE='VZ_INVALID_INPUT';
        END IF;
        IF v_task.status <> 'IN_PROGRESS' THEN
            RAISE EXCEPTION USING ERRCODE='P0001', MESSAGE='VZ_STATE_CONFLICT';
        END IF;
        IF NOT v_is_assignee THEN
            RAISE EXCEPTION USING ERRCODE='P0001', MESSAGE='VZ_FORBIDDEN';
        END IF;
        v_to_status := 'PENDING_REVIEW';
        v_event_type := 'SUBMIT';
    ELSIF p_action='REVIEW' THEN
        IF EXISTS (SELECT 1 FROM jsonb_object_keys(p_payload) AS keys(key_name)
                   WHERE key_name <> ALL(ARRAY['note','decision']))
           OR p_payload->>'decision' IS NULL
           OR p_payload->>'decision' NOT IN ('APPROVE','REJECT') THEN
            RAISE EXCEPTION USING ERRCODE='P0001', MESSAGE='VZ_INVALID_INPUT';
        END IF;
        IF v_task.status <> 'PENDING_REVIEW' THEN
            RAISE EXCEPTION USING ERRCODE='P0001', MESSAGE='VZ_STATE_CONFLICT';
        END IF;
        IF NOT (v_is_admin OR v_is_creator) OR v_is_assignee THEN
            RAISE EXCEPTION USING ERRCODE='P0001', MESSAGE='VZ_FORBIDDEN';
        END IF;
        IF p_payload->>'decision'='APPROVE' THEN
            v_to_status := 'COMPLETED';
            v_event_type := 'APPROVE';
        ELSE
            v_to_status := 'IN_PROGRESS';
            v_event_type := 'REJECT';
        END IF;
    ELSIF p_action='CANCEL' THEN
        IF EXISTS (SELECT 1 FROM jsonb_object_keys(p_payload) AS keys(key_name) WHERE key_name <> 'note') THEN
            RAISE EXCEPTION USING ERRCODE='P0001', MESSAGE='VZ_INVALID_INPUT';
        END IF;
        IF v_task.status NOT IN ('DRAFT','OPEN','IN_PROGRESS','PENDING_REVIEW') THEN
            RAISE EXCEPTION USING ERRCODE='P0001', MESSAGE='VZ_STATE_CONFLICT';
        END IF;
        IF NOT (v_is_admin OR v_is_creator) THEN
            RAISE EXCEPTION USING ERRCODE='P0001', MESSAGE='VZ_FORBIDDEN';
        END IF;
        v_to_status := 'CANCELLED';
        v_event_type := 'CANCEL';
    ELSIF p_action='DELETE_DRAFT' THEN
        IF EXISTS (SELECT 1 FROM jsonb_object_keys(p_payload) AS keys(key_name) WHERE key_name <> 'note') THEN
            RAISE EXCEPTION USING ERRCODE='P0001', MESSAGE='VZ_INVALID_INPUT';
        END IF;
        IF v_task.status <> 'DRAFT' THEN
            RAISE EXCEPTION USING ERRCODE='P0001', MESSAGE='VZ_STATE_CONFLICT';
        END IF;
        IF NOT (v_is_admin OR v_is_creator) THEN
            RAISE EXCEPTION USING ERRCODE='P0001', MESSAGE='VZ_FORBIDDEN';
        END IF;
        v_event_type := 'DELETE_DRAFT';
    END IF;

    v_changed_fields := p_payload-'note';
    UPDATE public.governance_task t SET
        title = CASE WHEN p_action='EDIT' AND p_payload?'title' THEN btrim(p_payload->>'title') ELSE t.title END,
        description = CASE WHEN p_action='EDIT' AND p_payload?'description' THEN btrim(p_payload->>'description') ELSE t.description END,
        measure_type = CASE WHEN p_action='EDIT' AND p_payload?'measure_type' THEN p_payload->>'measure_type' ELSE t.measure_type END,
        priority = CASE WHEN p_action='EDIT' AND p_payload?'priority' THEN p_payload->>'priority' ELSE t.priority END,
        due_date = CASE WHEN p_action='EDIT' AND p_payload?'due_date' THEN (p_payload->>'due_date')::date ELSE t.due_date END,
        effective_on = CASE WHEN p_action='EDIT' AND p_payload?'effective_on' THEN (p_payload->>'effective_on')::date ELSE t.effective_on END,
        assignee_id = CASE WHEN p_action IN ('PUBLISH','ASSIGN') THEN v_candidate_id ELSE t.assignee_id END,
        status = v_to_status,
        deleted_at = CASE WHEN p_action='DELETE_DRAFT' THEN clock_timestamp() ELSE t.deleted_at END,
        version = t.version+1,
        updated_at = clock_timestamp()
    WHERE t.task_id=v_task.task_id RETURNING t.* INTO v_task;

    v_changed_fields := v_changed_fields || jsonb_build_object('version',v_task.version);
    IF p_action IN ('PUBLISH','ASSIGN') THEN
        v_changed_fields := v_changed_fields || jsonb_build_object('assignee_id',v_task.assignee_id::text);
    END IF;
    INSERT INTO public.task_history
        (task_id,sequence_no,request_id,request_hash,event_type,from_status,to_status,actor_id,note,changed_fields)
    VALUES (v_task.task_id,v_task.version,p_request_id,p_request_hash,v_event_type,
            v_from_status,v_task.status,p_actor_id,v_note,v_changed_fields);
    RETURN v_task.task_id;
END $$;
