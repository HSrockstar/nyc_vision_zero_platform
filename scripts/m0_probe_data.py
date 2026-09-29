"""M0 官方数据只读探测；不导入数据库，不下载完整数据集。"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

DATASETS = {
    "crashes": ("h9gi-nx95", "collision_id", "collision_id,crash_date,crash_time,borough,latitude,longitude,on_street_name,cross_street_name,number_of_persons_injured,number_of_persons_killed"),
    "person": ("f55k-p6yu", "unique_id", "unique_id,person_id,vehicle_id,collision_id,crash_date,person_type,person_injury"),
    "vehicles": ("bm4k-52h4", "unique_id", "unique_id,vehicle_id,collision_id,crash_date,vehicle_type"),
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--bounds-only", action="store_true", help="全表复杂聚合超时后，用独立日期边界查询核对")
    parser.add_argument("--quality-only", action="store_true", help="核对选定年份的键与地点质量，并保存 CSV 小样")
    parser.add_argument("--street-check", action="store_true", help="核对街道字段的名称与样本冲突")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    requests = []
    samples = {}

    def fetch(label: str, url: str):
        record = {"label": label, "url": url, "started_at": datetime.now(timezone.utc).isoformat()}
        body = b""
        try:
            with urlopen(Request(url, headers={"User-Agent": "VisionZero-Course-M0/1.0", "Accept": "application/json"}), timeout=20) as response:
                record["status"] = response.status
                record["headers"] = {k: v for k, v in response.headers.items() if k.lower() in {"content-type", "content-length", "last-modified", "etag", "retry-after", "x-soda2-fields", "x-soda2-types"}}
                body = response.read(5_000_001)
                if len(body) > 5_000_000:
                    raise ValueError("探测响应超过 5 MB 上限，禁止视为完整结果")
        except HTTPError as error:
            record["status"] = error.code
            record["error"] = str(error)
            body = error.read(100_000)
        except Exception as error:
            record["error"] = f"{type(error).__name__}: {error}"
        record["finished_at"] = datetime.now(timezone.utc).isoformat()
        record["body_sha256"] = hashlib.sha256(body).hexdigest()
        path = args.output / f"{label}.response.txt"
        path.write_bytes(body)
        record["body_file"] = path.name
        record["body_bytes"] = len(body)
        requests.append(record)
        print(json.dumps({k: record.get(k) for k in ("label", "status", "error", "body_bytes")}, ensure_ascii=False), flush=True)
        if record.get("status") == 200:
            if ".csv?" in url:
                return body.decode("utf-8-sig")
            try:
                return json.loads(body)
            except (ValueError, UnicodeError) as error:
                record["parse_error"] = str(error)
        return None

    for kind, (dataset_id, key, columns) in DATASETS.items():
        base = f"https://data.cityofnewyork.us/resource/{dataset_id}.json"
        if args.street_check:
            if kind != "crashes":
                continue
            scope = "crash_date >= '2025-01-01T00:00:00' AND crash_date < '2026-01-01T00:00:00'"
            fetch("street-presence", base + "?" + urlencode({"$select": "count(*) as rows,count(on_street_name) as on_present,count(off_street_name) as off_present,count(cross_street_name) as cross_present", "$where": scope}))
            fetch("street-example", base + "?" + urlencode({"$select": "collision_id,on_street_name,off_street_name,cross_street_name", "$where": "off_street_name IS NOT NULL", "$limit": "5"}))
            continue
        if args.quality_only:
            scope = "crash_date >= '2025-01-01T00:00:00' AND crash_date < '2026-01-01T00:00:00'"
            fetch(f"{kind}-year-keys", base + "?" + urlencode({"$select": f"count(*) as rows,count({key}) as key_present,count(distinct {key}) as key_distinct,count(collision_id) as parent_present", "$where": scope}))
            if kind == "crashes":
                fetch("crashes-missing-coordinates", base + "?" + urlencode({"$select": "count(*) as rows", "$where": scope + " AND (latitude IS NULL OR longitude IS NULL)"}))
                fetch("crashes-streets", base + "?" + urlencode({"$select": "collision_id,on_street_name,off_street_name,cross_street_name", "$where": scope + " AND off_street_name IS NOT NULL", "$order": "collision_id", "$limit": "5"}))
            fetch(f"{kind}-csv-sample", base.replace(".json", ".csv") + "?" + urlencode({"$select": columns, "$where": scope, "$order": f"crash_date,{key}", "$limit": "2"}))
            continue
        if args.bounds_only:
            for edge, direction in (("min", "ASC"), ("max", "DESC")):
                fetch(f"{kind}-date-{edge}", base + "?" + urlencode({"$select": "crash_date", "$where": "crash_date IS NOT NULL", "$order": f"crash_date {direction}", "$limit": "1"}))
            fetch(f"{kind}-count", base + "?" + urlencode({"$select": "count(*) as rows"}))
            continue
        metadata = fetch(f"{kind}-metadata", f"https://data.cityofnewyork.us/api/views/{dataset_id}.json")
        if isinstance(metadata, dict):
            fields = [{k: c.get(k) for k in ("name", "fieldName", "dataTypeName", "description")} for c in metadata.get("columns", []) if not c.get("fieldName", "").startswith(":" )]
            (args.output / f"{kind}-fields.json").write_text(json.dumps(fields, ensure_ascii=False, indent=2), encoding="utf-8")
        query = {"$select": columns, "$where": "crash_date >= '2025-01-01T00:00:00' AND crash_date < '2025-02-01T00:00:00'", "$order": f"crash_date,{key}", "$limit": "10"}
        sample = fetch(f"{kind}-sample", base + "?" + urlencode(query))
        if not isinstance(sample, list):
            # 访问被拒绝或网络失败后停止该资源的数据请求，不循环重试。
            continue
        samples[kind] = sample
        fetch(f"{kind}-aggregate", base + "?" + urlencode({"$select": f"count(*) as rows,min(crash_date) as min_date,max(crash_date) as max_date,count({key}) as key_present,count(distinct {key}) as key_distinct"}))
        for scope, end in (("january", "2025-02-01"), ("year2025", "2026-01-01")):
            select = "count(*) as rows"
            if kind == "crashes":
                select += ",count(latitude) as latitude_present,count(longitude) as longitude_present"
            fetch(f"{kind}-{scope}", base + "?" + urlencode({"$select": select, "$where": f"crash_date >= '2025-01-01T00:00:00' AND crash_date < '{end}T00:00:00'"}))

    parents = samples.get("crashes", [])
    if parents:
        parent_ids = [str(row["collision_id"]) for row in parents if str(row.get("collision_id", "")).isdigit()]
        for kind in ("person", "vehicles"):
            if kind not in samples or not parent_ids:
                continue
            dataset_id, key, columns = DATASETS[kind]
            child = fetch(f"{kind}-parent-linked", f"https://data.cityofnewyork.us/resource/{dataset_id}.json?" + urlencode({"$select": columns, "$where": f"collision_id in ({','.join(parent_ids)})", "$order": f"collision_id,{key}", "$limit": "1000"}))
            if isinstance(child, list):
                counts = Counter(str(r.get("collision_id")) for r in child)
                (args.output / f"{kind}-link-summary.json").write_text(json.dumps({"parent_sample_count": len(parent_ids), "child_rows": len(child), "possibly_truncated": len(child) == 1000, "parents_with_child": sum(i in counts for i in parent_ids), "child_keys_missing": sum(key not in r for r in child), "child_keys_distinct": len({r.get(key) for r in child}), "date_mismatches": sum(r.get("crash_date") != p.get("crash_date") for r in child for p in parents if str(r.get("collision_id")) == str(p.get("collision_id")))}, ensure_ascii=False, indent=2), encoding="utf-8")
    (args.output / "requests.json").write_text(json.dumps(requests, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
