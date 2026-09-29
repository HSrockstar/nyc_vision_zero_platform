"""M1认证与账户管理：当前角色鉴权、全会话失效及账户变更事务。"""

from collections import OrderedDict
from datetime import datetime, timedelta, timezone
import secrets
from threading import Lock
from time import monotonic
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import jwt
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator
from pwdlib import PasswordHash
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.config import Settings
from app.db.connection import database_engine
from app.models import AppUser, AuditLog, GovernanceTask

router = APIRouter(prefix="/api/v1")
bearer = HTTPBearer(auto_error=False)
password_hasher = PasswordHash.recommended()
dummy_hash = password_hasher.hash(secrets.token_urlsafe(32))
ROLE_IDS = {"ADMIN": 1, "MANAGER": 2, "VIEWER": 3}
ACCOUNT_LOCK = 76301002


def fail(status, code, message):
    raise HTTPException(status_code=status, detail={"code": code, "message": message},
                        headers={"WWW-Authenticate": "Bearer"} if status == 401 else None)


def response(request, data):
    return {"data": data, "meta": {"request_id": str(request.state.request_id)}}


class LoginLimiter:
    """单进程限流；IP来自连接，不信任客户端转发头。"""
    def __init__(self):
        self.entries = OrderedDict()
        self.lock = Lock()

    def reserve(self, key, limit=5):
        with self.lock:
            now = monotonic()
            failures, pending = self.entries.get(key, ([], 0))
            failures = [stamp for stamp in failures if now - stamp < 300]
            if len(failures) + pending >= limit:
                fail(429, "LOGIN_RATE_LIMIT", "登录尝试过多，请五分钟后重试。")
            self.entries[key] = (failures, pending + 1)
            self.entries.move_to_end(key)
            if len(self.entries) > 4096:
                self.entries.popitem(last=False)

    def finish(self, key, success):
        with self.lock:
            failures, pending = self.entries.get(key, ([], 1))
            updated = failures if success is None else [] if success else failures + [monotonic()]
            self.entries[key] = (updated, max(0, pending - 1))


login_limiter = LoginLimiter()


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LoginInput(Input):
    username: str = Field(min_length=1, max_length=80)
    password: SecretStr = Field(max_length=128)


class NewUser(Input):
    username: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_.-]{2,79}$")
    display_name: str = Field(min_length=1, max_length=80)
    role: Literal["ADMIN", "MANAGER", "VIEWER"]
    password: SecretStr = Field(min_length=12, max_length=128)

    @field_validator("display_name")
    @classmethod
    def nonempty_name(cls, value):
        if not value.strip():
            raise ValueError("显示名不能为空")
        return value.strip()


class UserChange(Input):
    expected_version: int = Field(gt=0)
    display_name: str | None = Field(default=None, min_length=1, max_length=80)
    role: Literal["ADMIN", "MANAGER", "VIEWER"] | None = None
    is_active: bool | None = None

    @field_validator("display_name")
    @classmethod
    def nonempty_name(cls, value):
        if value is not None and not value.strip():
            raise ValueError("显示名不能为空")
        return value.strip() if value is not None else value


class PasswordChange(Input):
    old_password: SecretStr = Field(max_length=128)
    new_password: SecretStr = Field(min_length=12, max_length=128)


def database_session():
    try:
        engine = database_engine(Settings())
    except ValueError:
        fail(503, "CONFIGURATION_INVALID", "服务配置尚未就绪。")
    try:
        with Session(engine, expire_on_commit=False) as session, session.begin():
            yield session
    finally:
        engine.dispose()


def verify_password(password, encoded):
    try:
        return password_hasher.verify(password, encoded)
    except Exception:
        # 数据库中的无效哈希与错误密码使用相同公开失败路径。
        return False


def token_claims(token):
    try:
        key = Settings().signing_key()
    except ValueError:
        fail(503, "CONFIGURATION_INVALID", "认证配置尚未就绪。")
    try:
        claims = jwt.decode(token, key, algorithms=["HS256"], issuer="vision-zero",
                            audience="vision-zero-web",
                            options={"require": ["sub", "exp", "iat", "nbf", "jti", "ver", "iss", "aud"]})
        if (not isinstance(claims["sub"], str) or not claims["sub"].isascii() or not claims["sub"].isdigit()
                or not 0 < int(claims["sub"]) <= 9223372036854775807
                or type(claims["ver"]) is not int or claims["ver"] <= 0
                or any(type(claims[name]) is not int for name in ("exp", "iat", "nbf"))
                or not 0 < claims["exp"] - claims["iat"] <= 1800):
            raise ValueError("claims")
        UUID(claims["jti"])
        return claims
    except (jwt.InvalidTokenError, ValueError, TypeError, KeyError):
        fail(401, "AUTH_REQUIRED", "请重新登录。")


def current_user(request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
                 session: Session = Depends(database_session, scope="function")):
    if credentials is None or len(credentials.credentials) > 4096:
        fail(401, "AUTH_REQUIRED", "请先登录。")
    claims = token_claims(credentials.credentials)
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        # 与用户触发器/未来任务分配共用锁；先串行化，再检查最新身份。
        session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": ACCOUNT_LOCK})
    user = session.get(AppUser, int(claims["sub"]))
    if user is None or not user.is_active or user.auth_version != claims["ver"]:
        fail(401, "AUTH_REQUIRED", "账户状态已改变，请重新登录。")
    return user


def administrator(user: AppUser = Depends(current_user)):
    if user.role_id != ROLE_IDS["ADMIN"]:
        fail(403, "FORBIDDEN", "此操作需要管理员权限。")
    return user


def public_user(user):
    return {"user_id": str(user.user_id), "username": user.username,
            "display_name": user.display_name,
            "role": next(code for code, value in ROLE_IDS.items() if value == user.role_id),
            "is_active": user.is_active, "version": user.version}


def audit(session, request, actor, action, target, details):
    session.add(AuditLog(actor_id=actor.user_id, action=action, entity_type="app_user",
                         entity_id=str(target.user_id), request_id=request.state.request_id,
                         details=details))


@router.post("/auth/login")
def login(body: LoginInput, request: Request, session: Session = Depends(database_session, scope="function")):
    settings = Settings()
    try:
        key = settings.signing_key()
    except ValueError:
        fail(503, "CONFIGURATION_INVALID", "认证配置尚未就绪。")
    ip = request.client.host if request.client else "local"
    ip_key = 'ip:' + ip
    user_key = 'user:' + body.username.strip().lower()
    login_limiter.reserve(ip_key, limit=30)
    try:
        login_limiter.reserve(user_key)
    except HTTPException:
        login_limiter.finish(ip_key, None)
        raise
    success = False
    try:
        user = session.scalar(select(AppUser).where(func.lower(AppUser.username) == body.username.strip().lower()))
        valid = verify_password(body.password.get_secret_value(), user.password_hash if user else dummy_hash)
        if not user or not valid or not user.is_active:
            fail(401, "INVALID_CREDENTIALS", "用户名或密码不正确，或账户已停用。")
        now = datetime.now(timezone.utc)
        token = jwt.encode({"sub": str(user.user_id), "ver": user.auth_version,
                            "iat": now, "nbf": now, "exp": now + timedelta(minutes=settings.jwt_minutes),
                            "iss": "vision-zero", "aud": "vision-zero-web", "jti": str(uuid4())},
                           key, algorithm="HS256")
        success = True
        return response(request, {"access_token": token, "token_type": "bearer",
                                  "expires_in": settings.jwt_minutes * 60, "user": public_user(user)})
    finally:
        login_limiter.finish(ip_key, success)
        login_limiter.finish(user_key, success)


@router.get("/auth/me")
def me(request: Request, user: AppUser = Depends(current_user)):
    data = public_user(user)
    data["permissions"] = ["users:manage"] if user.role_id == 1 else []
    return response(request, data)


@router.post("/auth/logout")
def logout(request: Request, user: AppUser = Depends(current_user), session: Session = Depends(database_session, scope="function")):
    user.auth_version += 1
    audit(session, request, user, "AUTH_LOGOUT_ALL", user, {})
    return response(request, {"logged_out_all_sessions": True})


@router.post("/auth/change-password")
def change_password(body: PasswordChange, request: Request, user: AppUser = Depends(current_user),
                    session: Session = Depends(database_session, scope="function")):
    if not verify_password(body.old_password.get_secret_value(), user.password_hash):
        fail(400, "PASSWORD_MISMATCH", "原密码不正确。")
    user.password_hash = password_hasher.hash(body.new_password.get_secret_value())
    audit(session, request, user, "PASSWORD_CHANGED", user, {})
    session.flush()
    return response(request, {"reauthentication_required": True})


@router.get("/users")
def list_users(request: Request, page: int = Query(default=1, ge=1, le=100000),
               page_size: int = Query(default=20, ge=1, le=100),
               actor: AppUser = Depends(administrator), session: Session = Depends(database_session, scope="function")):
    items = session.scalars(select(AppUser).order_by(AppUser.user_id).offset((page - 1) * page_size).limit(page_size)).all()
    total = session.scalar(select(func.count()).select_from(AppUser))
    return response(request, {"items": [public_user(user) for user in items], "total": total})


@router.post("/users", status_code=201)
def create_user(body: NewUser, request: Request, actor: AppUser = Depends(administrator),
                session: Session = Depends(database_session, scope="function")):
    if session.scalar(select(AppUser.user_id).where(func.lower(AppUser.username) == body.username.lower())):
        fail(409, "USERNAME_EXISTS", "登录名已存在。")
    user = AppUser(username=body.username, display_name=body.display_name, role_id=ROLE_IDS[body.role],
                   password_hash=password_hasher.hash(body.password.get_secret_value()))
    session.add(user)
    session.flush()
    audit(session, request, actor, "USER_CREATED", user, {"role": body.role})
    return response(request, public_user(user))


@router.patch("/users/{user_id}")
def update_user(user_id: str, body: UserChange, request: Request, actor: AppUser = Depends(administrator),
                session: Session = Depends(database_session, scope="function")):
    if not user_id.isascii() or not user_id.isdecimal() or not 0 < int(user_id) <= 9223372036854775807:
        fail(422, "INVALID_ID", "账户编号无效。")
    changes = body.model_dump(exclude_unset=True, exclude={"expected_version"})
    if not changes or any(value is None for value in changes.values()):
        fail(422, "INVALID_CHANGE", "请提供有效的账户修改字段。")
    user = session.get(AppUser, int(user_id), with_for_update=True)
    if user is None:
        fail(404, "USER_NOT_FOUND", "账户不存在。")
    if user.version != body.expected_version:
        fail(409, "USER_VERSION_CONFLICT", "账户已被修改，请刷新后重试。")
    new_role = ROLE_IDS[body.role] if "role" in changes else user.role_id
    new_active = body.is_active if "is_active" in changes else user.is_active
    if user.role_id == 1 and user.is_active and (new_role != 1 or not new_active):
        other = session.scalar(select(AppUser.user_id).where(AppUser.role_id == 1, AppUser.is_active, AppUser.user_id != user.user_id).limit(1))
        if other is None:
            fail(409, "USER_LAST_ADMIN", "不能停用或降级最后一个可用管理员。")
    if new_role != user.role_id or not new_active:
        active_task = session.scalar(select(GovernanceTask.task_id).where(
            GovernanceTask.assignee_id == user.user_id, GovernanceTask.deleted_at.is_(None),
            GovernanceTask.status.in_(["OPEN", "IN_PROGRESS", "PENDING_REVIEW"])).limit(1))
        if active_task:
            fail(409, "USER_HAS_ACTIVE_TASKS", "该执行人仍有在办任务，请先处理任务。")
    if "display_name" in changes:
        user.display_name = body.display_name
    user.role_id = new_role
    user.is_active = new_active
    # 即使显式提交相同值，也作为版本受控操作保存。
    user.version += 1
    audit(session, request, actor, "USER_UPDATED", user, {"fields": sorted(changes)})
    session.flush()
    session.refresh(user)
    return response(request, public_user(user))
