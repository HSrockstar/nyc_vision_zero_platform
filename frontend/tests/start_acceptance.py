"""启动绑定独立合成库的本机服务，不修改配置或停止其他服务。"""
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / ".m6-work/frontend-refactor"
data = json.loads((OUTPUT / "browser-private.json").read_text(encoding="utf-8"))
if not data.get("synthetic_only") or not data["database"].startswith("vision_zero_m1_test_"):
    raise RuntimeError("验收服务只允许明确标记的独立合成库。")
values = {k: v for k, v in dotenv_values(data["config_file"]).items() if k.startswith("VISION_ZERO_")}
if values.get("VISION_ZERO_DATABASE_NAME") != data["database"]:
    raise RuntimeError("隔离数据库名称不一致。")
env = {**os.environ, **values, "VISION_ZERO_RUN_DB_TESTS": "1", "VISION_ZERO_TEST_CONFIG_FILE": data["config_file"],
       "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1"}
for port in (8006, 5176):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", port))
flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
def start(args, cwd, childenv, name):
    with (OUTPUT / (name + ".log")).open("wb") as log:
        return subprocess.Popen(args, cwd=cwd, env=childenv, stdout=log, stderr=subprocess.STDOUT, creationflags=flags)
backend = start([sys.executable, "-X", "utf8", "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8006"], ROOT / "backend", env, "backend")
frontend = start(["node", str(ROOT / "frontend/node_modules/vite/bin/vite.js"), "--host", "127.0.0.1", "--port", "5176", "--strictPort"], ROOT / "frontend", {**os.environ, "VISION_ZERO_API_TARGET": "http://127.0.0.1:8006"}, "frontend")
state = {"backend_pid": backend.pid, "frontend_pid": frontend.pid, "base_url": data["base_url"], "database": data["database"], "synthetic_only": True}
(OUTPUT / "processes.json").write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
for _ in range(60):
    if backend.poll() is not None or frontend.poll() is not None:
        raise RuntimeError("验收服务提前结束，请查看本轮日志。")
    try:
        with urllib.request.urlopen("http://127.0.0.1:8006/health/ready", timeout=2) as response:
            assert response.status == 200
        with urllib.request.urlopen(data["base_url"], timeout=2) as response:
            assert response.status == 200
        print(json.dumps({**state, "ready": True}))
        break
    except (OSError, AssertionError):
        time.sleep(.5)
else:
    raise RuntimeError("验收服务未在限定时间就绪。")
