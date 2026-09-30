CREATE INDEX ix_intersection_geography ON public.intersection USING gist ((center_geom::geography));

CREATE FUNCTION public.vz_intersection_state_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp AS $$
BEGIN
    IF current_user LIKE '%\_app' ESCAPE '\' THEN
        IF TG_OP='INSERT' THEN
            IF NEW.status <> 'CANDIDATE' OR NEW.source_method <> 'DERIVED'
               OR NEW.confirmed_by IS NOT NULL OR NEW.confirmed_at IS NOT NULL THEN
                RAISE EXCEPTION '应用账号只能创建系统推导候选' USING ERRCODE = '23514';
            END IF;
        ELSIF OLD.status <> 'CANDIDATE' OR NEW.status NOT IN ('CONFIRMED','REJECTED')
           OR NEW.version <> OLD.version + 1 THEN
            RAISE EXCEPTION '候选状态或版本转换无效' USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER trg_intersection_state BEFORE INSERT OR UPDATE ON public.intersection
    FOR EACH ROW EXECUTE FUNCTION public.vz_intersection_state_guard();

CREATE FUNCTION public.vz_assignment_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp AS $$
BEGIN
    IF NEW.match_status IN ('AUTO_MATCHED', 'MANUAL_CONFIRMED') AND NOT EXISTS (
        SELECT 1 FROM public.intersection i WHERE i.intersection_id = NEW.intersection_id
            AND i.status = 'CONFIRMED' AND i.is_active
    ) THEN
        RAISE EXCEPTION '正式归属必须指向启用的已确认交叉口' USING ERRCODE = '23514';
    END IF;
    IF TG_OP = 'UPDATE' AND OLD.match_method IN ('MANUAL', 'M3_REVIEW')
       AND NEW.match_method = 'M3_GENERATE' THEN
        RAISE EXCEPTION '自动生成不得覆盖人工判断' USING ERRCODE = '23514';
    END IF;
    IF TG_OP='UPDATE' AND current_user LIKE '%\_app' ESCAPE '\'
       AND NEW.version <> OLD.version + 1 THEN
        RAISE EXCEPTION '归属版本必须单步递增' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER trg_assignment_guard BEFORE INSERT OR UPDATE ON public.location_assignment
    FOR EACH ROW EXECUTE FUNCTION public.vz_assignment_guard();

CREATE FUNCTION public.vz_m3_revision_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp AS $$
BEGIN
    IF current_user LIKE '%\_app' ESCAPE '\' AND
       (NEW.revision <> OLD.revision + 1 OR NEW.last_change_note NOT LIKE 'M3%') THEN
        RAISE EXCEPTION '应用账号仅能递增M3分析版本' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER trg_m3_revision BEFORE UPDATE ON public.dataset_state
    FOR EACH ROW EXECUTE FUNCTION public.vz_m3_revision_guard();
