"""运行 Vision Zero M7 B01—B04 性能对照实验。

仅允许本项目随机测试库。所有临时索引 DDL 均处于单一事务中，最终以
ROLLBACK 恢复原索引；不写入业务表。结果目录采用独占创建，避免覆盖旧证据。
"""

from __future__ import annotations

import argparse
import csv
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import time

if __package__:
    from .benchmark_core import (
        B01_END, B01_PAGE_SIZE, B01_START, MEASURE_REPEATS, MIN_YEAR_COLLISIONS,
        STATEMENT_TIMEOUT_MS, WARMUP_REPEATS, YEAR_END, YEAR_START,
        equivalent_results, median, percentile,
        prepare_output_dir, result_summary, validate_database_name,
    )
else:
    from benchmark_core import (
        B01_END, B01_PAGE_SIZE, B01_START, MEASURE_REPEATS, MIN_YEAR_COLLISIONS,
        STATEMENT_TIMEOUT_MS, WARMUP_REPEATS, YEAR_END, YEAR_START,
        equivalent_results, median, percentile,
        prepare_output_dir, result_summary, validate_database_name,
    )


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"
BENCHMARK_SOURCE = PROJECT_ROOT / "benchmarks" / "benchmark_core.py"
INDEX_SOURCE = PROJECT_ROOT / "backend" / "migrations" / "sql" / "0002_tables.sql"
STATISTICS_SOURCE = PROJECT_ROOT / "backend" / "app" / "statistics.py"
SPATIAL_SOURCE = PROJECT_ROOT / "backend" / "app" / "spatial_api.py"

DATE_SQL = """
SELECT c.collision_id, c.crash_date
FROM public.collision AS c
WHERE c.crash_date >= %s AND c.crash_date < %s
ORDER BY c.crash_date DESC, c.collision_id DESC
LIMIT 100
""".strip()

LOCATION_DATE_SQL = """
SELECT c.collision_id, c.crash_date
FROM public.collision AS c
WHERE c.location_id = %s
  AND c.crash_date >= %s AND c.crash_date < %s
ORDER BY c.crash_date DESC, c.collision_id DESC
""".strip()

NEARBY_SQL = """
SELECT c.collision_id, c.crash_date, l.location_id
FROM public.location AS l
JOIN public.collision AS c USING (location_id)
WHERE l.geom IS NOT NULL
  AND c.crash_date >= %s AND c.crash_date < %s
  AND ST_DWithin(
        l.geom::geography,
        ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography,
        %s
      )
ORDER BY ST_Distance(
           l.geom::geography,
           ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography
         ), c.collision_id
LIMIT 101
""".strip()

B03_CENTER_SQL = """
WITH eligible_locations AS (
    SELECT DISTINCT l.location_id, l.geom
    FROM public.location AS l
    JOIN public.collision AS c USING (location_id)
    WHERE l.geom IS NOT NULL
      AND c.crash_date >= %s AND c.crash_date < %s
),
mean_point AS (
    SELECT AVG(ST_X(geom))::double precision AS mean_longitude,
           AVG(ST_Y(geom))::double precision AS mean_latitude,
           COUNT(*) AS location_count
    FROM eligible_locations
)
SELECT ST_X(p.geom)::double precision,
       ST_Y(p.geom)::double precision,
       mean_point.location_count
FROM eligible_locations AS p
CROSS JOIN mean_point
ORDER BY ST_Distance(
           p.geom::geography,
           ST_SetSRID(ST_MakePoint(mean_point.mean_longitude, mean_point.mean_latitude), 4326)::geography
         ), p.location_id
LIMIT 1
""".strip()

B03_MATCH_COUNT_SQL = """
SELECT COUNT(*)
FROM public.location AS l
JOIN public.collision AS c USING (location_id)
WHERE l.geom IS NOT NULL
  AND c.crash_date >= %s AND c.crash_date < %s
  AND ST_DWithin(
        l.geom::geography,
        ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography,
        %s
      )
""".strip()

VEHICLE_EXISTS_SQL = """
SELECT l.borough_id,
       COUNT(*) AS collision_count,
       SUM(s.persons_injured) AS persons_injured,
       SUM(s.persons_killed) AS persons_killed
FROM public.collision AS c
JOIN public.location AS l USING (location_id)
LEFT JOIN public.casualty_stat AS s USING (collision_id)
WHERE c.crash_date >= %s AND c.crash_date < %s
  AND EXISTS (
        SELECT 1
        FROM public.vehicle AS v
        WHERE v.collision_id = c.collision_id
          AND v.vehicle_type_id = %s
      )
GROUP BY l.borough_id
ORDER BY l.borough_id NULLS FIRST
""".strip()

VEHICLE_DISTINCT_SQL = """
SELECT l.borough_id,
       COUNT(*) AS collision_count,
       SUM(s.persons_injured) AS persons_injured,
       SUM(s.persons_killed) AS persons_killed
FROM public.collision AS c
JOIN public.location AS l USING (location_id)
JOIN (
        SELECT DISTINCT v.collision_id
        FROM public.vehicle AS v
        WHERE v.vehicle_type_id = %s
     ) AS matching_vehicle USING (collision_id)
LEFT JOIN public.casualty_stat AS s USING (collision_id)
WHERE c.crash_date >= %s AND c.crash_date < %s
GROUP BY l.borough_id
ORDER BY l.borough_id NULLS FIRST
""".strip()

CSV_FIELDS = (
    "benchmark", "condition", "condition_label", "phase", "iteration",
    "query_elapsed_ms", "explain_wall_ms", "planning_ms", "execution_ms",
    "shared_hit_blocks", "shared_read_blocks", "row_count", "result_sha256",
    "node_types", "index_names_used", "plan_file",
)


def _json_write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True, default=str)
        stream.write("\n")


def _json_read(value):
    if isinstance(value, str):
        return json.loads(value)
    return value


def _safe_query(connection, sql: str, parameters=()):
    return connection.execute(sql, parameters)


def _table_indexes(connection, table_name: str) -> list[dict]:
    rows = _safe_query(connection, """
        SELECT idx.relname,
               am.amname,
               i.indisprimary,
               i.indisunique,
               i.indisvalid,
               pg_get_indexdef(i.indexrelid),
               ARRAY(
                   SELECT COALESCE(a.attname, '<expression>')
                   FROM unnest(i.indkey::smallint[]) WITH ORDINALITY AS k(attnum, ord)
                   LEFT JOIN pg_attribute AS a
                     ON a.attrelid = i.indrelid AND a.attnum = k.attnum
                   WHERE k.ord <= i.indnkeyatts
                   ORDER BY k.ord
               ) AS key_columns
        FROM pg_index AS i
        JOIN pg_class AS idx ON idx.oid = i.indexrelid
        JOIN pg_am AS am ON am.oid = idx.relam
        JOIN pg_namespace AS ns ON ns.oid = idx.relnamespace
        WHERE i.indrelid = %s::regclass AND ns.nspname = 'public'
        ORDER BY idx.relname
    """, ("public." + table_name,)).fetchall()
    columns = ("name", "method", "primary", "unique", "valid", "definition", "key_columns")
    return [dict(zip(columns, row)) for row in rows]


def _constraint_snapshot(connection) -> list[dict]:
    rows = _safe_query(connection, """
        SELECT conname, contype, pg_get_constraintdef(oid)
        FROM pg_constraint
        WHERE conrelid = 'public.collision'::regclass AND contype IN ('p', 'u', 'f')
        ORDER BY conname
    """).fetchall()
    return [{"name": row[0], "type": row[1], "definition": row[2]} for row in rows]


def _catalog_snapshot(connection) -> dict:
    return {
        "collision_indexes": _table_indexes(connection, "collision"),
        "location_indexes": _table_indexes(connection, "location"),
        "collision_constraints": _constraint_snapshot(connection),
    }


def _index_by_name(indexes: list[dict], name: str) -> dict | None:
    return next((index for index in indexes if index["name"] == name), None)


def _require_regular_index(indexes: list[dict], name: str, table: str,
                           method: str, keys: list[str]) -> dict:
    index = _index_by_name(indexes, name)
    if (index is None or index["primary"] or index["unique"] or not index["valid"]
            or index["method"] != method or index["key_columns"] != keys):
        raise ValueError(f"索引 {name} 不符合预期；已停止以保护约束和数据。")
    definition = " ".join(index["definition"].lower().split())
    if table == "collision" and name == "ix_collision_date_id":
        if "crash_date desc, collision_id desc" not in definition:
            raise ValueError("日期复合索引定义与计划不符。")
    if table == "collision" and name == "ix_collision_location_date":
        if "(location_id, crash_date)" not in definition:
            raise ValueError("地点日期复合索引定义与计划不符。")
    if table == "location" and name == "ix_location_geography":
        if "geography" not in definition or "where" not in definition or "geom is not null" not in definition:
            raise ValueError("geography 索引定义与计划不符。")
    return index


def _validate_initial_layout(snapshot: dict) -> None:
    collision_indexes = snapshot["collision_indexes"]
    location_indexes = snapshot["location_indexes"]
    _require_regular_index(collision_indexes, "ix_collision_date_id", "collision", "btree",
                           ["crash_date", "collision_id"])
    _require_regular_index(collision_indexes, "ix_collision_location_date", "collision", "btree",
                           ["location_id", "crash_date"])
    _require_regular_index(location_indexes, "ix_location_geography", "location", "gist",
                           ["<expression>"])
    date_leading = [i["name"] for i in collision_indexes
                    if i["key_columns"] and i["key_columns"][0] == "crash_date"]
    location_leading = [i["name"] for i in collision_indexes
                        if i["key_columns"] and i["key_columns"][0] == "location_id"]
    geography_indexes = [i["name"] for i in location_indexes
                         if "geography" in i["definition"].lower()]
    if date_leading != ["ix_collision_date_id"]:
        raise ValueError("检测到额外的日期前导索引，无法构造无对应索引基线。")
    if location_leading != ["ix_collision_location_date"]:
        raise ValueError("检测到额外的地点前导索引，无法构造单列索引基线。")
    if geography_indexes != ["ix_location_geography"]:
        raise ValueError("检测到额外 geography 索引，无法构造无空间索引基线。")
    if _index_by_name(collision_indexes, "m7_bench_ix_collision_location"):
        raise ValueError("保留的 M7 临时索引名已被占用，停止实验。")
    if not snapshot["collision_constraints"]:
        raise ValueError("collision 表未发现主键、唯一键和外键约束。")


def _year_counts(connection) -> dict:
    collision_row = _safe_query(connection, """
        SELECT COUNT(*) AS all_rows,
               COUNT(*) FILTER (WHERE crash_date >= %s AND crash_date < %s) AS year_rows,
               MIN(crash_date) FILTER (WHERE crash_date >= %s AND crash_date < %s) AS year_min,
               MAX(crash_date) FILTER (WHERE crash_date >= %s AND crash_date < %s) AS year_max
        FROM public.collision
    """, (YEAR_START, YEAR_END, YEAR_START, YEAR_END, YEAR_START, YEAR_END)).fetchone()
    year_collisions = int(collision_row[1])
    if year_collisions < MIN_YEAR_COLLISIONS:
        raise ValueError(
            f"2025 年 collision 只有 {year_collisions} 条，低于要求的 {MIN_YEAR_COLLISIONS} 条；不生成不完整实验。"
        )
    counts = {
        "collision": {"all": int(collision_row[0]), "year_2025": year_collisions,
                      "year_min": collision_row[2].isoformat(), "year_max": collision_row[3].isoformat()},
    }
    for table in ("person", "vehicle", "collision_factor", "casualty_stat"):
        total = _safe_query(connection, f"SELECT COUNT(*) FROM public.{table}").fetchone()[0]
        year_total = _safe_query(connection, f"""
            SELECT COUNT(*)
            FROM public.{table} AS child
            JOIN public.collision AS c USING (collision_id)
            WHERE c.crash_date >= %s AND c.crash_date < %s
        """, (YEAR_START, YEAR_END)).fetchone()[0]
        counts[table] = {"all": int(total), "year_2025": int(year_total)}
    location_row = _safe_query(connection, """
        SELECT (SELECT COUNT(*) FROM public.location),
               (SELECT COUNT(DISTINCT c.location_id)
                FROM public.collision AS c
                WHERE c.crash_date >= %s AND c.crash_date < %s)
    """, (YEAR_START, YEAR_END)).fetchone()
    counts["location"] = {"all": int(location_row[0]), "used_by_2025_collisions": int(location_row[1])}
    return counts


def _source_files(connection) -> list[dict]:
    rows = _safe_query(connection, """
        SELECT DISTINCT item.file->>'source_kind', item.file->>'dataset_id',
               item.file->>'sha256', NULLIF(item.file->>'bytes', '')::bigint
        FROM public.import_batch AS b
        CROSS JOIN LATERAL jsonb_array_elements(
          CASE WHEN jsonb_typeof(b.input_manifest->'files') = 'array'
               THEN b.input_manifest->'files' ELSE '[]'::jsonb END
        ) AS item(file)
        WHERE b.status = 'SUCCEEDED'
          AND item.file->>'sha256' ~ '^[0-9a-f]{64}$'
        ORDER BY 1, 2, 3, 4
    """).fetchall()
    return [{"source_kind": row[0], "dataset_id": row[1], "sha256": row[2],
             "bytes": int(row[3]) if row[3] is not None else None} for row in rows]


def _discover_parameters(connection) -> dict:
    january_count = int(_safe_query(connection, """
        SELECT COUNT(*)
        FROM public.collision
        WHERE crash_date >= %s AND crash_date < %s
    """, (B01_START, B01_END)).fetchone()[0])
    if january_count < B01_PAGE_SIZE:
        raise ValueError(f"2025 年 1 月只有 {january_count} 条事故，无法执行 100 条分页对照。")
    location_row = _safe_query(connection, """
        SELECT c.location_id, COUNT(*) AS collision_count
        FROM public.collision AS c
        WHERE c.crash_date >= %s AND c.crash_date < %s
        GROUP BY c.location_id
        ORDER BY collision_count DESC, c.location_id
        LIMIT 1
    """, (YEAR_START, YEAR_END)).fetchone()
    vehicle_row = _safe_query(connection, """
        SELECT v.vehicle_type_id, COUNT(DISTINCT c.collision_id) AS collision_count
        FROM public.vehicle AS v
        JOIN public.collision AS c USING (collision_id)
        WHERE c.crash_date >= %s AND c.crash_date < %s
          AND v.vehicle_type_id IS NOT NULL
        GROUP BY v.vehicle_type_id
        ORDER BY collision_count DESC, v.vehicle_type_id
        LIMIT 1
    """, (YEAR_START, YEAR_END)).fetchone()
    center_row = _safe_query(connection, B03_CENTER_SQL, (YEAR_START, YEAR_END)).fetchone()
    if location_row is None or vehicle_row is None:
        raise ValueError("2025 年缺少地点或车型查询样本，无法执行完整 B01—B04。")
    if center_row is None or center_row[0] is None or center_row[1] is None or int(center_row[2]) == 0:
        raise ValueError("2025 年无可定位事故，无法执行 B03。")
    longitude, latitude = round(float(center_row[0]), 6), round(float(center_row[1]), 6)
    spatial_count = _require_b03_nonempty(_safe_query(connection, B03_MATCH_COUNT_SQL, (
        YEAR_START, YEAR_END, longitude, latitude, 200
    )).fetchone()[0])
    return {
        "date_range": {"start_inclusive": YEAR_START.isoformat(),
                       "end_exclusive": YEAR_END.isoformat(), "rows_scope": "2025 年"},
        "B01": {"query": "2025 年 1 月事故首屏，按日期、ID 倒序分页",
                "date_range": {"start_inclusive": B01_START.isoformat(),
                               "end_exclusive": B01_END.isoformat()},
                "page": 1, "page_size": B01_PAGE_SIZE, "matched_collision_count": january_count,
                "parameters": [B01_START.isoformat(), B01_END.isoformat()]},
        "B02": {"query": "单地点的 2025 年事故列表",
                "location_id": str(location_row[0]), "matched_collision_count": int(location_row[1]),
                "shared_index_control": "两种条件均临时关闭 B01 日期索引，隔离地点索引差异",
                "index_conditions": {"A": "location_id 单列索引", "B": "(location_id, crash_date) 复合索引"},
                "parameters": [str(location_row[0]), YEAR_START.isoformat(), YEAR_END.isoformat()]},
        "B03": {"query": "使用接口同款 ST_DWithin geography 谓词，按距离排序取前 101 条",
                "center_longitude": longitude, "center_latitude": latitude, "radius_m": 200,
                "center_method": "对 2025 年参与事故的不同 geocoded 地点求均值，再选距均值最近的真实地点；坐标四舍五入到 6 位小数",
                "eligible_geocoded_location_count": int(center_row[2]),
                "matched_collision_count_within_radius": spatial_count,
                "parameters": [YEAR_START.isoformat(), YEAR_END.isoformat(), longitude, latitude,
                               200, longitude, latitude]},
        "B04": {"query": "按最常见车型筛选事故，按 borough 汇总事故数和事故级伤亡总数",
                "vehicle_type_id": str(vehicle_row[0]), "matched_collision_count": int(vehicle_row[1]),
                "parameter_semantics": "筛中事故后，事故级 casualty_stat 每事故最多一行；比较 EXISTS 与 DISTINCT collision_id 子查询",
                "parameters_exists": [YEAR_START.isoformat(), YEAR_END.isoformat(), str(vehicle_row[0])],
                "parameters_distinct": [str(vehicle_row[0]), YEAR_START.isoformat(), YEAR_END.isoformat()]},
    }


def _require_b03_nonempty(match_count) -> int:
    count = int(match_count)
    if count <= 0:
        raise ValueError("B03 代表中心的 200 米范围内没有 2025 年事故，停止实验。")
    return count


def _memory_bytes() -> dict:
    if sys.platform == "win32":
        class MemoryStatus(ctypes.Structure):
            _fields_ = [
                ("dwLength", wintypes.DWORD), ("dwMemoryLoad", wintypes.DWORD),
                ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]
        try:
            status = MemoryStatus()
            status.dwLength = ctypes.sizeof(status)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return {"total_bytes": int(status.ullTotalPhys),
                        "available_bytes_at_capture": int(status.ullAvailPhys)}
        except (AttributeError, OSError):
            pass
    meminfo = Path("/proc/meminfo")
    if meminfo.exists():
        values = {}
        for line in meminfo.read_text(encoding="ascii").splitlines():
            key, _, rest = line.partition(":")
            if key in {"MemTotal", "MemAvailable"}:
                values[key] = int(rest.strip().split()[0]) * 1024
        if "MemTotal" in values:
            return {"total_bytes": values["MemTotal"],
                    "available_bytes_at_capture": values.get("MemAvailable")}
    return {"total_bytes": None, "available_bytes_at_capture": None}


def _docker_limits() -> dict | None:
    fmt = "{{.HostConfig.Memory}}|{{.HostConfig.NanoCpus}}|{{.HostConfig.MemorySwap}}|{{.HostConfig.CpuQuota}}|{{.HostConfig.CpuPeriod}}"
    try:
        result = subprocess.run(
            ["docker", "inspect", "--format", fmt, "vision-zero-dev-db"],
            capture_output=True, text=True, encoding="utf-8", timeout=10, check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    parts = result.stdout.strip().split("|")
    if len(parts) != 5:
        return None
    labels = ("memory_bytes", "nano_cpus", "memory_swap_bytes", "cpu_quota", "cpu_period")
    try:
        return {label: int(value) for label, value in zip(labels, parts)}
    except ValueError:
        return None


def _file_sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = __import__("hashlib").sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _code_metadata() -> dict:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT,
            capture_output=True, text=True, encoding="ascii", timeout=5, check=True,
        )
        commit = result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        commit = None
    sources = (BENCHMARK_SOURCE, Path(__file__), INDEX_SOURCE, STATISTICS_SOURCE, SPATIAL_SOURCE)
    return {
        "git_commit": commit,
        "sha256_by_source_file": {
            path.relative_to(PROJECT_ROOT).as_posix(): _file_sha256(path) for path in sources
        },
    }


def _environment(connection, database: str, output_dir: Path) -> dict:
    db_row = _safe_query(connection, """
        SELECT current_database(), current_setting('server_version'), postgis_full_version()
    """).fetchone()
    if db_row[0] != database:
        raise ValueError("连接实际数据库与请求的随机测试库不同。")
    settings_row = _safe_query(connection, """
        SELECT current_setting('shared_buffers'), current_setting('work_mem'),
               current_setting('effective_cache_size'), current_setting('random_page_cost'),
               current_setting('seq_page_cost')
    """).fetchone()
    disk = shutil.disk_usage(output_dir)
    return {
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "database": {"name": db_row[0], "postgres_version": db_row[1], "postgis_full_version": db_row[2],
                     "statement_timeout_ms": STATEMENT_TIMEOUT_MS,
                     "planner_settings": {"shared_buffers": settings_row[0], "work_mem": settings_row[1],
                                          "effective_cache_size": settings_row[2],
                                          "random_page_cost": settings_row[3], "seq_page_cost": settings_row[4]}},
        "python": {"version": sys.version, "implementation": platform.python_implementation()},
        "host": {"os": platform.platform(), "architecture": platform.machine(),
                 "cpu": platform.processor() or None, "logical_cpus": os.cpu_count(),
                 "memory": _memory_bytes(),
                 "result_storage": {"free_bytes_at_capture": int(disk.free),
                                    "total_bytes": int(disk.total)},
                 "database_container_limits": _docker_limits()},
        "code": _code_metadata(),
        "measurement": {"warmup_repeats_per_condition": WARMUP_REPEATS,
                        "measured_repeats_per_condition": MEASURE_REPEATS,
                        "schedule": "A/B 交替；每个条件先预热，再交替测量",
                        "cache_note": "未清理数据库或操作系统缓存；结果属于交替热缓存条件，不声称冷缓存。"},
    }


def _configure_condition(connection, benchmark: str, condition: str) -> str:
    if benchmark == "B01":
        if condition == "A":
            connection.execute("DROP INDEX public.ix_collision_date_id")
            return "无 crash_date 前导二级索引"
        connection.execute("""
            CREATE INDEX ix_collision_date_id
            ON public.collision (crash_date DESC, collision_id DESC)
        """)
        return "crash_date、collision_id 日期复合索引"
    if benchmark == "B02":
        connection.execute("DROP INDEX IF EXISTS public.ix_collision_date_id")
        if condition == "A":
            connection.execute("DROP INDEX IF EXISTS public.ix_collision_location_date")
            connection.execute("DROP INDEX IF EXISTS public.m7_bench_ix_collision_location")
            connection.execute("""
                CREATE INDEX m7_bench_ix_collision_location
                ON public.collision (location_id)
            """)
            return "location_id 单列索引；共同关闭日期索引"
        connection.execute("DROP INDEX public.m7_bench_ix_collision_location")
        connection.execute("""
            CREATE INDEX ix_collision_location_date
            ON public.collision (location_id, crash_date)
        """)
        return "location_id、crash_date 复合索引；共同关闭日期索引"
    if benchmark == "B03":
        if condition == "A":
            connection.execute("DROP INDEX public.ix_location_geography")
            return "无匹配 geography GiST 索引"
        connection.execute("""
            CREATE INDEX ix_location_geography
            ON public.location USING gist ((geom::geography))
            WHERE geom IS NOT NULL
        """)
        return "geom::geography GiST 局部索引"
    if benchmark == "B04":
        return "EXISTS" if condition == "A" else "DISTINCT collision_id 子查询"
    raise ValueError(f"未知基准编号：{benchmark}")


def _query_for(benchmark: str, condition: str) -> str:
    if benchmark == "B01":
        return DATE_SQL
    if benchmark == "B02":
        return LOCATION_DATE_SQL
    if benchmark == "B03":
        return NEARBY_SQL
    if benchmark == "B04":
        return VEHICLE_EXISTS_SQL if condition == "A" else VEHICLE_DISTINCT_SQL
    raise ValueError(f"未知基准编号：{benchmark}")


def _parameters_for(benchmark: str, condition: str, params: dict) -> tuple:
    if benchmark == "B01":
        return B01_START, B01_END
    if benchmark == "B02":
        return int(params["B02"]["location_id"]), YEAR_START, YEAR_END
    if benchmark == "B03":
        item = params["B03"]
        common = (YEAR_START, YEAR_END, item["center_longitude"], item["center_latitude"], item["radius_m"])
        return common + (item["center_longitude"], item["center_latitude"])
    if benchmark == "B04":
        vehicle_type_id = int(params["B04"]["vehicle_type_id"])
        if condition == "A":
            return YEAR_START, YEAR_END, vehicle_type_id
        return vehicle_type_id, YEAR_START, YEAR_END
    raise ValueError(f"未知基准编号：{benchmark}")


def _plan_summary(document) -> dict:
    value = _json_read(document)
    if not isinstance(value, list) or not value or not isinstance(value[0], dict):
        raise ValueError("EXPLAIN 未返回预期的 JSON 计划。")
    root = value[0].get("Plan")
    if not isinstance(root, dict):
        raise ValueError("EXPLAIN JSON 缺少根计划。")
    node_types, index_names = set(), set()
    stack = [root]
    while stack:
        node = stack.pop()
        if node.get("Node Type"):
            node_types.add(node["Node Type"])
        if node.get("Index Name"):
            index_names.add(node["Index Name"])
        stack.extend(node.get("Plans", []))
    return {
        "document": value,
        "planning_ms": float(value[0].get("Planning Time", 0.0)),
        "execution_ms": float(value[0].get("Execution Time", 0.0)),
        "shared_hit_blocks": int(root.get("Shared Hit Blocks", 0)),
        "shared_read_blocks": int(root.get("Shared Read Blocks", 0)),
        "node_types": sorted(node_types),
        "index_names_used": sorted(index_names),
    }


def _run_one(connection, benchmark: str, condition: str, params: dict) -> dict:
    query = _query_for(benchmark, condition)
    arguments = _parameters_for(benchmark, condition, params)
    started = time.perf_counter()
    explain_row = connection.execute(
        "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + query, arguments
    ).fetchone()
    explain_wall_ms = (time.perf_counter() - started) * 1000
    plan = _plan_summary(explain_row[0])
    started = time.perf_counter()
    rows = connection.execute(query, arguments).fetchall()
    query_elapsed_ms = (time.perf_counter() - started) * 1000
    summary = result_summary(rows)
    return {
        **summary,
        "query_elapsed_ms": query_elapsed_ms,
        "explain_wall_ms": explain_wall_ms,
        "planning_ms": plan["planning_ms"],
        "execution_ms": plan["execution_ms"],
        "shared_hit_blocks": plan["shared_hit_blocks"],
        "shared_read_blocks": plan["shared_read_blocks"],
        "node_types": plan["node_types"],
        "index_names_used": plan["index_names_used"],
        "plan_document": plan["document"],
    }


def _record_sample(writer, stream, output_dir: Path, benchmark: str, condition: str,
                   condition_label: str, phase: str, iteration: int, result: dict) -> None:
    plan_relative = ""
    if phase == "measure":
        plan_path = Path("plans") / benchmark / f"{condition}_{iteration:02d}.json"
        _json_write(output_dir / plan_path, result["plan_document"])
        plan_relative = plan_path.as_posix()
    writer.writerow({
        "benchmark": benchmark,
        "condition": condition,
        "condition_label": condition_label,
        "phase": phase,
        "iteration": iteration,
        "query_elapsed_ms": f"{result['query_elapsed_ms']:.6f}",
        "explain_wall_ms": f"{result['explain_wall_ms']:.6f}",
        "planning_ms": f"{result['planning_ms']:.6f}",
        "execution_ms": f"{result['execution_ms']:.6f}",
        "shared_hit_blocks": result["shared_hit_blocks"],
        "shared_read_blocks": result["shared_read_blocks"],
        "row_count": result["row_count"],
        "result_sha256": result["sha256"],
        "node_types": ";".join(result["node_types"]),
        "index_names_used": ";".join(result["index_names_used"]),
        "plan_file": plan_relative,
    })
    stream.flush()


def _case_summary(samples: dict[str, list[dict]], labels: dict[str, str], correctness: dict) -> dict:
    result = {"equivalent_results": correctness, "conditions": {}}
    for condition in ("A", "B"):
        observed = samples[condition]
        result["conditions"][condition] = {
            "label": labels[condition],
            "measurements": len(observed),
            "query_elapsed_ms": {
                "median": round(median([x["query_elapsed_ms"] for x in observed]), 6),
                "p95": round(percentile([x["query_elapsed_ms"] for x in observed], 0.95), 6),
            },
            "explain_execution_ms": {
                "median": round(median([x["execution_ms"] for x in observed]), 6),
                "p95": round(percentile([x["execution_ms"] for x in observed], 0.95), 6),
            },
            "observed_node_types": sorted({node for x in observed for node in x["node_types"]}),
            "observed_index_names": sorted({index for x in observed for index in x["index_names_used"]}),
            "result": {"row_count": observed[-1]["row_count"], "sha256": observed[-1]["sha256"]},
        }
    result["A_over_B_query_median_ratio"] = round(
        result["conditions"]["A"]["query_elapsed_ms"]["median"]
        / max(result["conditions"]["B"]["query_elapsed_ms"]["median"], 0.000001), 6
    )
    return result


def _write_correctness(output_dir: Path, cases: dict, error_type: str | None = None,
                       rollback_verified: bool | None = None) -> None:
    _json_write(output_dir / "correctness.json", {
        "overall_pass": error_type is None and bool(cases) and all(
            case.get("passed") is True for case in cases.values()
        ),
        "status": "complete" if error_type is None else "incomplete",
        "completed_cases": cases,
        "error_type": error_type,
        "temporary_index_rollback_verified": rollback_verified,
        "result_comparison": "ordered row count and SHA-256; only summaries are persisted",
    })


def _write_summary(output_dir: Path, cases: dict, dataset: dict | None, error_type: str | None,
                   rollback_verified: bool | None) -> None:
    status = "完成" if error_type is None else "未完成"
    lines = [
        "# M7 B01—B04 数据库性能实验",
        "",
        f"状态：**{status}**。",
        "",
        f"数据范围固定为 2025 年（左闭右开），每条件预热 {WARMUP_REPEATS} 次、测量 {MEASURE_REPEATS} 次，A/B 交替。",
        "普通查询耗时包含客户端取回结果的时间；EXPLAIN ANALYZE 执行耗时单独记录。缓存未清理，因此不称为冷缓存。",
        "结果只保存计数和 SHA-256 摘要，不保存事故、人员、车辆或账号记录。",
        "",
    ]
    if dataset:
        lines.append(f"2025 年事故数：{dataset['counts']['collision']['year_2025']:,}；全库事故数：{dataset['counts']['collision']['all']:,}。")
        lines.append("")
    for benchmark, result in cases.items():
        lines.extend([f"## {benchmark}", ""])
        if result.get("conditions"):
            for condition in ("A", "B"):
                item = result["conditions"][condition]
                q = item["query_elapsed_ms"]
                e = item["explain_execution_ms"]
                indexes = ", ".join(item["observed_index_names"]) or "执行计划未显示索引扫描"
                lines.append(
                    f"- {condition}（{item['label']}）：普通查询 median {q['median']:.3f} ms、P95 {q['p95']:.3f} ms；"
                    f"EXPLAIN 执行 median {e['median']:.3f} ms、P95 {e['p95']:.3f} ms；观察到索引：{indexes}。"
                )
            lines.append(f"- A/B 普通查询中位数比：{result['A_over_B_query_median_ratio']:.4f}。这是本次环境的观测值，不外推为普遍加速结论。")
            lines.append(f"- 结果一致：{'通过' if result['equivalent_results'] else '失败'}；返回行数 {result['conditions']['A']['result']['row_count']:,}，仅保存摘要哈希。")
        else:
            lines.append(f"- 状态：{result.get('status', '尚未运行')}。")
        lines.append("")
    lines.extend([
        f"临时索引事务回滚并与初始目录核对：{'通过' if rollback_verified else '未确认'}。",
        "",
        "执行计划保存在 `plans/`，逐次耗时保存在 `timings.csv`；完整环境和数据摘要见 JSON 文件。",
    ])
    if error_type:
        lines.extend(["", f"实验中止类型：`{error_type}`。异常详细文本未写入结果，避免把查询或连接信息带入证据目录。"])
    with (output_dir / "summary.md").open("x", encoding="utf-8", newline="\n") as stream:
        stream.write("\n".join(lines) + "\n")


def _load_admin_connect():
    backend = str(BACKEND_ROOT)
    if backend not in sys.path:
        sys.path.insert(0, backend)
    from app.db.provision import admin_connect
    return admin_connect


def run(database: str, output_dir: Path) -> None:
    database = validate_database_name(database)
    admin_connect = _load_admin_connect()
    connection = admin_connect(database)
    connection.prepare_threshold = None
    cases: dict[str, dict] = {}
    dataset = None
    initial_catalog = None
    rollback_verified = False
    error: Exception | None = None
    csv_stream = None
    try:
        connection.execute(f"SET LOCAL statement_timeout = '{STATEMENT_TIMEOUT_MS}ms'")
        connection.execute("SET LOCAL lock_timeout = '5s'")
        actual_database = connection.execute("SELECT current_database()").fetchone()[0]
        if actual_database != database:
            raise ValueError("连接目标与批准的随机测试库不一致。")
        initial_catalog = _catalog_snapshot(connection)
        _validate_initial_layout(initial_catalog)
        counts = _year_counts(connection)
        sources = _source_files(connection)
        dataset = {"date_range": {"start_inclusive": YEAR_START.isoformat(),
                                   "end_exclusive": YEAR_END.isoformat()},
                   "counts": counts, "source_files": sources,
                   "source_file_hashes_available": bool(sources),
                   "initial_indexes": {"collision": initial_catalog["collision_indexes"],
                                       "location": initial_catalog["location_indexes"]},
                   "collision_integrity_constraints": initial_catalog["collision_constraints"]}
        params = _discover_parameters(connection)
        environment = _environment(connection, database, output_dir)
        _json_write(output_dir / "environment.json", environment)
        _json_write(output_dir / "dataset_manifest.json", dataset)
        _json_write(output_dir / "query_parameters.json", params)
        csv_stream = (output_dir / "timings.csv").open("x", encoding="utf-8", newline="")
        writer = csv.DictWriter(csv_stream, fieldnames=CSV_FIELDS)
        writer.writeheader()
        csv_stream.flush()

        for benchmark in ("B01", "B02", "B03", "B04"):
            labels: dict[str, str] = {}
            samples = {"A": [], "B": []}
            warmup_summaries = {"A": [], "B": []}
            cases[benchmark] = {"status": "running"}
            for phase, repetitions in (("warmup", WARMUP_REPEATS), ("measure", MEASURE_REPEATS)):
                for iteration in range(1, repetitions + 1):
                    pair_summaries = {}
                    for condition in ("A", "B"):
                        labels[condition] = _configure_condition(connection, benchmark, condition)
                        result = _run_one(connection, benchmark, condition, params)
                        pair_summaries[condition] = {"row_count": result["row_count"],
                                                     "sha256": result["sha256"]}
                        _record_sample(writer, csv_stream, output_dir, benchmark, condition,
                                       labels[condition], phase, iteration, result)
                        if phase == "measure":
                            samples[condition].append(result)
                        else:
                            warmup_summaries[condition].append(pair_summaries[condition])
                    if not equivalent_results(pair_summaries["A"], pair_summaries["B"]):
                        cases[benchmark] = {
                            "passed": False,
                            "status": f"{phase} 轮次 {iteration} 的 A/B 查询结果不一致",
                            "A": pair_summaries["A"], "B": pair_summaries["B"],
                        }
                        raise ValueError(f"{benchmark} 两种实现结果不一致，已停止后续实验。")
            # 测量阶段逐对校验；另外确认预热结果也在每次 A/B 之间一致。
            result = _case_summary(samples, labels, True)
            result["warmup_results_equivalent"] = all(
                equivalent_results(warmup_summaries["A"][i], warmup_summaries["B"][i])
                for i in range(WARMUP_REPEATS)
            )
            result["passed"] = result["warmup_results_equivalent"] and all(
                equivalent_results(
                    {"row_count": samples["A"][i]["row_count"], "sha256": samples["A"][i]["sha256"]},
                    {"row_count": samples["B"][i]["row_count"], "sha256": samples["B"][i]["sha256"]},
                ) for i in range(MEASURE_REPEATS)
            )
            cases[benchmark] = result
            if not result["passed"]:
                raise ValueError(f"{benchmark} 全部测量结果一致性检查失败。")
            if benchmark == "B02":
                # 后续 B03/B04 回到其余初始索引环境；最终仍由事务回滚恢复数据库。
                connection.execute("""
                    CREATE INDEX ix_collision_date_id
                    ON public.collision (crash_date DESC, collision_id DESC)
                """)

        connection.rollback()
        restored_catalog = _catalog_snapshot(connection)
        rollback_verified = restored_catalog == initial_catalog
        connection.rollback()
        if not rollback_verified:
            raise RuntimeError("索引目录回滚后与初始状态不一致。")
        _write_correctness(output_dir, cases, rollback_verified=rollback_verified)
        _write_summary(output_dir, cases, dataset, None, rollback_verified)
    except Exception as exc:
        error = exc
        try:
            connection.rollback()
            if initial_catalog is not None:
                restored_catalog = _catalog_snapshot(connection)
                rollback_verified = restored_catalog == initial_catalog
                connection.rollback()
        except Exception:
            rollback_verified = False
        if not (output_dir / "correctness.json").exists():
            _write_correctness(output_dir, cases, type(exc).__name__, rollback_verified)
        if not (output_dir / "summary.md").exists():
            _write_summary(output_dir, cases, dataset, type(exc).__name__, rollback_verified)
    finally:
        if csv_stream is not None:
            csv_stream.close()
        connection.close()
    if error is not None:
        raise RuntimeError(type(error).__name__) from None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="在指定随机测试库执行 M7 B01—B04 性能对照实验。")
    parser.add_argument("--database", required=True, help="vision_zero_m1_test_<12位小写十六进制>")
    parser.add_argument("--output", required=True, help="新建或空的本地结果目录；非空目录会被拒绝")
    args = parser.parse_args(argv)
    output_dir = None
    try:
        database = validate_database_name(args.database)
        output_dir = prepare_output_dir(args.output)
        run(database, output_dir)
    except Exception as exc:
        if output_dir is not None:
            if not (output_dir / "correctness.json").exists():
                _write_correctness(output_dir, {}, type(exc).__name__, None)
            if not (output_dir / "summary.md").exists():
                _write_summary(output_dir, {}, None, type(exc).__name__, None)
        print(f"M7 性能实验未完成（{type(exc).__name__}）；如已创建结果目录，请检查其中的 summary.md。",
              file=sys.stderr)
        return 1
    print(f"M7 B01—B04 完成；聚合结果保存在：{output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
