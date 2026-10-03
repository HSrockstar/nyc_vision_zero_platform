"""纯逻辑基准工具：参数校验、结果摘要和统计，不连接数据库。"""

from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Iterable, Sequence


DATABASE_RE = re.compile(r"vision_zero_m1_test_[0-9a-f]{12}\Z")
YEAR_START = date(2025, 1, 1)
YEAR_END = date(2026, 1, 1)
B01_START = date(2025, 1, 1)
B01_END = date(2025, 2, 1)
B01_PAGE_SIZE = 100
MIN_YEAR_COLLISIONS = 85_546
WARMUP_REPEATS = 3
MEASURE_REPEATS = 20
STATEMENT_TIMEOUT_MS = 60_000


def validate_database_name(value: str) -> str:
    """仅接受本项目批准格式的随机测试库名，特别拒绝开发库。"""
    if not isinstance(value, str) or not DATABASE_RE.fullmatch(value):
        raise ValueError("数据库名必须是 vision_zero_m1_test_<12位小写十六进制>。")
    return value


def prepare_output_dir(value: str | Path) -> Path:
    """创建新结果目录；只允许复用空目录，并拒绝链接和覆盖已有结果。"""
    path = Path(value).expanduser()
    if path.is_symlink():
        raise ValueError("结果目录不能是符号链接。")
    if path.exists():
        if not path.is_dir() or any(path.iterdir()):
            raise FileExistsError("结果目录已存在且非空；请指定新的本地目录。")
    path.mkdir(parents=True, exist_ok=True)
    return path.resolve()


def _json_value(value):
    if isinstance(value, (date, datetime, time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, bytes):
        return value.hex()
    raise TypeError(f"不支持的结果值类型：{type(value).__name__}")


def result_summary(rows: Iterable[Sequence[object]]) -> dict:
    """对有序结果做稳定摘要；只返回行数和哈希，不保留或输出行内容。"""
    digest = hashlib.sha256()
    count = 0
    for row in rows:
        encoded = json.dumps(
            list(row), ensure_ascii=False, separators=(",", ":"), default=_json_value
        ).encode("utf-8")
        digest.update(encoded)
        digest.update(b"\n")
        count += 1
    return {"row_count": count, "sha256": digest.hexdigest()}


def percentile(values: Sequence[float], q: float) -> float:
    """Nearest-rank 分位数；P95 对 20 个观测取第 19 个有序值。"""
    if not values:
        raise ValueError("分位数至少需要一个观测值。")
    if not 0 < q <= 1:
        raise ValueError("分位数 q 必须在 (0, 1] 内。")
    ordered = sorted(float(value) for value in values)
    rank = max(1, math.ceil(q * len(ordered)))
    return ordered[rank - 1]


def median(values: Sequence[float]) -> float:
    if not values:
        raise ValueError("中位数至少需要一个观测值。")
    ordered = sorted(float(value) for value in values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def equivalent_results(left: dict, right: dict) -> bool:
    return left.get("row_count") == right.get("row_count") and left.get("sha256") == right.get("sha256")
