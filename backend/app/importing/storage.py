"""CSV只写入仓库内批准数据库的随机目录；文件名不取客户端路径。"""

import csv
import hashlib
from pathlib import Path
from uuid import uuid4
import shutil
from threading import Lock

from app.config import PROJECT_ROOT, Settings, workspace_path
from app.importing.cleaning import ImportProblem, KINDS, MAPPING, resolve_headers

MAX_BYTES = 256 * 1024 * 1024
MAX_ROWS = 3_000_000
MAX_STORED_BYTES = 4 * 1024 * 1024 * 1024
storage_lock = Lock()
csv.field_size_limit(1024 * 1024)


def storage_directory(key, settings=None):
    settings = settings or Settings()
    settings.connection_url()  # 不接受未批准的数据库命名空间。
    if len(key) != 32 or any(character not in "0123456789abcdef" for character in key):
        raise ImportProblem("STORAGE_REFERENCE_INVALID")
    return workspace_path(PROJECT_ROOT / "data/raw" / settings.database_name / key)


def file_hash(path):
    result = hashlib.sha256()
    with workspace_path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def csv_rows(path):
    try:
        with workspace_path(path).open("r", encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream, strict=True)
            if not reader.fieldnames or len(reader.fieldnames) > 128:
                raise ImportProblem("CSV_HEADERS_INVALID")
            for index, row in enumerate(reader, start=1):
                if index > MAX_ROWS:
                    raise ImportProblem("CSV_ROW_LIMIT")
                if None in row or any(value is None for value in row.values()):
                    raise ImportProblem("CSV_MALFORMED")
                yield index, row
    except (UnicodeError, csv.Error, OSError):
        raise ImportProblem("CSV_READ_FAILED") from None


def discard_files(key):
    """只清理本次尚未登记的随机目录；复核每个固定文件不含链接。"""
    directory = storage_directory(key)
    if not directory.exists(): return
    for item in directory.iterdir():
        workspace_path(item)
        if item.name not in {kind + ".csv" for kind in KINDS} or not item.is_file():
            raise ImportProblem("STORAGE_REFERENCE_INVALID")
    shutil.rmtree(directory)


def stored_bytes():
    root = workspace_path(PROJECT_ROOT / "data/raw" / Settings().database_name)
    if not root.exists(): return 0
    total = 0
    for directory in root.iterdir():
        workspace_path(directory)
        if not directory.is_dir(): continue
        for kind in KINDS:
            path = workspace_path(directory / (kind + ".csv"))
            if path.exists(): total += path.stat().st_size
    return total


def save_files(streams, mode="auto"):
    key = uuid4().hex
    with storage_lock:
        if stored_bytes() + MAX_BYTES > MAX_STORED_BYTES:
            raise ImportProblem("STORAGE_QUOTA_EXCEEDED")
        try:
            return _save_files(streams, mode, key)
        except Exception:
            discard_files(key)
            raise


def _save_files(streams, mode, key):
    """streams为三个(kind,二进制流,原文件名)；CLI也必须先校验输入路径。"""
    if mode not in ("api", "display", "auto") or {item[0] for item in streams} != set(KINDS) or len(streams) != 3:
        raise ImportProblem("THREE_CSV_FILES_REQUIRED")
    directory = storage_directory(key)
    directory.mkdir(parents=True, exist_ok=False)
    total = 0
    files = []
    for kind, stream, name in streams:
        name = str(name).replace("\\", "/").rsplit("/", 1)[-1]
        if not name.lower().endswith(".csv") or not 0 < len(name) <= 180 or any(ord(character) < 32 for character in name):
            raise ImportProblem("CSV_FILENAME_INVALID")
        path = workspace_path(directory / (kind + ".csv"))
        size = 0
        with path.open("xb") as target:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                size += len(block)
                total += len(block)
                if total > MAX_BYTES:
                    raise ImportProblem("UPLOAD_TOO_LARGE")
                target.write(block)
        if not size:
            raise ImportProblem("CSV_EMPTY_FILE")
        try:
            with path.open("r", encoding="utf-8-sig", newline="") as source:
                headers = next(csv.reader(source, strict=True))
            resolved, _ = resolve_headers(kind, headers, mode)
        except (UnicodeError, csv.Error, StopIteration):
            raise ImportProblem("CSV_HEADERS_INVALID") from None
        files.append({"source_kind": kind, "dataset_id": MAPPING[kind]["dataset_id"],
                      "original_name": name, "sha256": file_hash(path), "bytes": size,
                      "encoding": "utf-8-sig", "headers": headers, "header_mode": resolved})
    return {"storage_key": key, "files": files}


def verify_files(manifest):
    directory = storage_directory(manifest["storage_key"])
    if {file["source_kind"] for file in manifest["files"]} != set(KINDS):
        raise ImportProblem("SAVED_FILES_INVALID")
    for file in manifest["files"]:
        path = workspace_path(directory / (file["source_kind"] + ".csv"))
        if not path.is_file() or path.stat().st_size != file["bytes"] or file_hash(path) != file["sha256"]:
            raise ImportProblem("SAVED_FILES_CHANGED")
    return directory
