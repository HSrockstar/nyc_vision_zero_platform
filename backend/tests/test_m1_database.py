import os
from uuid import uuid4

import psycopg
import pytest

from app.config import Settings
from conftest import connect_as, seed_user

pytestmark = pytest.mark.skipif(os.getenv("VISION_ZERO_RUN_DB_TESTS") != "1", reason="需显式启用真实PG验证")


@pytest.fixture
def basis(db_env):
    with connect_as() as connection:
        user, _ = seed_user(connection)
        manager, _ = seed_user(connection, role=2)
        intersection = connection.execute("""INSERT INTO intersection
            (intersection_code, street_a, street_b, center_geom, status, source_method, confirmation_note, confirmed_by, confirmed_at)
            VALUES (%s, 'M1 TEST A', 'M1 TEST B', ST_SetSRID(ST_MakePoint(-73.9857,40.7484),4326),
                    'CONFIRMED', 'MANUAL', '明确标记的M1测试路口', %s, now()) RETURNING intersection_id""", ("TEST-" + uuid4().hex, user)).fetchone()[0]
        run = connection.execute("""INSERT INTO risk_run (request_id, request_hash, rule_id, period_start, period_end, status, requested_by)
            VALUES (%s, %s, 1, '2025-01-01', '2025-02-01', 'RUNNING', %s) RETURNING run_id""", (uuid4(), "a" * 64, user)).fetchone()[0]
        return {"user": user, "manager": manager, "intersection": intersection, "run": run}


def add_profile(connection, basis, *, n=1, injured=0, killed=0, vulnerable=0, missing=0):
    return connection.execute("""INSERT INTO risk_profile (run_id, intersection_id, collision_count, injured_count,
        killed_count, vulnerable_road_user_count, incomplete_casualty_collision_count)
        VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING profile_id""",
        (basis["run"], basis["intersection"], n, injured, killed, vulnerable, missing)).fetchone()[0]


def finish_run(connection, run):
    connection.execute("UPDATE risk_run SET status='SUCCEEDED', input_revision=0, finished_at=now() WHERE run_id=%s", (run,))


def add_task(connection, basis, profile, *, status="DRAFT", measure="FIELD_SURVEY"):
    return connection.execute("""INSERT INTO governance_task
        (task_code, request_id, request_hash, profile_id, title, description, measure_type, priority, status,
         created_by, assignee_id, assessment_scope)
        VALUES (%s,%s,%s,%s,'M1 TEST','明确标记的数据库约束测试',%s,'LOW',%s,%s,%s,'{}') RETURNING task_id""",
        ("TEST-" + uuid4().hex, uuid4(), "a" * 64, profile, measure, status, basis["user"], basis["manager"])).fetchone()[0]


@pytest.mark.parametrize("score,level", [(9,"LOW"),(10,"MEDIUM"),(29,"MEDIUM"),(30,"HIGH"),(None,"UNKNOWN")])
def test_risk_view_thresholds_and_missing(basis, score, level):
    with connect_as() as connection:
        profile = add_profile(connection, basis, n=score or 1, missing=1 if score is None else 0)
        assert connection.execute("SELECT count(*) FROM v_risk_profile WHERE profile_id=%s", (profile,)).fetchone()[0] == 0
        finish_run(connection, basis["run"])
        actual = connection.execute("SELECT score, risk_level, is_stale FROM v_risk_profile WHERE profile_id=%s", (profile,)).fetchone()
        assert actual == (score, level, False)
        connection.execute("UPDATE dataset_state SET revision=revision+1 WHERE state_id=1")
        assert connection.execute("SELECT is_stale FROM v_risk_profile WHERE profile_id=%s", (profile,)).fetchone()[0]
        connection.rollback()


@pytest.mark.parametrize("n,i,k,v,expected", [(2,1,0,1,10),(4,2,1,2,30)])
def test_risk_view_hand_calculation(basis,n,i,k,v,expected):
    with connect_as() as connection:
        profile = add_profile(connection, basis, n=n, injured=i, killed=k, vulnerable=v)
        finish_run(connection, basis["run"])
        assert connection.execute("SELECT score FROM v_risk_profile WHERE profile_id=%s", (profile,)).fetchone()[0] == expected


@pytest.mark.parametrize("mutation", ["negative", "duplicate", "period", "srid", "published_rule"])
def test_database_rejects_invalid_input(basis, mutation):
    with pytest.raises(psycopg.Error):
        with connect_as() as connection:
            if mutation == "negative": add_profile(connection, basis, injured=-1)
            elif mutation == "duplicate":
                add_profile(connection, basis)
                add_profile(connection, basis)
            elif mutation == "period":
                connection.execute("UPDATE risk_run SET period_end=period_start WHERE run_id=%s", (basis["run"],))
            elif mutation == "srid":
                connection.execute("UPDATE intersection SET center_geom=ST_SetSRID(ST_MakePoint(-73,40),3857) WHERE intersection_id=%s", (basis["intersection"],))
            else: connection.execute("UPDATE risk_rule SET weight_collision=2 WHERE rule_id=1")


@pytest.mark.parametrize("mutation", ["profile", "run", "intersection", "history", "audit"])
def test_snapshot_and_history_immutable(basis, mutation):
    with connect_as() as connection:
        profile = add_profile(connection, basis)
        finish_run(connection, basis["run"])
        task = add_task(connection, basis, profile)
        history = connection.execute("""INSERT INTO task_history (task_id,sequence_no,request_id,request_hash,event_type,to_status,actor_id,note)
            VALUES (%s,1,%s,%s,'CREATE','DRAFT',%s,'M1 TEST') RETURNING history_id""", (task,uuid4(),"a"*64,basis["user"])).fetchone()[0]
        audit_id = connection.execute("INSERT INTO audit_log (actor_id,action,entity_type) VALUES (%s,'TEST','test') RETURNING audit_id", (basis["user"],)).fetchone()[0]
    with pytest.raises(psycopg.errors.CheckViolation):
        with connect_as() as connection:
            if mutation == "profile": connection.execute("UPDATE risk_profile SET injured_count=1 WHERE profile_id=%s", (profile,))
            elif mutation == "run": connection.execute("UPDATE risk_run SET input_revision=1 WHERE run_id=%s", (basis["run"],))
            elif mutation == "intersection": connection.execute("UPDATE intersection SET street_a='OTHER' WHERE intersection_id=%s", (basis["intersection"],))
            elif mutation == "history": connection.execute("DELETE FROM task_history WHERE history_id=%s", (history,))
            else: connection.execute("UPDATE audit_log SET action='OTHER' WHERE audit_id=%s", (audit_id,))


def test_unknown_only_investigation_draft(basis):
    with connect_as() as connection:
        profile = add_profile(connection, basis, missing=1)
        finish_run(connection, basis["run"])
        task = add_task(connection, basis, profile)
    with pytest.raises(psycopg.errors.CheckViolation):
        with connect_as() as connection:
            connection.execute("UPDATE governance_task SET status='OPEN' WHERE task_id=%s", (task,))


def test_collision_requires_casualty_and_preserves_null(basis):
    with connect_as() as connection:
        batch = connection.execute("""INSERT INTO import_batch (request_id,request_hash,manifest_hash,cleaning_version,status,created_by)
            VALUES (%s,%s,%s,'M1 TEST','UPLOADED',%s) RETURNING batch_id""", (uuid4(),"a"*64,"b"*64,basis["user"])).fetchone()[0]
        raw = connection.execute("""INSERT INTO raw_record (batch_id,source_kind,row_no,row_hash,validation_status)
            VALUES (%s,'CRASHES',1,%s,'ACCEPTED') RETURNING raw_record_id""", (batch,"c"*64)).fetchone()[0]
        location = connection.execute("INSERT INTO location (location_key) VALUES (%s) RETURNING location_id", ("M1-"+uuid4().hex,)).fetchone()[0]
    collision = secrets_collision_id()
    with pytest.raises(psycopg.errors.CheckViolation):
        with connect_as() as connection:
            connection.execute("INSERT INTO collision (collision_id,location_id,crash_date,source_record_id) VALUES (%s,%s,'2025-01-01',%s)", (collision,location,raw))
    with connect_as() as connection:
        connection.execute("INSERT INTO collision (collision_id,location_id,crash_date,source_record_id) VALUES (%s,%s,'2025-01-01',%s)", (collision,location,raw))
        connection.execute("INSERT INTO casualty_stat (collision_id) VALUES (%s)", (collision,))
    with connect_as() as connection:
        assert connection.execute("SELECT persons_injured FROM casualty_stat WHERE collision_id=%s", (collision,)).fetchone() == (None,)
    with pytest.raises(psycopg.errors.CheckViolation):
        with connect_as() as connection:
            connection.execute("UPDATE raw_record SET payload='{\"changed\":true}' WHERE raw_record_id=%s", (raw,))
    with pytest.raises(psycopg.errors.CheckViolation):
        with connect_as() as connection:
            connection.execute("DELETE FROM casualty_stat WHERE collision_id=%s", (collision,))


def secrets_collision_id():
    return uuid4().int % 9000000000000000000 + 1


@pytest.mark.parametrize("kind", ["app", "worker"])
@pytest.mark.parametrize("statement", ["CREATE TABLE public.forbidden(id integer)", "CREATE EXTENSION hstore", "UPDATE risk_rule SET weight_collision=0", "DELETE FROM task_history", "UPDATE governance_task SET status='COMPLETED'", "SELECT public.vz_user_guard()"])
def test_runtime_roles_cannot_administer(db_env, kind, statement):
    with pytest.raises(psycopg.Error):
        with connect_as(kind) as connection:
            connection.execute(statement)


def test_worker_cannot_read_passwords_or_write_accounts(db_env):
    for statement in ("SELECT password_hash FROM app_user", "UPDATE app_user SET is_active=false", "SELECT payload FROM raw_record", "SELECT person_age FROM person"):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with connect_as("worker") as connection:
                connection.execute(statement)
    with connect_as("worker") as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "0002_business_model"
        assert not connection.execute("SELECT has_schema_privilege(current_user,'public','CREATE')").fetchone()[0]
        assert not connection.execute("SELECT has_database_privilege(current_user,current_database(),'CREATE')").fetchone()[0]


def test_custom_function_and_default_acl_not_public(db_env):
    with connect_as() as connection:
        public_exec = connection.execute("""SELECT p.proname FROM pg_proc p
            CROSS JOIN LATERAL aclexplode(COALESCE(p.proacl,acldefault('f',p.proowner))) acl
            WHERE p.pronamespace='public'::regnamespace AND p.proname LIKE 'vz_%'
              AND acl.grantee=0 AND acl.privilege_type='EXECUTE'""").fetchall()
        assert public_exec == []
        name = 'm1_acl_' + uuid4().hex
        connection.execute(f"CREATE FUNCTION public.{name}() RETURNS integer LANGUAGE sql AS 'SELECT 1'")
        for kind in ('app','worker'):
            role = Settings().database_name + '_' + kind
            assert not connection.execute("SELECT has_function_privilege(%s,%s,'EXECUTE')",(role,'public.'+name+'()')).fetchone()[0]
        connection.rollback()


@pytest.mark.parametrize('case', ['foreign_key','not_null','username_unique'])
def test_basic_relational_constraints(db_env,case):
    with connect_as() as connection:
        user,name=seed_user(connection)
    expected = {'foreign_key':psycopg.errors.ForeignKeyViolation,'not_null':psycopg.errors.NotNullViolation,'username_unique':psycopg.errors.UniqueViolation}[case]
    with pytest.raises(expected):
        with connect_as() as connection:
            if case=='foreign_key': connection.execute('INSERT INTO casualty_stat (collision_id) VALUES (%s)',(secrets_collision_id(),))
            elif case=='not_null': connection.execute("INSERT INTO app_user (username,display_name,role_id) VALUES (%s,'M1 TEST',1)",('test_'+uuid4().hex[:16],))
            else: connection.execute("INSERT INTO app_user (username,password_hash,display_name,role_id) SELECT upper(username),password_hash,display_name,role_id FROM app_user WHERE user_id=%s",(user,))


def test_geography_distance_is_metres(db_env):
    with connect_as('app') as connection:
        distance,near100,near50=connection.execute("""WITH points AS (
            SELECT ST_SetSRID(ST_MakePoint(-73.9857,40.7484),4326)::geography a,
                   ST_SetSRID(ST_MakePoint(-73.9847,40.7484),4326)::geography b)
            SELECT ST_Distance(a,b),ST_DWithin(a,b,100),ST_DWithin(a,b,50) FROM points""").fetchone()
        assert 80 < distance < 90 and near100 and not near50
