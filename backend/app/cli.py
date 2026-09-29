"""M1本机角色与首次管理员入口；密码不通过命令行参数或stdout传递。"""

import argparse
from getpass import getpass
import os
import secrets
from contextlib import ExitStack
from datetime import date
from pathlib import Path
from uuid import UUID, uuid4
import json

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.auth import ACCOUNT_LOCK, NewUser, password_hasher
from app.config import PROJECT_ROOT, Settings
from app.db.connection import database_engine
from app.db.provision import provision, workspace_path
from app.models import AppUser, AuditLog
from app.importing.storage import save_files
from app.importing.service import batch_data, create_batch, request_action
from app.models import ImportBatch


def init_admin(username, display_name, *, generate=False):
    path = workspace_path(PROJECT_ROOT / ".m1-work/model/initial-admin.txt")
    if generate and path.exists():
        raise ValueError("已保留首次管理员文件，不会覆盖或重复初始化。")
    password = secrets.token_urlsafe(24) if generate else os.environ.get("VISION_ZERO_INITIAL_ADMIN_PASSWORD") or getpass("首次管理员密码（至少12字符）：")
    body = NewUser(username=username, display_name=display_name, password=password, role="ADMIN")
    engine = database_engine(Settings(), migration=True)
    try:
        with Session(engine) as session, session.begin():
            session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": ACCOUNT_LOCK})
            if session.scalar(select(AppUser.user_id).where(AppUser.role_id == 1, AppUser.is_active).limit(1)):
                raise ValueError("已有可用管理员；后续账户请通过管理员API创建。")
            user = AppUser(username=body.username, display_name=body.display_name, role_id=1,
                           password_hash=password_hasher.hash(password))
            session.add(user)
            session.flush()
            session.add(AuditLog(actor_id=user.user_id, action="INITIAL_ADMIN", entity_type="app_user",
                                 entity_id=str(user.user_id), details={"method": "local_cli"}))
            if generate:
                path.parent.mkdir(parents=True, exist_ok=True)
                workspace_path(path)
                with path.open("x", encoding="utf-8") as stream:
                    stream.write(f"本机首次管理员；仅保留在Git忽略目录。\n用户名：{username}\n密码：{password}\n登录后请修改密码。\n")
    finally:
        engine.dispose()
    print("首次管理员已建立。" + ("随机密码保存在 .m1-work/model/initial-admin.txt。" if generate else ""))


def main():
    parser = argparse.ArgumentParser(description="Vision Zero M1本机维护入口")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("provision-roles")
    admin = commands.add_parser("init-admin")
    admin.add_argument("--username", default="admin")
    admin.add_argument("--display-name", default="系统管理员")
    admin.add_argument("--generate", action="store_true")
    upload = commands.add_parser("import-csv")
    upload.add_argument("--directory", required=True)
    upload.add_argument("--username", default="admin")
    upload.add_argument("--start", type=date.fromisoformat, required=True)
    upload.add_argument("--end", type=date.fromisoformat, required=True)
    upload.add_argument("--request-id", type=UUID, default=None)
    upload.add_argument("--header-mode", choices=("api", "display", "auto"), default="auto")
    publish = commands.add_parser("publish-import")
    publish.add_argument("batch_id", type=int)
    publish.add_argument("--username", default="admin")
    publish.add_argument("--request-id", type=UUID, default=None)
    retry = commands.add_parser("retry-import")
    retry.add_argument("batch_id", type=int)
    retry.add_argument("--username", default="admin")
    retry.add_argument("--request-id", type=UUID, default=None)
    args = parser.parse_args()
    try:
        if args.command == "provision-roles":
            provision()
            print("本机迁移、应用、worker角色已配置；随机凭据仅保存到本地忽略文件。")
        elif args.command == "init-admin":
            init_admin(args.username, args.display_name, generate=args.generate)
        else:
            engine = database_engine(Settings())
            try:
                with Session(engine, expire_on_commit=False) as session, session.begin():
                    session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": ACCOUNT_LOCK})
                    actor = session.scalar(select(AppUser).where(AppUser.username == args.username, AppUser.is_active, AppUser.role_id == 1))
                    if actor is None: raise ValueError("本机维护需启用的管理员")
                    if args.command == "import-csv":
                        directory = workspace_path(Path(args.directory))
                        directory.relative_to(PROJECT_ROOT / "data/raw")
                        with ExitStack() as stack:
                            streams = [(kind, stack.enter_context(workspace_path(directory / (kind + ".csv")).open("rb")), kind + ".csv") for kind in ("CRASHES", "PERSON", "VEHICLES")]
                            batch = create_batch(session, actor, args.request_id or uuid4(), args.start, args.end, save_files(streams, args.header_mode))
                    else:
                        batch = session.scalar(select(ImportBatch).where(ImportBatch.batch_id == args.batch_id).with_for_update())
                        if batch is None: raise ValueError("批次不存在")
                        batch = request_action(session, actor, batch, args.request_id or uuid4(), "IMPORT_RETRY" if args.command == "retry-import" else "IMPORT_PUBLISH")
                    result = batch_data(batch)
                print(json.dumps(result, ensure_ascii=False))
            finally:
                engine.dispose()
    except Exception:
        # 驱动/配置异常可能包含DSN或密码，维护入口不打印异常正文。
        print("操作未完成；请核对专用数据库状态、已有角色归属及本地配置。")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
