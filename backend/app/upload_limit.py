"""在multipart解析前按实际请求字节限制上传，并限制并发暂存。"""

import asyncio
from uuid import uuid4

from fastapi import HTTPException
from starlette.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.importing.storage import MAX_BYTES
from app.auth import fail, token_claims
from app.config import Settings
from app.db.connection import database_engine
from app.models import AppUser


def upload_authorized(authorization):
    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer" or len(parts[1]) > 4096:
        fail(401, "AUTH_REQUIRED", "请先登录。")
    claims = token_claims(parts[1])
    engine = database_engine(Settings())
    try:
        with Session(engine) as session:
            user = session.execute(select(AppUser.role_id, AppUser.is_active, AppUser.auth_version).where(AppUser.user_id == int(claims["sub"]))).first()
            if not user or not user.is_active or user.auth_version != claims["ver"]:
                fail(401, "AUTH_REQUIRED", "请重新登录。")
            if user.role_id != 1: fail(403, "FORBIDDEN", "此操作需要管理员权限。")
    finally:
        engine.dispose()


async def rejected(scope, receive, send, status, code, message, headers=None):
    request_id = str(scope.get("state", {}).get("request_id") or uuid4())
    result = JSONResponse({"error": {"code": code, "message": message}, "meta": {"request_id": request_id}},
                          status_code=status, headers={"X-Request-ID": request_id, "Cache-Control": "no-store", **(headers or {})})
    return await result(scope, receive, send)


class UploadLimit:
    def __init__(self, app):
        self.app = app
        self.slots = asyncio.Semaphore(2)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] != "POST" or scope["path"] != "/api/v1/imports":
            return await self.app(scope, receive, send)
        limit = MAX_BYTES + 1024 * 1024
        headers = dict(scope.get("headers", []))
        # File/Form解析早于路由依赖；先做只读权限检查，保存前仍由依赖在账号锁下复核。
        try:
            await run_in_threadpool(upload_authorized, headers.get(b"authorization", b"").decode("latin-1"))
        except HTTPException as error:
            return await rejected(scope, receive, send, error.status_code, error.detail["code"], error.detail["message"], error.headers)
        except (ValueError, SQLAlchemyError):
            return await rejected(scope, receive, send, 503, "DATABASE_UNAVAILABLE", "数据库或认证配置暂不可用。")
        try: length = int(headers.get(b"content-length", b"0"))
        except ValueError: length = limit + 1
        if length > limit or self.slots.locked():
            return await rejected(scope, receive, send, 413 if length > limit else 429, "UPLOAD_LIMIT", "上传超过大小或并发限制，请稍后重试。")
        received = 0
        deadline = asyncio.get_running_loop().time() + 300
        async def bounded_receive():
            nonlocal received
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise HTTPException(408, detail={"code": "UPLOAD_TIMEOUT", "message": "上传超过时间限制。"})
            try:
                message = await asyncio.wait_for(receive(), timeout=min(30, remaining))
            except TimeoutError:
                raise HTTPException(408, detail={"code": "UPLOAD_TIMEOUT", "message": "上传连接超时。"}) from None
            received += len(message.get("body", b""))
            if received > limit:
                raise HTTPException(413, detail={"code": "UPLOAD_LIMIT", "message": "上传文件超过大小限制。"})
            return message
        async with self.slots:
            await self.app(scope, bounded_receive, send)
