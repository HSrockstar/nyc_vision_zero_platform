"""运行独立PG回归并另存证据，不覆盖M1—M6的历史验证材料。"""

import argparse
import json
import os
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, help='仓库内的新证据目录')
    parser.add_argument('tests', nargs='*', default=['backend/tests'])
    args = parser.parse_args()
    output = (ROOT / args.output).resolve()
    output.relative_to(ROOT)
    if output.exists():
        raise ValueError('证据目录已存在，请指定新轮次')
    output.mkdir(parents=True)
    sys.path[:0] = [str(ROOT / 'backend'), str(ROOT / 'backend/tests')]
    os.environ['VISION_ZERO_RUN_DB_TESTS'] = '1'
    os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
    os.chdir(ROOT)

    class EvidenceDestination:
        def pytest_collection_modifyitems(self, items):
            import conftest
            conftest.PROJECT_ROOT = output
            for item in items:
                if item.module.__name__ == 'test_database_integration':
                    item.module.PROJECT_ROOT = output
            (output / 'collection.json').write_text(json.dumps({
                'total': len(items), 'nodeids': [item.nodeid for item in items],
                'historical_evidence_redirected': ['.m2-work/schema-evidence.json', '.m2-work/migration-lifecycle.json']
            }, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    return pytest.main([*args.tests, '-v', '-p', 'no:cacheprovider', '--tb=short',
                       '--junitxml=' + str(output / 'junit.xml')], plugins=[EvidenceDestination()])


if __name__ == '__main__':
    raise SystemExit(main())
