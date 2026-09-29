"""只读取项目配置，连接目标限定为本机专用开发或验证库。"""

from pathlib import Path
import re

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from dotenv import dotenv_values
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = PROJECT_ROOT / "backend"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        env_prefix="VISION_ZERO_",
        extra="ignore",
    )

    database_url: SecretStr = SecretStr("")
    migration_database_url: SecretStr = SecretStr("")
    database_name: str = "vision_zero_dev"
    db_port: int = 55433
    run_db_tests: bool = False

    def connection_url(self, *, migration: bool = False) -> URL:
        secret = self.migration_database_url if migration else self.database_url
        try:
            url = make_url(secret.get_secret_value())
            approved = dotenv_values(PROJECT_ROOT / ".env")
            approved_key = "VISION_ZERO_MIGRATION_DATABASE_URL" if migration else "VISION_ZERO_DATABASE_URL"
            approved_url = make_url(approved.get(approved_key) or "")
            test_database = self.run_db_tests and re.fullmatch(
                r"vision_zero_m1_test_[0-9a-f]{12}", self.database_name
            )
            allowed_name = self.database_name == "vision_zero_dev" or test_database
            valid = (
                allowed_name
                and approved.get("VISION_ZERO_DATABASE_NAME") == "vision_zero_dev"
                and self.db_port == int(approved.get("VISION_ZERO_DB_PORT") or "0")
                and url.set(database="vision_zero_dev") == approved_url
                and url.drivername == "postgresql+psycopg"
                and url.host in {"127.0.0.1", "localhost"}
                and url.port == self.db_port
                and url.database == self.database_name
                and bool(url.username)
                and bool(url.password)
                and not url.query
            )
        except (ArgumentError, ValueError, TypeError):
            valid = False
        if not valid:
            raise ValueError("连接配置不符合本项目本机专用库边界。") from None
        return url
