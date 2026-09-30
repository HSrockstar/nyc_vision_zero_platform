"""M4真实PG验收；全部输入为合成，使用独立随机库。"""

import csv
import io
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient
import psycopg
import pytest
from sqlalchemy import event

from app import risks
from app.config import Settings
from app.db.connection import database_engine
from app.main import app
from conftest import connect_as, seed_user
from test_m1_auth import login
from test_m2_imports import csv_bytes, execute_job, inputs, upload

FIELDS = ('number_of_persons_injured', 'number_of_persons_killed', 'number_of_pedestrians_injured',
          'number_of_pedestrians_killed', 'number_of_cyclist_injured', 'number_of_cyclist_killed')


@pytest.fixture
def risk_client(isolated_db):
    with connect_as() as connection:
        users = [seed_user(connection, role=role) for role in (1, 2, 3)]
    with TestClient(app) as client:
        auth = [login(client, name) for _, name in users]
        files = inputs()
        base = next(csv.DictReader(io.StringIO(files['crashes'].decode('utf-8-sig'))))
        rows = []
        for index in range(8):
            group = 'A' if index < 2 else 'B' if index < 6 else 'U' if index == 6 else 'X'
            row = {**base, **{field: '0' for field in FIELDS}, 'collision_id': str(91000 + index),
                   'on_street_name': 'SYNTHETIC ' + group, 'off_street_name': 'SYNTHETIC CROSS ' + group,
                   'longitude': str(-74 + index * .001), 'crash_date': '2025-01-01'}
            # 同一组使用同一观察地点。
            row['longitude'] = {'A': '-74', 'B': '-73.99', 'U': '-73.98', 'X': ''}[group]
            if index in (0, 2):
                row[FIELDS[0]] = '1'; row[FIELDS[2]] = '1'
            if index == 3:
                row[FIELDS[0]] = '1'; row[FIELDS[1]] = '1'; row[FIELDS[4]] = '1'
            if group == 'U': row[FIELDS[4]] = ''
            if group == 'X': row['latitude'] = ''
            rows.append(row)
        files['crashes'] = csv_bytes('CRASHES', rows)
        files['persons'] = csv_bytes('PERSON', [])
        files['vehicles'] = csv_bytes('VEHICLES', [
            {'unique_id': str(92000 + i), 'collision_id': '91000', 'crash_date': '2025-01-01',
             'vehicle_type': 'SYNTHETIC CAR'} for i in range(2)])
        batch = upload(client, auth[0], files)
        assert batch.status_code == 202, batch.text
        execute_job()
        assert client.post('/api/v1/imports/' + batch.json()['data']['batch_id'] + '/publish', headers=auth[0],
                           json={'request_id': str(uuid4())}).status_code == 202
        execute_job()
        generated = client.post('/api/v1/intersection-candidates/generate', headers=auth[1],
                                json={'borough_id': 3, 'max_locations': 100, 'radius_m': 50})
        assert generated.status_code == 200, generated.text
        candidates = client.get('/api/v1/intersections', headers=auth[0]).json()['data']['items']
        for item in candidates:
            result = client.post('/api/v1/intersections/' + item['intersection_id'] + '/confirm',
                headers=auth[1], json={'version': item['version'], 'note': '明确标记的M4合成道路确认'})
            assert result.status_code == 200, result.text
        yield client, auth, users


def request_run(client, headers, **changes):
    return client.post('/api/v1/risk-runs', headers=headers, json={
        'request_id': str(uuid4()), 'rule_id': '1', 'period_start': '2025-01-01', 'period_end': '2026-01-01', **changes})


def test_pipeline_hand_values_unknown_coverage_roles_and_history(risk_client):
    client, (admin, manager, viewer), _ = risk_client
    assert client.get('/api/v1/risk-rules').status_code == 401
    assert request_run(client, viewer).status_code == 403
    assert request_run(client, manager, period_end='2025-01-01').status_code == 422
    assert request_run(client, manager, rule_id='999').status_code == 422
    response = request_run(client, manager)
    assert response.status_code == 202, response.text
    run_id = response.json()['data']['run_id']
    assert client.get('/api/v1/risk-profiles', headers=viewer).status_code == 422
    assert client.get('/api/v1/risk-profiles', headers=viewer, params={'run_id': run_id}).json()['data']['items'] == []
    assert risks.run_once()['status'] == 'processed'
    run = client.get('/api/v1/risk-runs/' + run_id, headers=viewer).json()['data']
    assert run['status'] == 'SUCCEEDED' and not run['is_stale']
    assert run['coverage_summary']['total'] == 8 and run['coverage_summary']['included'] == 7
    assert run['coverage_summary']['missing_coordinates'] == 1 and run['coverage_summary']['unmatched'] == 1
    assert run['coverage_summary']['profiled_intersections'] == 3
    assert run['coverage_summary']['incomplete_included'] == 1
    items = client.get('/api/v1/risk-profiles', headers=viewer, params={'run_id': run_id}).json()['data']['items']
    assert [(row['score'], row['risk_level'], row['collision_count']) for row in items] == [
        ('30.00', 'HIGH', 4), ('10.00', 'MEDIUM', 2), (None, 'UNKNOWN', 1)]
    details = client.get('/api/v1/risk-profiles/' + items[0]['profile_id'], headers=viewer).json()['data']
    assert details['contributions'] == {'collision': '4.00', 'injured': '6.00', 'killed': '10.00', 'vru': '10.00'}
    assert client.get('/api/v1/risk-profiles', headers=viewer,
                      params={'run_id': run_id, 'risk_level': 'UNKNOWN'}).json()['data']['total'] == 1
    snapshot = risks.read_snapshot(run['input_manifest']['snapshot'])
    assert len(snapshot['included_inputs']) == 7 and len(snapshot['mapping']) == 3
    assert risks.run_once()['status'] == 'idle'
    with connect_as() as connection:
        connection.execute('UPDATE dataset_state SET revision=revision+1 WHERE state_id=1')
    assert client.get('/api/v1/risk-runs/' + run_id, headers=viewer).json()['data']['is_stale']
    assert client.get('/api/v1/risk-profiles', headers=viewer, params={'run_id': run_id}).json()['data']['items'][0]['score'] == '30.00'
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with connect_as('app') as connection:
            connection.execute('UPDATE risk_run SET status=\'FAILED\' WHERE run_id=%s', (run_id,))
    with pytest.raises(psycopg.errors.CheckViolation):
        with connect_as() as connection:
            connection.execute('UPDATE risk_profile SET collision_count=999 WHERE run_id=%s', (run_id,))
    empty = request_run(client, admin, period_start='2026-01-01', period_end='2026-02-01').json()['data']['run_id']
    assert risks.run_once()['status'] == 'processed'
    assert client.get('/api/v1/risk-profiles', headers=viewer, params={'run_id': empty}).json()['data']['total'] == 0
    assert client.get('/api/v1/risk-runs/' + empty, headers=viewer).json()['data']['coverage_summary']['coverage_ratio'] is None


def test_request_deduplication_and_content_conflict(risk_client):
    client, (_, manager, _), _ = risk_client
    key = str(uuid4())
    first = request_run(client, manager, request_id=key)
    repeat = request_run(client, manager, request_id=key)
    assert first.json()['data']['run_id'] == repeat.json()['data']['run_id']
    assert request_run(client, manager, request_id=key, period_end='2025-06-01').status_code == 409
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with connect_as('worker') as connection:
            connection.execute("UPDATE risk_run SET period_end='2025-06-01' WHERE run_id=%s", (first.json()['data']['run_id'],))


@pytest.mark.parametrize('failure', ['file', 'hash', 'publication', 'authority', 'role'])
def test_failed_calculation_exposes_no_partial_results(risk_client, failure):
    client, (_, manager, viewer), users = risk_client
    run_id = request_run(client, manager).json()['data']['run_id']
    if failure == 'publication':
        with connect_as() as connection:
            connection.execute("""CREATE FUNCTION public.synthetic_failure() RETURNS trigger LANGUAGE plpgsql AS $$
                BEGIN IF NEW.status='SUCCEEDED' THEN RAISE EXCEPTION 'synthetic rollback'; END IF; RETURN NEW; END $$;
                CREATE TRIGGER synthetic_failure BEFORE UPDATE ON risk_run FOR EACH ROW EXECUTE FUNCTION public.synthetic_failure()""")
    if failure == 'authority':
        with connect_as() as connection:
            connection.execute('UPDATE app_user SET is_active=false,version=version+1,auth_version=auth_version+1 WHERE user_id=%s', (users[1][0],))
    if failure == 'role':
        with connect_as() as connection:
            connection.execute('UPDATE app_user SET role_id=3,version=version+1,auth_version=auth_version+1 WHERE user_id=%s', (users[1][0],))
    original = risks.write_snapshot

    def broken_file(payload):
        if failure == 'file': raise OSError('synthetic disk failure')
        reference = original(payload)
        if failure == 'hash': risks.snapshot_path(reference['storage_key']).write_bytes(b'corrupted')
        return reference

    with patch.object(risks, 'write_snapshot', broken_file):
        result = risks.run_once()
    assert result['status'] == 'failed', result
    assert client.get('/api/v1/risk-runs/' + run_id, headers=viewer).json()['data']['status'] == 'FAILED'
    assert client.get('/api/v1/risk-profiles', headers=viewer, params={'run_id': run_id}).json()['data']['items'] == []
    with connect_as() as connection:
        assert connection.execute('SELECT count(*) FROM risk_profile WHERE run_id=%s', (run_id,)).fetchone()[0] == 0


def test_snapshot_is_consistent_when_data_changes_before_publication(risk_client):
    client, (_, manager, viewer), _ = risk_client
    run_id = request_run(client, manager).json()['data']['run_id']
    original = risks.calculate

    def concurrent_calculate(engine, run_id, token):
        changed = False

        def change_after_aggregate(_conn, _cursor, statement, _params, _context, _many):
            nonlocal changed
            if 'GROUP BY intersection_id ORDER BY intersection_id' not in statement or changed:
                return
            changed = True
            with connect_as() as connection:
                connection.execute('UPDATE casualty_stat SET persons_injured=100 WHERE collision_id=91000')
                connection.execute("""UPDATE location_assignment SET intersection_id=NULL,match_status='REJECTED',
                    match_method='MANUAL',version=version+1,reviewed_at=now()
                    WHERE location_id=(SELECT location_id FROM collision WHERE collision_id=91000)""")
                connection.execute('UPDATE dataset_state SET revision=revision+1 WHERE state_id=1')

        event.listen(engine, 'after_cursor_execute', change_after_aggregate)
        try:
            reference = original(engine, run_id, token)
            assert changed
            return reference
        finally:
            event.remove(engine, 'after_cursor_execute', change_after_aggregate)

    with patch.object(risks, 'calculate', concurrent_calculate):
        result = risks.run_once()
        assert result['status'] == 'processed', result
    run = client.get('/api/v1/risk-runs/' + run_id, headers=viewer).json()['data']
    assert run['is_stale']
    snapshot = risks.read_snapshot(run['input_manifest']['snapshot'])
    assert snapshot['included_inputs'][0]['persons_injured'] == 1
    assert snapshot['profiles'][0]['injured_count'] == 1
    assert snapshot['coverage']['included'] == 7 and len(snapshot['mapping']) == 3
    assert next(item for item in snapshot['mapping'] if item['street_a'] == 'SYNTHETIC A')['match_status'] == 'AUTO_MATCHED'


def test_expired_lease_and_token_prevent_late_publication(risk_client):
    client, (_, manager, viewer), _ = risk_client
    run_id = request_run(client, manager).json()['data']['run_id']
    engine = database_engine(Settings(), worker=True)
    try:
        job = risks.claim(engine)
        assert job is not None
        reference = risks.calculate(engine, *job)
        with connect_as() as connection:
            connection.execute("UPDATE risk_run SET lease_expires_at=now()-interval '1 second' WHERE run_id=%s", (run_id,))
        assert risks.claim(engine) is None
        with pytest.raises(risks.RiskProblem, match='RISK_LEASE_LOST'):
            risks.publish(engine, *job, reference)
        assert client.get('/api/v1/risk-runs/' + run_id, headers=viewer).json()['data']['status'] == 'FAILED'
    finally:
        engine.dispose()


def test_each_required_casualty_field_produces_unknown(risk_client):
    client, (_, manager, viewer), _ = risk_client
    for field in ('persons_injured','persons_killed','pedestrians_injured','pedestrians_killed','cyclists_injured','cyclists_killed'):
        with connect_as() as connection:
            original = connection.execute('SELECT ' + field + ' FROM casualty_stat WHERE collision_id=91000').fetchone()[0]
            connection.execute('UPDATE casualty_stat SET ' + field + '=NULL WHERE collision_id=91000')
        run_id = request_run(client, manager).json()['data']['run_id']
        result = risks.run_once()
        assert result['status'] == 'processed', result
        rows = client.get('/api/v1/risk-profiles', headers=viewer, params={'run_id': run_id}).json()['data']['items']
        a = next(row for row in rows if row['street_a'] == 'SYNTHETIC A')
        assert a['score'] is None and a['risk_level'] == 'UNKNOWN' and a['incomplete_casualty_collision_count'] == 1
        with connect_as() as connection:
            connection.execute('UPDATE casualty_stat SET ' + field + '=%s WHERE collision_id=91000', (original,))


def test_rule_retirement_preserves_history_and_allows_failure_recording(risk_client):
    client, (_, manager, viewer), _ = risk_client
    successful = request_run(client, manager).json()['data']['run_id']
    result = risks.run_once()
    assert result['status'] == 'processed', result
    queued = request_run(client, manager).json()['data']['run_id']
    with connect_as() as connection:
        connection.execute("UPDATE risk_rule SET status='RETIRED' WHERE rule_id=1")
    result = risks.run_once()
    assert result['status'] == 'failed' and result['error_code'] == 'RISK_RULE_NO_LONGER_PUBLISHED'
    assert client.get('/api/v1/risk-runs/' + queued, headers=viewer).json()['data']['status'] == 'FAILED'
    assert request_run(client, manager).status_code == 422
    assert client.get('/api/v1/risk-rules', headers=viewer).json()['data']['items'][0]['status'] == 'RETIRED'
    assert client.get('/api/v1/risk-profiles', headers=viewer, params={'run_id': successful}).json()['data']['total'] == 3
