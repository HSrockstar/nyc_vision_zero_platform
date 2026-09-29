from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

from fastapi.testclient import TestClient
import jwt
import psycopg
import pytest

from app.auth import password_hasher
from app.cli import init_admin
from app.config import Settings
from app.main import app
from conftest import TEST_PASSWORD, connect_as, seed_user
from test_m1_database import basis, add_profile, add_task, finish_run


def login(client, username, password=TEST_PASSWORD):
    result = client.post('/api/v1/auth/login', json={"username": username, "password": password})
    assert result.status_code == 200, result.text
    return {"Authorization": "Bearer " + result.json()["data"]["access_token"]}


def accounts():
    with connect_as() as connection:
        return [seed_user(connection, role=role) for role in (1, 2, 3)]


def test_unauthorized_and_viewer_manager_write_rejected(db_env):
    admin, manager, viewer = accounts()
    with TestClient(app) as client:
        assert client.get('/api/v1/users').status_code == 401
        for user in (manager, viewer):
            headers = login(client, user[1])
            assert client.get('/api/v1/users', headers=headers).status_code == 403
            assert client.post('/api/v1/users', headers=headers, json={
                "username": "forbidden_" + uuid4().hex[:12], "display_name": "测试",
                "role": "ADMIN", "password": TEST_PASSWORD}).status_code == 403
        headers = login(client, admin[1])
        assert client.get('/api/v1/users', headers=headers).status_code == 200


def test_account_creation_serialization_unique_and_validation(db_env):
    admin, _, _ = accounts()
    with TestClient(app) as client:
        headers = login(client, admin[1])
        body = {"username": "new_" + uuid4().hex[:12], "display_name": "新测试账户", "role": "VIEWER", "password": TEST_PASSWORD}
        created = client.post('/api/v1/users', headers=headers, json=body)
        assert created.status_code == 201
        data = created.json()['data']
        assert isinstance(data['user_id'], str)
        assert 'password' not in created.text and TEST_PASSWORD not in created.text
        body['username'] = body['username'].upper()
        assert client.post('/api/v1/users', headers=headers, json=body).status_code == 409
        body['password'] = 'bad-secret'
        invalid = client.post('/api/v1/users', headers=headers, json=body)
        assert invalid.status_code == 422 and 'bad-secret' not in invalid.text
    with connect_as() as connection:
        encoded = connection.execute("SELECT password_hash FROM app_user WHERE user_id=%s", (int(data['user_id']),)).fetchone()[0]
        assert encoded.startswith('$argon2id$') and password_hasher.verify(TEST_PASSWORD, encoded)


def test_logout_invalidates_all_sessions(db_env):
    user = accounts()[2]
    with TestClient(app) as client:
        first = login(client, user[1])
        second = login(client, user[1])
        assert client.post('/api/v1/auth/logout', headers=first).json()['data']['logged_out_all_sessions']
        for headers in (first, second):
            assert client.get('/api/v1/auth/me', headers=headers).status_code == 401


def test_password_change_and_audit_have_no_secrets(db_env):
    user = accounts()[2]
    new_password = 'M1-New-Synthetic-Password!'
    with TestClient(app) as client:
        headers = login(client, user[1])
        bad = client.post('/api/v1/auth/change-password', headers=headers, json={"old_password":"wrong", "new_password":new_password})
        assert bad.status_code == 400
        changed = client.post('/api/v1/auth/change-password', headers=headers, json={"old_password":TEST_PASSWORD,"new_password":new_password})
        assert changed.status_code == 200
        assert client.get('/api/v1/auth/me',headers=headers).status_code == 401
        assert client.post('/api/v1/auth/login',json={"username":user[1],"password":TEST_PASSWORD}).status_code == 401
        login(client,user[1],new_password)
    with connect_as() as connection:
        details = connection.execute("SELECT details::text FROM audit_log WHERE actor_id=%s", (user[0],)).fetchall()
        assert details and all(TEST_PASSWORD not in row[0] and new_password not in row[0] and '$argon2' not in row[0] for row in details)


@pytest.mark.parametrize("change", ["disable", "role"])
def test_changed_account_invalidates_existing_token(db_env, change):
    admin, manager, _ = accounts()
    with TestClient(app) as client:
        admin_headers = login(client,admin[1])
        manager_headers = login(client,manager[1])
        body = {"expected_version":1, **({"is_active":False} if change=='disable' else {"role":"VIEWER"})}
        changed = client.patch(f'/api/v1/users/{manager[0]}',headers=admin_headers,json=body)
        assert changed.status_code == 200
        assert client.get('/api/v1/auth/me',headers=manager_headers).status_code == 401
        if change == 'disable':
            assert client.post('/api/v1/auth/login',json={"username":manager[1],"password":TEST_PASSWORD}).status_code == 401
        else:
            assert client.get('/api/v1/users',headers=login(client,manager[1])).status_code == 403


def test_forged_role_claim_is_ignored(db_env):
    viewer = accounts()[2]
    with TestClient(app) as client:
        headers = login(client,viewer[1])
        token = headers['Authorization'].split()[1]
        claims = jwt.decode(token,Settings().signing_key(),algorithms=['HS256'],audience='vision-zero-web')
        claims['role'] = 'ADMIN'
        headers['Authorization'] = 'Bearer ' + jwt.encode(claims,Settings().signing_key(),algorithm='HS256')
        assert client.get('/api/v1/users',headers=headers).status_code == 403


def test_failed_login_rate_limit(db_env):
    with TestClient(app) as client:
        statuses = [client.post('/api/v1/auth/login',json={"username":"no_such_m1_user","password":"wrong"}).status_code for _ in range(6)]
        assert statuses == [401]*5 + [429]


def test_initial_admin_and_last_admin_guards(isolated_db, monkeypatch, capsys):
    monkeypatch.setenv('VISION_ZERO_INITIAL_ADMIN_PASSWORD',TEST_PASSWORD)
    init_admin('initial_test','测试初始化管理员')
    assert TEST_PASSWORD not in capsys.readouterr().out
    with pytest.raises(ValueError):
        init_admin('another_test','测试重复初始化')
    with connect_as() as connection:
        user = connection.execute("SELECT user_id,username FROM app_user WHERE role_id=1 AND is_active").fetchone()
    with TestClient(app) as client:
        headers = login(client,user[1])
        for body in ({"is_active":False},{"role":"VIEWER"}):
            result = client.patch(f'/api/v1/users/{user[0]}',headers=headers,json={"expected_version":1,**body})
            assert result.status_code == 409 and result.json()['error']['code']=='USER_LAST_ADMIN'
    with pytest.raises(psycopg.errors.CheckViolation):
        with connect_as() as connection:
            connection.execute('UPDATE app_user SET is_active=false WHERE user_id=%s',(user[0],))


@pytest.mark.parametrize("mode", ["api", "database"])
def test_two_admins_cannot_both_disable(isolated_db, mode):
    with connect_as() as connection:
        users=[seed_user(connection) for _ in range(2)]
    barrier=Barrier(2)
    if mode=='api':
        with TestClient(app) as client:
            headers=[login(client,user[1]) for user in users]
        def disable(index):
            barrier.wait(timeout=5)
            with TestClient(app) as client:
                return client.patch(f'/api/v1/users/{users[index][0]}',headers=headers[index],json={"expected_version":1,"is_active":False}).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(disable,range(2)))
        assert sorted(results)==[200,409]
    else:
        def disable(index):
            try:
                with connect_as() as connection:
                    connection.execute("SET LOCAL statement_timeout='8s'")
                    barrier.wait(timeout=5)
                    connection.execute('UPDATE app_user SET is_active=false WHERE user_id=%s',(users[index][0],))
                return 'success'
            except psycopg.errors.CheckViolation:
                return 'rejected'
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(disable,range(2)))
        assert sorted(results)==['rejected','success']
    with connect_as() as connection:
        assert connection.execute('SELECT count(*) FROM app_user WHERE role_id=1 AND is_active').fetchone()[0]==1


@pytest.mark.parametrize("status", ['OPEN','IN_PROGRESS','PENDING_REVIEW'])
@pytest.mark.parametrize("change", ["disable","role"])
def test_active_assignee_changes_rejected(basis,status,change):
    with connect_as() as connection:
        profile=add_profile(connection,basis)
        finish_run(connection,basis['run'])
        add_task(connection,basis,profile,status=status)
        username=connection.execute('SELECT username FROM app_user WHERE user_id=%s',(basis['user'],)).fetchone()[0]
    with TestClient(app) as client:
        body={"expected_version":1,**({"is_active":False} if change=='disable' else {"role":"VIEWER"})}
        result=client.patch(f"/api/v1/users/{basis['manager']}",headers=login(client,username),json=body)
        assert result.status_code==409 and result.json()['error']['code']=='USER_HAS_ACTIVE_TASKS'


def test_assignment_and_role_change_cannot_race(basis):
    with connect_as() as connection:
        profile=add_profile(connection,basis)
        finish_run(connection,basis['run'])
        task=add_task(connection,basis,profile)
    barrier=Barrier(2)
    def change(index):
        try:
            with connect_as() as connection:
                connection.execute("SET LOCAL statement_timeout='8s'")
                barrier.wait(timeout=5)
                if index==0: connection.execute('UPDATE app_user SET role_id=3 WHERE user_id=%s',(basis['manager'],))
                else: connection.execute("UPDATE governance_task SET status='OPEN' WHERE task_id=%s",(task,))
            return 'success'
        except psycopg.errors.CheckViolation:
            return 'rejected'
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(change,range(2)))
    assert sorted(results)==['rejected','success']


def test_account_version_conflict(db_env):
    admin,_,viewer=accounts()
    with TestClient(app) as client:
        headers=login(client,admin[1])
        path=f'/api/v1/users/{viewer[0]}'
        body={"expected_version":1,"display_name":"更新后测试名"}
        assert client.patch(path,headers=headers,json=body).status_code==200
        assert client.patch(path,headers=headers,json=body).status_code==409
