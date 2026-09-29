"""在一次性用途的 Linux 容器中验证同版本依赖、哈希重放与真实 PostGIS 连接。"""
import json
import pathlib
import platform
import subprocess
import sys

source = pathlib.Path("/validation")
evidence = pathlib.Path("/evidence")
evidence.mkdir(exist_ok=True)


def run(args, name):
    result = subprocess.run(args, capture_output=True, text=True)
    (evidence / (name + ".log")).write_text(result.stdout + result.stderr, encoding="utf-8")
    print(json.dumps({"step": name, "exit_code": result.returncode}), flush=True)
    if result.returncode:
        print(result.stderr[-2000:], flush=True)
        raise SystemExit(result.returncode)
    return result.stdout


run([sys.executable, "-m", "venv", "/tmp/m0-env"], "venv-create")
python = "/tmp/m0-env/bin/python"
constraints = pathlib.Path("/tmp/m0-constraints.txt")
constraints.write_text("\n".join(line.split(" --hash=")[0] for line in (source / "requirements-win-py312.lock").read_text().splitlines() if line and not line.startswith("#")), encoding="utf-8")
run([python, "-m", "pip", "install", "--only-binary=:all:", "--index-url", "https://pypi.org/simple", "--timeout", "20", "--retries", "1", "-r", str(source / "requirements.in"), "-c", str(constraints), "--report", str(evidence / "pip-install-report.json")], "pip-install-linux")
run([python, "-m", "pip", "check"], "pip-check-linux")
output = run([python, str(source / "python_smoke.py")], "python-smoke-linux")
(evidence / "python-smoke.json").write_text(output, encoding="utf-8")
report = json.loads((evidence / "pip-install-report.json").read_text())
lines = ["# Linux amd64 / CPython 3.12.4 / glibc; M0 actual installation hashes."]
for item in sorted(report["install"], key=lambda item: item["metadata"]["name"].lower()):
    name, version = item["metadata"]["name"], item["metadata"]["version"]
    sha256 = item["download_info"]["archive_info"]["hashes"]["sha256"]
    lines.append(f"{name}=={version} --hash=sha256:{sha256}")
lock = evidence / "requirements-linux-py312.lock"
lock.write_text("\n".join(lines) + "\n", encoding="utf-8")
# 第二个干净 venv 验证实际安装，覆盖 Linux 轮子差异，而非仅解析锁。
run([sys.executable, "-m", "venv", "/tmp/m0-replay"], "venv-replay-create")
run(["/tmp/m0-replay/bin/python", "-m", "pip", "install", "--require-hashes", "--index-url", "https://pypi.org/simple", "--timeout", "20", "--retries", "1", "-r", str(lock)], "pip-hash-replay-linux")
run(["/tmp/m0-replay/bin/python", "-m", "pip", "check"], "pip-check-replay-linux")
config = json.loads(pathlib.Path("/run/m0/credentials.json").read_text())
config.update(host="127.0.0.1", port=5432)
credentials = pathlib.Path("/tmp/m0-credentials.json")
credentials.write_text(json.dumps(config), encoding="utf-8")
run(["/tmp/m0-replay/bin/python", str(source / "database_smoke.py"), "--credentials", str(credentials), "--output", str(evidence / "database-smoke-linux.json")], "database-smoke-linux")
result = {"python": platform.python_version(), "platform": platform.platform(), "packages": len(report["install"]), "linux_hash_replay": "actual clean installation passed", "database_connection": "passed"}
(evidence / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
print(json.dumps(result), flush=True)
