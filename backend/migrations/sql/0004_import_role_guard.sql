CREATE OR REPLACE FUNCTION public.vz_import_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp AS $$
BEGIN
    IF TG_OP='INSERT' THEN
        IF NEW.status <> 'UPLOADED' THEN
            RAISE EXCEPTION '批次必须从上传状态开始' USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;
    IF OLD.status IN ('SUCCEEDED', 'CANCELLED') THEN
        RAISE EXCEPTION '终态导入批次不可改写' USING ERRCODE = '23514';
    END IF;
    IF ROW(NEW.batch_id,NEW.request_id,NEW.request_hash,NEW.manifest_hash,NEW.cleaning_version,
           NEW.requested_start,NEW.requested_end,NEW.created_by,NEW.created_at,
           NEW.input_manifest->'files',NEW.input_manifest->'storage_key')
       IS DISTINCT FROM ROW(OLD.batch_id,OLD.request_id,OLD.request_hash,OLD.manifest_hash,OLD.cleaning_version,
           OLD.requested_start,OLD.requested_end,OLD.created_by,OLD.created_at,
           OLD.input_manifest->'files',OLD.input_manifest->'storage_key') THEN
        RAISE EXCEPTION '导入输入、范围及创建依据不可替换' USING ERRCODE = '23514';
    END IF;
    IF NEW.status <> OLD.status AND NOT (
         (OLD.status='UPLOADED' AND NEW.status IN ('VALIDATING','FAILED','CANCELLED'))
      OR (OLD.status='VALIDATING' AND NEW.status IN ('READY','FAILED'))
      OR (OLD.status='READY' AND NEW.status IN ('PUBLISHING','CANCELLED'))
      OR (OLD.status='PUBLISHING' AND NEW.status IN ('SUCCEEDED','FAILED'))
      OR (OLD.status='FAILED' AND NEW.status IN ('UPLOADED','CANCELLED'))) THEN
        RAISE EXCEPTION '导入状态转换无效' USING ERRCODE = '23514';
    END IF;
    IF current_user LIKE '%\_app' ESCAPE '\' AND NEW.status <> OLD.status AND NOT (
        (OLD.status='READY' AND NEW.status='PUBLISHING') OR (OLD.status='FAILED' AND NEW.status='UPLOADED')) THEN
        RAISE EXCEPTION '应用账号仅能登记发布或重试请求' USING ERRCODE = '23514';
    END IF;
    IF current_user LIKE '%\_worker' ESCAPE '\' AND OLD.status='READY' AND NEW.status='PUBLISHING' THEN
        RAISE EXCEPTION 'worker不能自行授权发布' USING ERRCODE = '23514';
    END IF;
    IF NEW.status='PUBLISHING' AND NEW.publish_request_id IS NULL THEN
        RAISE EXCEPTION '发布必须有明确的管理员请求' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END $$;
