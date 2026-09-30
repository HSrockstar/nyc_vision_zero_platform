"""M3合成观察点、正式事故和权限边界；数据库用例只用随机验证库。"""

import csv
import io
import json
import subprocess
import sys
from uuid import uuid4

from fastapi.testclient import TestClient
import psycopg
import pytest

from app.main import app
from app.config import BACKEND_ROOT
from app.spatial import pair
from conftest import connect_as, seed_user
from test_m1_auth import login
from test_m2_imports import csv_bytes, execute_job, inputs, upload


def test_street_pair_is_ordered_without_fuzzy_aliases():
    assert pair("  Main  Street ", "８ AVE") == pair("8 ave", "MAIN STREET")
    assert pair("BROADWAY", " Broadway ") is None
    assert pair("MAIN ST", "8 AVE") != pair("MAIN STREET", "8 AVE")


@pytest.fixture
def spatial_client(isolated_db):
    with connect_as() as connection:
        accounts = [seed_user(connection, role=role)[1] for role in (1, 2, 3)]
        for location_id, borough, on_street, cross_street, longitude, latitude in (
            (9001, 3, 'SYNTHETIC MAIN', 'SYNTHETIC CROSS', -74.00000, 40.70000),
            (9002, 3, 'SYNTHETIC CROSS', 'SYNTHETIC MAIN', -73.99965, 40.70000),
            (9003, 3, 'SYNTHETIC MAIN', 'SYNTHETIC CROSS', -73.99930, 40.70000),
            (9004, 3, 'SYNTHETIC X', 'SYNTHETIC Y', -74.00500, 40.70000),
            (9005, 3, 'SYNTHETIC MAIN', 'SYNTHETIC CROSS', None, None),
            (9006, None, 'SYNTHETIC MAIN', 'SYNTHETIC CROSS', -74.00000, 40.70000),
        ):
            connection.execute("""INSERT INTO location(location_id,location_key,key_input,borough_id,
                on_street_name,cross_street_name,geom) VALUES (%s,%s,'{}'::jsonb,%s,%s,%s,
                CASE WHEN %s::float IS NULL THEN NULL ELSE ST_SetSRID(ST_MakePoint(%s,%s),4326) END)""",
                (location_id, uuid4().hex, borough, on_street, cross_street,
                 longitude, longitude, latitude))
    with TestClient(app) as client:
        yield client, [login(client, name) for name in accounts]


def call_generate(client, auth, *, after=0, max_locations=3):
    return client.post('/api/v1/intersection-candidates/generate', headers=auth,
                       json={'borough_id': 3, 'after_location_id': after, 'max_locations': max_locations,
                             'radius_m': 50})


def test_candidate_anchor_confirmation_ambiguity_manual_override_and_permissions(spatial_client):
    client, (admin, manager, viewer) = spatial_client
    assert call_generate(client, viewer).status_code == 403
    first = call_generate(client, manager)
    assert first.status_code == 200, first.text
    assert first.json()['data']['processed'] == 3
    assert first.json()['data']['created_candidates'] == 2  # 60米首尾不能借中点串联
    assert first.json()['meta']['request_id']
    candidates = client.get('/api/v1/intersections', headers=viewer,
                            params={'status': 'CANDIDATE'}).json()['data']
    assert candidates['total'] == 2
    by_code = {item['intersection_code']: item for item in candidates['items']}
    first_id = by_code['NYC-M3-9001']['intersection_id']
    third_id = by_code['NYC-M3-9003']['intersection_id']
    assert client.get('/api/v1/location-assignments/9002', headers=manager).json()['data']['intersection_id'] == first_id
    with connect_as() as connection:
        assert connection.execute('SELECT revision FROM dataset_state').fetchone()[0] == 0
    repeated = call_generate(client, manager)
    assert repeated.status_code == 200
    assert repeated.json()['data']['created_candidates'] == 0
    assert repeated.json()['data']['auto_matched'] == 0
    assert client.post(f'/api/v1/intersections/{first_id}/confirm', headers=viewer,
                       json={'version': 1, 'note': '合成证据'}).status_code == 403
    confirmed = client.post(f'/api/v1/intersections/{first_id}/confirm', headers=manager,
                            json={'version': 1, 'note': '合成观察点与街道配对已复核'})
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()['data']['assignments_changed'] == 2
    assert client.post(f'/api/v1/intersections/{first_id}/confirm', headers=manager,
                       json={'version': 1, 'note': '旧版本'}).status_code == 409
    assignment = client.get('/api/v1/location-assignments/9002', headers=manager).json()['data']
    assert assignment['match_status'] == 'AUTO_MATCHED'
    assert call_generate(client, manager).json()['data']['auto_matched'] == 0
    third = client.post(f'/api/v1/intersections/{third_id}/confirm', headers=admin,
                        json={'version': 1, 'note': '第二个锚点单独复核'})
    assert third.status_code == 200, third.text
    downgraded = client.get('/api/v1/location-assignments/9002', headers=manager).json()['data']
    assert downgraded['match_status'] == 'CANDIDATE' and downgraded['intersection_id'] is None
    with connect_as() as connection:
        connection.execute("""INSERT INTO location(location_id,location_key,key_input,borough_id,on_street_name,
            cross_street_name,geom) VALUES (9007,%s,'{}'::jsonb,3,'SYNTHETIC MAIN','SYNTHETIC CROSS',
            ST_SetSRID(ST_MakePoint(-73.99948,40.7),4326))""", (uuid4().hex,))
    overlap = call_generate(client, manager, after=9006)
    assert overlap.status_code == 200, overlap.text
    ambiguous = client.get('/api/v1/location-assignments/9007', headers=manager).json()['data']
    assert ambiguous['match_status'] == 'CANDIDATE' and ambiguous['intersection_id'] is None
    assert len(ambiguous['evidence']['confirmed_ids']) == 2
    assert client.patch('/api/v1/location-assignments/9002', headers=viewer,
                        json={'version': downgraded['version'], 'status': 'REJECTED', 'reason': '无权限'}).status_code == 403
    changed = client.patch('/api/v1/location-assignments/9002', headers=manager,
                           json={'version': downgraded['version'], 'status': 'MANUAL_CONFIRMED',
                                 'intersection_id': third_id, 'reason': '现场复核后改派，合成数据'})
    assert changed.status_code == 200, changed.text
    assert client.patch('/api/v1/location-assignments/9002', headers=manager,
                        json={'version': assignment['version'], 'status': 'REJECTED',
                              'reason': '旧版本'}).status_code == 409
    assert call_generate(client, manager).json()['data']['auto_matched'] == 0
    revised = client.get('/api/v1/location-assignments/9002', headers=manager).json()['data']
    assert revised['match_status'] == 'MANUAL_CONFIRMED' and revised['intersection_id'] == third_id
    with connect_as() as connection:
        assert connection.execute('SELECT revision FROM dataset_state').fetchone()[0] >= 3
        actions = [r[0] for r in connection.execute("SELECT action FROM audit_log WHERE action LIKE 'INTERSECTION_%' OR action='LOCATION_ASSIGNMENT_REVIEWED'")]
        assert 'INTERSECTION_CANDIDATES_GENERATED' in actions
        assert 'INTERSECTION_CONFIRMED' in actions
        assert 'LOCATION_ASSIGNMENT_REVIEWED' in actions
        assert connection.execute('SELECT count(*) FROM location WHERE geom IS NULL').fetchone()[0] == 1
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with connect_as('worker') as connection:
            connection.execute("INSERT INTO intersection(intersection_code,street_a,street_b,center_geom,status,source_method) VALUES('FORBIDDEN','A','B',ST_SetSRID(ST_MakePoint(-74,40.7),4326),'CANDIDATE','DERIVED')")


def test_map_bbox_nearby_and_missing_coordinate_coverage(spatial_client):
    client, (admin, _manager, viewer) = spatial_client
    files = inputs()
    reader = csv.DictReader(io.StringIO(files['crashes'].decode('utf-8-sig')))
    rows = list(reader)
    rows[1]['collision_id'] = '9007199254740994'
    rows.append({**rows[0], 'collision_id': '9007199254740995', 'crash_date': '2025-01-03',
                 'latitude': '', 'longitude': ''})
    files['crashes'] = csv_bytes('CRASHES', rows)
    batch = upload(client, admin, files)
    assert batch.status_code == 202, batch.text
    execute_job()
    number = batch.json()['data']['batch_id']
    authorized = client.post(f'/api/v1/imports/{number}/publish', headers=admin,
                             json={'request_id': str(uuid4())})
    assert authorized.status_code == 202, authorized.text
    execute_job()
    args = {'start': '2025-01-01', 'end': '2025-01-04', 'west': -74.01, 'south': 40.69,
            'east': -73.99, 'north': 40.71, 'limit': 1}
    visible = client.get('/api/v1/map/collisions', headers=viewer, params=args)
    assert visible.status_code == 200, visible.text
    data = visible.json()['data']
    assert data['returned'] == 1 and data['truncated'] is True
    assert data['coverage']['total'] == 3 and data['coverage']['geocoded'] == 2
    assert data['coverage']['missing_coordinates'] == 1
    assert data['coverage']['unmatched'] == 3
    assert client.get('/api/v1/collisions', headers=viewer,
                      params={'start': '2025-01-01', 'end': '2025-01-04', 'include_total': True}).json()['data']['total'] == 3
    assert client.get('/api/v1/map/collisions', headers=viewer,
                      params={**args, 'west': -73.8, 'east': -74.0}).status_code == 422
    close = client.get('/api/v1/map/nearby', headers=viewer,
                       params={'longitude': -74.0, 'latitude': 40.7, 'radius_m': 100, 'limit': 1})
    assert close.status_code == 200 and close.json()['data']['truncated'] is True
    far = client.get('/api/v1/map/nearby', headers=viewer,
                     params={'longitude': -73.0, 'latitude': 40.7, 'radius_m': 50})
    assert far.status_code == 200 and far.json()['data']['items'] == []


def test_rejected_candidate_stays_rejected_and_local_cli_is_bounded(spatial_client):
    client, (_admin, manager, _viewer) = spatial_client
    with connect_as() as connection:
        username = connection.execute("SELECT username FROM app_user WHERE role_id = 1").fetchone()[0]
    command = [sys.executable, '-X', 'utf8', '-m', 'app.cli',
               'generate-intersection-candidates', '--borough-id', '3',
               '--username', username, '--max-batches', '1']
    first = subprocess.run(command, cwd=BACKEND_ROOT, capture_output=True, text=True, timeout=60)
    assert first.returncode == 0, first.stderr
    report = json.loads(first.stdout)
    assert report['processed'] <= 100
    candidates = client.get('/api/v1/intersections', headers=manager,
                            params={'status': 'CANDIDATE', 'limit': 100}).json()['data']['items']
    target = next(item for item in candidates if item['intersection_code'] == 'NYC-M3-9004')
    rejected = client.post(f"/api/v1/intersections/{target['intersection_id']}/reject",
                           headers=manager, json={'version': target['version'],
                                                  'note': 'Synthetic observation was manually rejected'})
    assert rejected.status_code == 200, rejected.text
    assignment = client.get('/api/v1/location-assignments/9004', headers=manager).json()['data']
    assert assignment['match_status'] == 'REJECTED' and assignment['intersection_id'] is None
    rerun = client.post('/api/v1/intersection-candidates/generate', headers=manager,
                        json={'borough_id': 3, 'after_location_id': 9003, 'max_locations': 100, 'radius_m': 50})
    assert rerun.status_code == 200, rerun.text
    with connect_as() as connection:
        assert connection.execute("SELECT count(*) FROM intersection WHERE intersection_code='NYC-M3-9004'").fetchone()[0] == 1
        assert connection.execute("SELECT count(*) FROM audit_log WHERE action='INTERSECTION_REJECTED'").fetchone()[0] == 1
