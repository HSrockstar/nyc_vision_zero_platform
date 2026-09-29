"""导入请求/发布授权与幂等；正式关系只由worker事务写入。"""

from datetime import date, datetime, timezone
from uuid import UUID

from sqlalchemy import select, text

from app.auth import ACCOUNT_LOCK, fail
from app.contracts import request_digest
from app.importing.cleaning import CLEANING_VERSION, digest
from app.models import AuditLog, ImportBatch
from app.importing.storage import discard_files


def record_audit(session, actor_id, action, batch_id, request_id, details=None):
    session.add(AuditLog(actor_id=actor_id, action=action, entity_type="import_batch", entity_id=str(batch_id),
                         request_id=request_id, details=details or {}))


def create_batch(session, actor, request_id, start, end, manifest):
    if not isinstance(start, date) or not isinstance(end, date) or start >= end:
        fail(422, "IMPORT_RANGE_INVALID", "请选择左闭右开的有效日期范围。")
    session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": ACCOUNT_LOCK})
    content = {"files": [{key: file[key] for key in ("source_kind", "dataset_id", "sha256", "bytes", "headers", "header_mode")}
                         for file in sorted(manifest["files"], key=lambda file: file["source_kind"])],
               "start": start.isoformat(), "end": end.isoformat(), "cleaning_version": CLEANING_VERSION}
    request_hash = request_digest(actor_id=str(actor.user_id), operation="IMPORT_CREATE", target_id=None, payload=content)
    existing = session.scalar(select(ImportBatch).where(ImportBatch.request_id == request_id))
    if existing:
        if manifest.get("storage_key") != existing.input_manifest.get("storage_key"):
            discard_files(manifest["storage_key"])
        if existing.request_hash != request_hash:
            fail(409, "IDEMPOTENCY_CONFLICT", "该请求编号已用于不同的导入内容。")
        return existing
    batch = ImportBatch(request_id=request_id, request_hash=request_hash, manifest_hash=digest(content),
                        cleaning_version=CLEANING_VERSION, input_manifest=manifest, requested_start=start,
                        requested_end=end, created_by=actor.user_id, status="UPLOADED")
    session.add(batch)
    session.info.setdefault("uncommitted_import_files", []).append(manifest["storage_key"])
    session.flush()
    record_audit(session, actor.user_id, "IMPORT_UPLOADED", batch.batch_id, request_id, {"source_files": 3})
    return batch


def request_action(session, actor, batch, request_id: UUID, operation):
    digest_value = request_digest(actor_id=str(actor.user_id), operation=operation,
                                  target_id=str(batch.batch_id), payload={})
    key = "publishes" if operation == "IMPORT_PUBLISH" else "retries"
    manifest = dict(batch.input_manifest)
    # ACCOUNT_LOCK使同一操作编号的全库检查与登记串行，不能跨目标复用。
    other = session.scalar(select(ImportBatch).where(ImportBatch.input_manifest[key].contains([{"request_id": str(request_id)}])))
    if other:
        event = next(event for event in other.input_manifest[key] if event["request_id"] == str(request_id))
        if other.batch_id != batch.batch_id or event["request_hash"] != digest_value:
            fail(409, "IDEMPOTENCY_CONFLICT", "该请求编号已用于不同的操作。")
        return batch
    if operation == "IMPORT_PUBLISH":
        if batch.status != "READY" or batch.input_manifest.get("validation", {}).get("blocking_issue_count", 1):
            fail(409, "IMPORT_NOT_READY", "批次尚未就绪或存在阻断问题，不能发布。")
        batch.status = "PUBLISHING"
        batch.publish_request_id = request_id
        batch.publish_request_hash = digest_value
        batch.publish_requested_by = actor.user_id
    else:
        if batch.status != "FAILED":
            fail(409, "IMPORT_RETRY_NOT_ALLOWED", "只有失败批次可以重新校验。")
        if batch.attempt_no >= 10:
            fail(409, "IMPORT_RETRY_LIMIT", "重试次数已达上限，请建立新批次。")
        batch.status = "UPLOADED"
        batch.error_summary = None
        batch.finished_at = None
        batch.publish_request_id = None
        batch.publish_request_hash = None
        batch.publish_requested_by = None
    batch.worker_token = None
    batch.lease_expires_at = None
    events = list(manifest.get(key, []))
    events.append({"request_id": str(request_id), "request_hash": digest_value,
                   "actor_id": str(actor.user_id), "at": datetime.now(timezone.utc).isoformat()})
    manifest[key] = events
    batch.input_manifest = manifest
    record_audit(session, actor.user_id, operation + "_REQUESTED", batch.batch_id, request_id)
    session.flush()
    return batch


def batch_data(batch, *, detailed=True):
    data = {name: getattr(batch, name) for name in ("status", "cleaning_version", "rows_read", "rows_accepted", "rows_rejected", "rows_skipped", "error_summary")}
    data.update(batch_id=str(batch.batch_id), published_revision=str(batch.published_revision) if batch.published_revision is not None else None,
                requested_start=batch.requested_start.isoformat() if batch.requested_start else None, requested_end=batch.requested_end.isoformat() if batch.requested_end else None,
                created_at=batch.created_at.isoformat(), attempt_no=batch.attempt_no)
    if detailed:
        # storage_key和请求摘要只供worker使用；不会返回本机路径。
        manifest = batch.input_manifest
        data["input_manifest"] = {key: manifest[key] for key in ("files", "validation", "publication") if key in manifest}
        counts = manifest.get("validation", {}).get("source_counts", {})
        data["input_manifest"]["files"] = [{**file, "row_count": sum(counts[file["source_kind"]].values()) if file["source_kind"] in counts else None}
                                             for file in manifest.get("files", [])]
    return data
