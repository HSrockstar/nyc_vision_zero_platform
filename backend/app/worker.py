"""worker 当前仅提供连接预检入口，不处理导入或风险作业。"""

import json

from app.health import readiness


def main() -> int:
    body, status = readiness()
    print(json.dumps({"worker": "preflight_only", **body}, ensure_ascii=False))
    return 0 if status == 200 else 1


if __name__ == "__main__":
    raise SystemExit(main())
