"""下载固定纽约官方数据集；保存原始 CSV、分页检查点及计数证据。"""

import argparse
import csv
import hashlib
import io
import json
from pathlib import Path
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
SETS = {"CRASHES": ("h9gi-nx95", "collision_id"), "PERSON": ("f55k-p6yu", "unique_id"), "VEHICLES": ("bm4k-52h4", "unique_id")}


def fetch(dataset, suffix, query):
    url = f"https://data.cityofnewyork.us/resource/{dataset}.{suffix}?" + urlencode(query)
    for attempt in range(5):
        try:
            with urlopen(Request(url, headers={"User-Agent": "VisionZero-Course/1.0"}), timeout=90) as response:
                return response.read()
        except HTTPError as error:
            if error.code not in (429, 500, 502, 503, 504) or attempt == 4:
                raise RuntimeError(f"官方接口返回 HTTP {error.code}") from None
            time.sleep(min(30, 2 ** attempt * 2))
        except (URLError, TimeoutError):
            if attempt == 4: raise RuntimeError("官方接口连接超时") from None
            time.sleep(2 ** attempt * 2)


def count(dataset, condition):
    return int(json.loads(fetch(dataset, "json", {"$select": "count(*) as n", "$where": condition}))[0]["n"])


def download(scope):
    directory = ROOT / "data/raw/official" / scope
    directory.mkdir(parents=True, exist_ok=True)
    start, end = "2025-01-01T00:00:00", "2026-01-01T00:00:00" if scope == "year2025" else "2025-02-01T00:00:00"
    condition = f"crash_date >= '{start}' AND crash_date < '{end}'"
    parent_ids = None
    if scope == "first500":
        selected = json.loads(fetch(SETS["CRASHES"][0], "json", {"$select": "collision_id", "$where": condition, "$order": "crash_date,collision_id", "$limit": 500}))
        parent_ids = [int(row["collision_id"]) for row in selected]
        if len(parent_ids) != 500: raise RuntimeError("首批事故数量不足500")
    manifest = {"scope": scope, "start": start[:10], "end": end[:10], "files": [], "selected_collision_ids": parent_ids,
                "method": "官方CSV；稳定来源键分页；下载前后计数一致且键唯一", "verified_complete": False}
    for kind, (dataset, key) in SETS.items():
        where = f"collision_id in ({','.join(map(str, parent_ids))})" if parent_ids is not None else condition
        before = count(dataset, where)
        target = directory / (kind + ".csv")
        checkpoint = directory / (kind + "-checkpoint.json")
        rows, last, headers = 0, 0, None
        keys = set()
        # 未完成文件保留；新一次下载使用临时文件，完整核验后替换对应下载输出。
        temporary = directory / (kind + ".download.csv")
        with temporary.open("w", encoding="utf-8", newline="") as stream:
            writer = None
            while True:
                body = fetch(dataset, "csv", {"$where": f"({where}) AND {key} > {last}", "$order": key, "$limit": 5000})
                page = csv.DictReader(io.StringIO(body.decode("utf-8-sig"), newline=""))
                if headers is None:
                    headers = page.fieldnames
                    if not headers or key not in headers: raise RuntimeError("官方CSV表头变化")
                    writer = csv.DictWriter(stream, fieldnames=headers)
                    writer.writeheader()
                elif headers != page.fieldnames: raise RuntimeError("分页表头不一致")
                chunk = list(page)
                if not chunk: break
                for row in chunk:
                    number = int(row[key])
                    if number <= last or number in keys: raise RuntimeError("分页来源键不递增或重复")
                    keys.add(number)
                    last = number
                    writer.writerow(row)
                rows += len(chunk)
                stream.flush()
                checkpoint.write_text(json.dumps({"dataset_id": dataset, "rows": rows, "last_key": str(last), "complete": False}), encoding="utf-8")
                print(json.dumps({"source_kind": kind, "downloaded": rows, "expected": before}), flush=True)
                if len(chunk) < 5000: break
        after = count(dataset, where)
        if before != after or rows != before or rows != len(keys): raise RuntimeError("官方计数变化或下载不完整，文件未登记为完整")
        temporary.replace(target)
        sha = hashlib.file_digest(target.open("rb"), "sha256").hexdigest()
        file = {"source_kind": kind, "dataset_id": dataset, "source_url": f"https://data.cityofnewyork.us/resource/{dataset}.csv",
                "filename": target.name, "rows": rows, "count_before": before, "count_after": after, "unique_keys": len(keys),
                "sha256": sha, "bytes": target.stat().st_size, "headers": headers}
        manifest["files"].append(file)
        checkpoint.write_text(json.dumps({**file, "complete": True}, ensure_ascii=False, indent=2), encoding="utf-8")
        (directory / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest["verified_complete"] = True
    (directory / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"scope": scope, "verified_complete": True, "counts": {f["source_kind"]: f["rows"] for f in manifest["files"]}}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scope", choices=("first500", "year2025"), required=True)
    download(parser.parse_args().scope)
