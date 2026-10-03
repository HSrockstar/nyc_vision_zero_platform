"""T28：终止持有租约的真实worker子进程，再启动新进程恢复。"""

import json
import os
from pathlib import Path
import subprocess
import sys
import time
from uuid import uuid4

from fastapi.testclient import TestClient

from app.config import BACKEND_ROOT
from app.main import app
from conftest import connect_as, seed_user
from test_m1_auth import login


def test_real_worker_process_restart_fences_abandoned_risk_job(isolated_db, tmp_path):
    with connect_as() as connection:
        _, username = seed_user(connection, role=2)
    with TestClient(app) as client:
        headers = login(client, username)

        def request_run():
            response = client.post('/api/v1/risk-runs', headers=headers, json={
                'request_id': str(uuid4()), 'rule_id': '1',
                'period_start': '2025-01-01', 'period_end': '2026-01-01'})
            assert response.status_code == 202, response.text
            return response.json()['data']['run_id']

        first = request_run()
        marker = tmp_path / 'claimed.json'
        child = tmp_path / 'pause_claimed_worker.py'
        child.write_text('''import json, sys, time
from pathlib import Path
from app import risks
from app.worker import main
marker = Path(sys.argv[1])
def pause(engine, run_id, token):
    marker.write_text(json.dumps({'run_id': str(run_id)}), encoding='utf-8')
    time.sleep(120)
    raise RuntimeError('test pause elapsed')
risks.calculate = pause
sys.argv = ['app.worker', '--once', '--kind', 'risks']
raise SystemExit(main())
''', encoding='utf-8')
        environment = dict(os.environ, PYTHONPATH=str(BACKEND_ROOT), PYTHONDONTWRITEBYTECODE='1')
        with (tmp_path / 'abandoned-worker.log').open('wb') as output:
            process = subprocess.Popen([sys.executable, '-X', 'utf8', str(child), str(marker)],
                cwd=BACKEND_ROOT, env=environment, stdout=output, stderr=subprocess.STDOUT)
            try:
                deadline = time.monotonic() + 30
                while not marker.exists() and process.poll() is None and time.monotonic() < deadline:
                    time.sleep(0.1)
                assert marker.exists(), 'worker没有进入已持有租约的计算阶段'
                assert json.loads(marker.read_text(encoding='utf-8'))['run_id'] == first
                with connect_as() as connection:
                    state = connection.execute('SELECT status,worker_token IS NOT NULL FROM risk_run WHERE run_id=%s', (first,)).fetchone()
                    assert state == ('RUNNING', True)
                process.terminate()
                process.wait(timeout=10)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=10)
        # 缩短本隔离夹具的租约等待；生产120秒租约逻辑及新进程入口不变。
        with connect_as() as connection:
            connection.execute("UPDATE risk_run SET lease_expires_at=clock_timestamp()-interval '1 second' WHERE run_id=%s", (first,))
        restarted = subprocess.run([sys.executable, '-X', 'utf8', '-m', 'app.worker', '--once', '--kind', 'risks'],
            cwd=BACKEND_ROOT, env=environment, capture_output=True, text=True, encoding='utf-8', timeout=60)
        assert restarted.returncode == 0, restarted.stdout
        with connect_as() as connection:
            state = connection.execute('SELECT status,worker_token,lease_expires_at FROM risk_run WHERE run_id=%s', (first,)).fetchone()
            assert state == ('FAILED', None, None)
            assert connection.execute('SELECT count(*) FROM risk_profile WHERE run_id=%s', (first,)).fetchone()[0] == 0
        second = request_run()
        assert second != first
        retried = subprocess.run([sys.executable, '-X', 'utf8', '-m', 'app.worker', '--once', '--kind', 'risks'],
            cwd=BACKEND_ROOT, env=environment, capture_output=True, text=True, encoding='utf-8', timeout=60)
        assert retried.returncode == 0, retried.stdout
        with connect_as() as connection:
            assert connection.execute('SELECT status FROM risk_run WHERE run_id=%s', (second,)).fetchone()[0] == 'SUCCEEDED'
            assert connection.execute('SELECT status FROM risk_run WHERE run_id=%s', (first,)).fetchone()[0] == 'FAILED'
