"""M0 包导入和基础调用验证；不连接数据库，不实现业务 API。"""
import importlib.metadata
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient
from geoalchemy2 import Geometry
from pwdlib import PasswordHash
from sqlalchemy import Column, MetaData, Table, func, select
from sqlalchemy.dialects import postgresql
import psycopg
import jwt

app = FastAPI()


@app.get("/m0-dependency-check")
def check():
    return {"scope": "M0 dependency verification"}


response = TestClient(app).get("/m0-dependency-check")
assert response.status_code == 200
password_hash = PasswordHash.recommended()
hashed = password_hash.hash("M0-temporary-smoke-value")
assert password_hash.verify("M0-temporary-smoke-value", hashed)
token = jwt.encode({"scope": "m0"}, "m0-local-smoke-key-at-least-32-bytes", algorithm="HS256")
assert jwt.decode(token, "m0-local-smoke-key-at-least-32-bytes", algorithms=["HS256"])["scope"] == "m0"
table = Table("m0_location", MetaData(), Column("geom", Geometry("POINT", srid=4326)))
query = select(func.ST_AsText(table.c.geom)).compile(dialect=postgresql.dialect())
assert "ST_AsText" in str(query)
packages = ["fastapi", "SQLAlchemy", "psycopg", "psycopg-binary", "alembic", "GeoAlchemy2", "uvicorn", "pytest", "httpx", "PyJWT", "pwdlib", "pydantic-settings", "python-multipart"]
print(json.dumps({"versions": {p: importlib.metadata.version(p) for p in packages}, "fastapi_testclient": "passed", "argon2_roundtrip": "passed", "jwt_roundtrip": "passed", "postgresql_sql_compilation": "passed", "psycopg_implementation": psycopg.pq.__impl__, "database_connection": "not_executed"}, ensure_ascii=False, indent=2))
