"""检查原有修改与历史证据保留；不修改Git索引、配置或业务数据。"""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

root = Path.cwd()
work = root / ".m6-work/fix2"
evidence = root / "docs/evidence/M6/fix2"
output = Path(sys.argv[1]) if len(sys.argv) > 1 else evidence / "final-checks.json"
if output.exists():
    raise RuntimeError("已有最终检查证据，请另存轮次")

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest().upper()

def git(args):
    return subprocess.run(["git", *args], cwd=root, capture_output=True)

historical = []
for manifest in ("historical-hashes.json", "review2-hashes.json"):
    for entry in json.loads((work / manifest).read_text(encoding="utf-8-sig")):
        historical.append({"path": entry["Path"], "unchanged": sha(entry["Path"]) == entry["Hash"]})
before = json.loads((evidence / "development-before.json").read_text(encoding="utf-8"))
after = json.loads((evidence / "development-after-final.json").read_text(encoding="utf-8"))
tracked = git(["diff", "--binary"])
initial = (work / "initial-tracked.diff").read_bytes()
status = git(["status", "--porcelain=v1"])
initial_status = (work / "initial-status.txt").read_text(encoding="utf-8-sig").splitlines()
current_status = status.stdout.decode("utf-8").splitlines()
default_check = git(["diff", "--check"])
crlf_check = git(["-c", "core.whitespace=blank-at-eol,blank-at-eof,cr-at-eol", "diff", "--check"])
(evidence / (output.stem + "-git-diff-check.log")).write_bytes(default_check.stdout + default_check.stderr)
(evidence / (output.stem + "-git-status.txt")).write_bytes(status.stdout)
empty = work / "empty-for-diff.txt"
empty.write_bytes(b"")
task_checks = []
for file in [root / "frontend/src/components/StatisticsPanel.vue", root / "docs/milestones/M6.md", root / "docs/milestones/M6-demo.md", *evidence.glob("*.py"), *evidence.glob("*.cjs")]:
    checked = git(["-c", "core.whitespace=blank-at-eol,blank-at-eof,cr-at-eol", "diff", "--no-index", "--check", "--", str(empty), str(file)])
    diagnostic = (checked.stdout + checked.stderr).decode("utf-8", errors="replace")
    # --no-index隐含--exit-code；1且无诊断仅表示文件不同，不是空白错误。
    task_checks.append({"file": str(file), "exit_code": checked.returncode, "output": diagnostic,
                        "whitespace_ok": checked.returncode in (0, 1) and not diagnostic.strip()})
result = {
    "development_unchanged": before == after,
    "historical_files_checked": len(historical),
    "historical_files_unchanged": all(item["unchanged"] for item in historical),
    "historical_changes": [item for item in historical if not item["unchanged"]],
    "preexisting_tracked_diff_unchanged": tracked.stdout == initial,
    "preexisting_status_preserved": set(initial_status).issubset(current_status),
    "git_status_exit_code": status.returncode,
    "git_diff_check_default_exit_code": default_check.returncode,
    "git_diff_check_allow_crlf_exit_code": crlf_check.returncode,
    "task_file_whitespace_checks": task_checks,
    "note": "默认diff --check对既有CRLF增量报尾空白；仅本次命令允许CRLF后核查，不修改全局Git配置，不清理用户原有修改。",
    "commit_or_push_executed": False,
}
output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps(result, ensure_ascii=False, indent=2))
raise SystemExit(0 if result["development_unchanged"] and result["historical_files_unchanged"] and result["preexisting_tracked_diff_unchanged"] and result["preexisting_status_preserved"] and crlf_check.returncode == 0 and all(c["whitespace_ok"] for c in task_checks) else 1)
