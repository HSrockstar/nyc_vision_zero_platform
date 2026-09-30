"""导入与M4风险worker；--once适合本机逐步验收。"""

import json
import argparse
import time

from app.health import readiness
from app.importing.jobs import run_once
from app.risks import run_once as risk_once


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--preflight", action="store_true")
    parser.add_argument("--kind", choices=("all", "imports", "risks"), default="all")
    args = parser.parse_args()
    body, status = readiness(worker=True)
    if status != 200 or args.preflight:
        print(json.dumps(body, ensure_ascii=False))
        return 0 if status == 200 else 1
    try:
        while True:
            result = run_once() if args.kind != "risks" else {"status": "idle", "processed": False}
            risk_result = risk_once() if args.kind != "imports" else {"status": "idle", "processed": False}
            if result["status"] != "failed" and (not result["processed"] or risk_result["processed"] or risk_result["status"] == "failed"):
                result = risk_result
            if args.once or result["processed"] or result["status"] == "failed":
                print(json.dumps(result, ensure_ascii=False), flush=True)
            if args.once: return 1 if result["status"] == "failed" else 0
            time.sleep(2 if result["processed"] else 5)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
