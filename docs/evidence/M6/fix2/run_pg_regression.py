"""一次全量真实PG回归；仅重定向测试的证据输出，不改变配置、数据库守卫或断言。"""
import json
import os
import sys
from pathlib import Path
import pytest

root = Path.cwd()
output = Path(sys.argv[1]).resolve()
output.mkdir(parents=True, exist_ok=True)
if (output / "collection.json").exists():
    raise RuntimeError("已有此轮回归证据，请指定新目录")
sys.path[:0] = [str(root / "backend"), str(root / "backend/tests")]
os.environ["VISION_ZERO_RUN_DB_TESTS"] = "1"
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

class EvidenceDestination:
    def pytest_collection_modifyitems(self, items):
        # 两个测试模块把证据写在固定历史路径；只重定向它们自己的模块变量。
        # app.config、连接设置、迁移配置、产品代码与测试函数均保持原样。
        import conftest
        conftest.PROJECT_ROOT = output
        for item in items:
            if item.module.__name__ == "test_database_integration":
                item.module.PROJECT_ROOT = output
        (output / "collection.json").write_text(json.dumps({
            "total": len(items),
            "m6_tests": [item.nodeid for item in items if "test_m6_statistics.py::" in item.nodeid],
            "historical_evidence_redirected": [".m2-work/schema-evidence.json", ".m2-work/migration-lifecycle.json"],
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

raise SystemExit(pytest.main(["backend/tests", "-v", "-p", "no:cacheprovider", "--tb=short"], plugins=[EvidenceDestination()]))
