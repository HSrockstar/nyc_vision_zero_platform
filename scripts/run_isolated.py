"""前台启动已通过恢复验收的隔离库服务，不切换开发库配置。"""

import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import Settings, workspace_path
from app.maintenance import (
    MaintenanceError, assert_local_container, isolated_environment, require_database, root_values,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("backend", "worker"))
    parser.add_argument("--database", required=True)
    parser.add_argument("--port", type=int, default=8002)
    parser.add_argument("--once", action="store_true", help="worker仅尝试领取一次任务")
    args = parser.parse_args()
    try:
        require_database(args.database, target=True)
        if not 1024 <= args.port <= 65535 or (args.once and args.action != "worker"):
            raise MaintenanceError("ISOLATED_ARGUMENT_INVALID")
        proof = workspace_path(ROOT / ".m7-work/restores" / args.database / "verification.json")
        verified = json.loads(proof.read_text(encoding="utf-8"))
        if verified.get("status") != "completed" or verified.get("database") != args.database:
            raise MaintenanceError("RESTORE_NOT_VERIFIED")
        config = workspace_path(ROOT / ".m1-work/model" / (args.database + ".env"))
        assert_local_container(root_values())
        with isolated_environment(config):
            settings = Settings()
            settings.connection_url(worker=args.action == "worker")
            command = (["-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(args.port)]
                       if args.action == "backend" else ["-m", "app.worker", *(["--once"] if args.once else [])])
            print(f"启动隔离服务：{args.action} / {args.database}；Ctrl+C停止。", flush=True)
            return subprocess.call([sys.executable, "-X", "utf8", *command], cwd=ROOT / "backend")
    except KeyboardInterrupt:
        return 130
    except Exception as error:
        print("隔离服务未启动：" + (str(error) if isinstance(error, MaintenanceError) else "配置或恢复证据检查失败"))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
