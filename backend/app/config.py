"""只读取项目配置，连接目标限定为本机专用开发或验证库。"""

from pathlib import Path
import re
import os
import stat

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from dotenv import dotenv_values
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = PROJECT_ROOT / "backend"


def workspace_path(path: Path) -> Path:
    """拒绝秘密文件路径中的链接，并将读写限定在本仓库。"""
    path = Path(os.path.abspath(path))
    root = Path(os.path.abspath(PROJECT_ROOT))
    try:
        relative = path.relative_to(root)
    except ValueError:
        raise ValueError("本地配置必须保留在本仓库内。") from None
    current = root
    for part in (None, *relative.parts):
        if part is not None:
            current = current / part
        try:
            info = current.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            raise ValueError("本地配置路径不允许符号链接或重解析点。")
    return path



class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        env_prefix="VISION_ZERO_",
        extra="ignore",
    )

    database_url: SecretStr = SecretStr("")
    migration_database_url: SecretStr = SecretStr("")
    worker_database_url: SecretStr = SecretStr("")
    jwt_secret: SecretStr = SecretStr("")
    jwt_minutes: int = 15
    database_name: str = "vision_zero_dev"
    db_port: int = 55433
    run_db_tests: bool = False
    test_config_file: str = ""

    def __init__(self, **values):
        workspace_path(PROJECT_ROOT / ".env")
        super().__init__(**values)

    def approved_values(self) -> dict:
        root = dotenv_values(workspace_path(PROJECT_ROOT / ".env"))
        if not self.test_config_file:
            return root
        path = workspace_path(Path(self.test_config_file)).resolve()
        if not (self.run_db_tests
                and re.fullmatch(r"vision_zero_m1_test_[0-9a-f]{12}", self.database_name)
                and path.parent == (PROJECT_ROOT / ".m1-work/model").resolve()
                and path.name == self.database_name + ".env"):
            raise ValueError("验证配置不符合本项目边界。")
        values = dotenv_values(path)
        for key in ("VISION_ZERO_WORKSPACE_ID", "VISION_ZERO_DB_PORT", "POSTGRES_PASSWORD"):
            if values.get(key) != root.get(key):
                raise ValueError("验证配置不符合本项目边界。")
        if values.get("VISION_ZERO_DATABASE_NAME") != self.database_name:
            raise ValueError("验证配置不符合本项目边界。")
        return values

    def connection_url(self, *, migration: bool = False, worker: bool = False) -> URL:
        if migration and worker:
            raise ValueError("连接角色不明确。")
        kind = "migrator" if migration else "worker" if worker else "app"
        secret = self.migration_database_url if migration else self.worker_database_url if worker else self.database_url
        try:
            url = make_url(secret.get_secret_value())
            approved = self.approved_values()
            approved_key = "VISION_ZERO_MIGRATION_DATABASE_URL" if migration else "VISION_ZERO_WORKER_DATABASE_URL" if worker else "VISION_ZERO_DATABASE_URL"
            approved_url = make_url(approved.get(approved_key) or "")
            test_database = self.run_db_tests and re.fullmatch(
                r"vision_zero_m1_test_[0-9a-f]{12}", self.database_name
            )
            allowed_name = self.database_name == "vision_zero_dev" or test_database
            valid = (
                allowed_name
                and approved.get("VISION_ZERO_DATABASE_NAME") == self.database_name
                and self.db_port == int(approved.get("VISION_ZERO_DB_PORT") or "0")
                and url == approved_url
                and url.drivername == "postgresql+psycopg"
                and url.host in {"127.0.0.1", "localhost"}
                and url.port == self.db_port
                and url.database == self.database_name
                and url.username == self.database_name + "_" + kind
                and bool(url.password)
                and not url.query
            )
        except (ArgumentError, ValueError, TypeError):
            valid = False
        if not valid:
            raise ValueError("连接配置不符合本项目本机专用库边界。") from None
        return url

    def signing_key(self) -> str:
        key = self.jwt_secret.get_secret_value()
        approved = self.approved_values()
        if (not re.fullmatch(r"[0-9a-f]{96}", key)
                or key != approved.get("VISION_ZERO_JWT_SECRET")
                or not 1 <= self.jwt_minutes <= 30):
            raise ValueError("认证配置无效。")
        return key
