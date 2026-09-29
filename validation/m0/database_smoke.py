"""真实 PostgreSQL/PostGIS 的 M0 验证；只写会话临时表，不创建业务结构。"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import psycopg
from geoalchemy2 import Geometry, WKTElement
from sqlalchemy import Column, Integer, MetaData, Table, create_engine, func, insert, select, text
from sqlalchemy.engine import URL


def verify(config: dict) -> dict:
    checks = {}
    conn = psycopg.connect(host=config["host"], port=config["port"], dbname=config["database"], user=config["user"], password=config["password"], connect_timeout=10)
    with conn:
        versions = conn.execute("SELECT version(), current_setting('server_version_num'), PostGIS_Full_Version(), postgis_lib_version()").fetchone()
        extensions = conn.execute("SELECT extname, extversion FROM pg_extension WHERE extname LIKE 'postgis%' ORDER BY extname").fetchall()
        conn.execute("CREATE TEMP TABLE m0_parent (id BIGINT PRIMARY KEY, label TEXT NOT NULL UNIQUE, n INTEGER CHECK(n >= 0))")
        conn.execute("CREATE TEMP TABLE m0_child (id BIGINT PRIMARY KEY, parent_id BIGINT NOT NULL REFERENCES m0_parent(id), geom geometry(Point,4326))")
        conn.execute("INSERT INTO m0_parent VALUES (1, 'm0-only', 0)")
        conn.execute("INSERT INTO m0_child VALUES (1, 1, ST_SetSRID(ST_MakePoint(-73.9857, 40.7484),4326))")
        for label, statement, expected_state in [
            ("primary_key", "INSERT INTO m0_parent VALUES (1,'other',0)", "23505"),
            ("unique", "INSERT INTO m0_parent VALUES (2,'m0-only',0)", "23505"),
            ("foreign_key", "INSERT INTO m0_child VALUES (2,999,NULL)", "23503"),
            ("check_nonnegative", "INSERT INTO m0_parent VALUES (2,'negative',-1)", "23514"),
            ("not_null", "INSERT INTO m0_parent VALUES (2,NULL,0)", "23502"),
            ("geometry_srid", "INSERT INTO m0_child VALUES (2,1,ST_SetSRID(ST_MakePoint(0,0),3857))", "22023"),
        ]:
            try:
                with conn.transaction():
                    conn.execute(statement)
            except psycopg.Error as error:
                assert error.sqlstate == expected_state, (label, error.sqlstate)
                checks[label] = {"passed": True, "sqlstate": error.sqlstate}
            else:
                raise AssertionError(f"约束未拒绝错误输入：{label}")
        point = conn.execute("SELECT ST_SRID(geom), ST_X(geom), ST_Y(geom), ST_AsGeoJSON(geom) FROM m0_child WHERE id=1").fetchone()
        assert point[:3] == (4326, -73.9857, 40.7484)
        assert json.loads(point[3])["coordinates"] == [-73.9857, 40.7484]
        checks["srid_and_coordinate_order"] = {"passed": True, "srid": point[0], "coordinates": json.loads(point[3])["coordinates"]}
        distance, near, far = conn.execute("""
            WITH points AS (
              SELECT ST_SetSRID(ST_MakePoint(-73.9857,40.7484),4326)::geography a,
                     ST_SetSRID(ST_MakePoint(-73.9847,40.7484),4326)::geography b
            ) SELECT ST_Distance(a,b),ST_DWithin(a,b,100),ST_DWithin(a,b,50) FROM points
        """).fetchone()
        assert 80 < distance < 90 and near is True and far is False
        checks["geography_distance_m"] = {"passed": True, "distance_m": distance, "within_100m": near, "within_50m": far}
        conn.execute("CREATE TEMP TABLE m0_rollback (id INTEGER PRIMARY KEY)")
        try:
            with conn.transaction():
                conn.execute("INSERT INTO m0_rollback VALUES (1)")
                conn.execute("INSERT INTO m0_rollback VALUES (1)")
        except psycopg.errors.UniqueViolation:
            pass
        assert conn.execute("SELECT count(*) FROM m0_rollback").fetchone()[0] == 0
        checks["transaction_rollback"] = {"passed": True, "rows_after_failed_transaction": 0}
    conn.close()

    url = URL.create("postgresql+psycopg", username=config["user"], password=config["password"], host=config["host"], port=int(config["port"]), database=config["database"])
    engine = create_engine(url, connect_args={"connect_timeout": 10})
    table = Table("m0_geoalchemy", MetaData(), Column("id", Integer, primary_key=True), Column("geom", Geometry("POINT", srid=4326)), prefixes=["TEMPORARY"])
    with engine.connect() as connection:
        with connection.begin():
            table.create(connection)
            connection.execute(insert(table).values(id=1, geom=WKTElement("POINT(-73.9857 40.7484)", srid=4326)))
            row = connection.execute(select(func.ST_X(table.c.geom), func.ST_Y(table.c.geom), func.ST_SRID(table.c.geom))).one()
            assert tuple(row) == (-73.9857, 40.7484, 4326)
        transaction = connection.begin()
        connection.execute(insert(table).values(id=2, geom=WKTElement("POINT(-73.98 40.74)", srid=4326)))
        transaction.rollback()
        assert connection.execute(text("SELECT count(*) FROM m0_geoalchemy")).scalar_one() == 1
    engine.dispose()
    checks["sqlalchemy_geoalchemy_roundtrip"] = {"passed": True}
    checks["sqlalchemy_rollback"] = {"passed": True}
    return {"postgresql": versions[0], "server_version_num": versions[1], "postgis_full_version": versions[2], "postgis_lib_version": versions[3], "extensions": dict(extensions), "checks": checks, "business_tables_created": False, "scope": "session temporary tables only"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--credentials", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.credentials:
        config = json.loads(args.credentials.read_text(encoding="utf-8"))
    else:
        config = {"host": os.environ["PGHOST"], "port": os.environ.get("PGPORT", "5432"), "database": os.environ["PGDATABASE"], "user": os.environ["PGUSER"], "password": os.environ["PGPASSWORD"]}
    result = verify(config)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"passed_checks": len(result["checks"]), "postgresql_version_num": result["server_version_num"], "postgis": result["postgis_lib_version"], "output": str(args.output)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
