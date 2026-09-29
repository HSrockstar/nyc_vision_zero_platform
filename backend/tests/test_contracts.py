from datetime import datetime, timedelta, timezone
from uuid import uuid4

import jwt
import pytest
from fastapi import HTTPException

from app.auth import LoginLimiter, token_claims
from app.config import Settings
from app.contracts import request_digest
from app.db.base import Base
from app import models


def test_complete_model_and_source_keys():
    assert len(Base.metadata.tables) == 23
    for name in ("collision", "person", "vehicle"):
        assert next(iter(Base.metadata.tables[name].primary_key)).identity is None
    assert list(Base.metadata.tables["collision_factor"].primary_key.columns.keys()) == ["collision_id", "factor_order"]
    assert not Base.metadata.tables["person"].c.source_vehicle_id.foreign_keys


def test_request_digest_stable_and_scoped():
    def digest(**overrides):
        return request_digest(**dict({"actor_id": "1", "operation": "TASK_EDIT", "target_id": "2", "payload": {"note": "调查", "version": 1}}, **overrides))
    baseline = digest()
    assert baseline == digest(payload={"version": 1, "note": "调查"})
    for override in ({"actor_id": "3"}, {"operation": "TASK_CANCEL"}, {"target_id": "4"}, {"payload": {"note": "其他", "version": 1}}):
        assert digest(**override) != baseline
    with pytest.raises(ValueError):
        digest(payload={"score": float("nan")})


@pytest.mark.parametrize("change", ["expired", "algorithm", "missing", "issuer", "audience", "version"])
def test_reject_invalid_tokens(monkeypatch, change):
    key = "a" * 96
    monkeypatch.setattr(Settings, "signing_key", lambda self: key)
    now = datetime.now(timezone.utc)
    claims = {"sub": "1", "ver": 1, "iat": now, "nbf": now, "exp": now + timedelta(minutes=15),
              "jti": str(uuid4()), "iss": "vision-zero", "aud": "vision-zero-web"}
    algorithm = "HS256"
    if change == "expired":
        claims.update(iat=now - timedelta(minutes=20), nbf=now - timedelta(minutes=20), exp=now - timedelta(minutes=5))
    elif change == "algorithm": algorithm = "HS384"
    elif change == "missing": del claims["jti"]
    elif change == "issuer": claims["iss"] = "other"
    elif change == "audience": claims["aud"] = "other"
    else: claims["ver"] = True
    with pytest.raises(HTTPException) as rejected:
        token_claims(jwt.encode(claims, key, algorithm=algorithm))
    assert rejected.value.status_code == 401


def test_limiter_bounds_failures_and_resets():
    limiter = LoginLimiter()
    for _ in range(5):
        limiter.reserve("local")
        limiter.finish("local", False)
    with pytest.raises(HTTPException) as rejected:
        limiter.reserve("local")
    assert rejected.value.status_code == 429
    limiter.reserve("another")
    limiter.finish("another", True)
    assert limiter.entries["another"] == ([], 0)


@pytest.mark.parametrize("directory_link", [False, True])
def test_secret_writes_reject_links_without_touching_target(tmp_path, monkeypatch, directory_link):
    import os
    import subprocess
    from app.db import provision
    import app.config as config
    root = tmp_path / "workspace"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    original = outside / "valuable.txt"
    original.write_text("保持原内容", encoding="utf-8")
    monkeypatch.setattr(provision, "PROJECT_ROOT", root)
    monkeypatch.setattr(config, "PROJECT_ROOT", root)
    if directory_link:
        link = root / ".m1-work"
        if os.name == "nt":
            result = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(outside)], capture_output=True)
            assert result.returncode == 0
        else:
            link.symlink_to(outside, target_is_directory=True)
        target = link / "model" / "secret.env"
    else:
        target = root / ".env"
        link = root / ".env.pending"
        if os.name == "nt":
            result = subprocess.run(["cmd", "/c", "mklink", "/H", str(link), str(original)], capture_output=True)
            assert result.returncode == 0
        else:
            link.symlink_to(original)
    with pytest.raises((ValueError, FileExistsError)):
        provision.write_config(target, {"SECRET": "不能写出仓库"})
    assert original.read_text(encoding="utf-8") == "保持原内容"
    assert not (outside / "model" / "secret.env").exists()


@pytest.mark.parametrize("mismatch", [None, "scope", "workspace", "missing"])
def test_python_maintenance_checks_volume_owner(monkeypatch, mismatch):
    import json
    from types import SimpleNamespace
    from app.db.provision import assert_local_container
    import app.db.provision as module
    for key in ('DOCKER_HOST', 'DOCKER_CONTEXT', 'DOCKER_TLS_VERIFY', 'DOCKER_CERT_PATH'):
        monkeypatch.delenv(key, raising=False)
    values = {'VISION_ZERO_WORKSPACE_ID': 'test-workspace', 'VISION_ZERO_DB_IMAGE': 'test-image',
              'VISION_ZERO_DB_PORT': '55433', 'POSTGRES_PASSWORD': 'synthetic-maintenance-value'}
    labels = {'vision-zero.scope': 'development', 'vision-zero.workspace': 'test-workspace'}
    volume_labels = dict(labels)
    if mismatch == 'scope': volume_labels['vision-zero.scope'] = 'other'
    if mismatch == 'workspace': volume_labels['vision-zero.workspace'] = 'other'
    if mismatch == 'missing': volume_labels = None
    container = {'State': {'Running': True}, 'Image': 'test-image',
                 'Config': {'Labels': labels, 'Env': ['POSTGRES_USER=postgres', 'POSTGRES_DB=vision_zero_dev',
                            'POSTGRES_PASSWORD=synthetic-maintenance-value']},
                 'HostConfig': {'PortBindings': {'5432/tcp': [{'HostIp': '127.0.0.1', 'HostPort': '55433'}]}},
                 'Mounts': [{'Type': 'volume', 'Name': 'vision-zero-dev-postgis-data',
                             'Destination': '/var/lib/postgresql/data', 'RW': True}]}
    def run(arguments, **kwargs):
        if arguments[1:3] == ['context', 'show']: output = 'desktop-linux'
        elif arguments[1:3] == ['context', 'inspect']: output = 'npipe:////./pipe/dockerDesktopLinuxEngine'
        elif arguments[1] == 'inspect': output = json.dumps([container])
        elif arguments[1:3] == ['volume', 'inspect']:
            output = json.dumps([{'Name': 'vision-zero-dev-postgis-data', 'Labels': volume_labels}])
        else: raise AssertionError('非预期Docker命令')
        return SimpleNamespace(returncode=0, stdout=output)
    monkeypatch.setattr(module.subprocess, 'run', run)
    if mismatch:
        with pytest.raises(ValueError): assert_local_container(values)
    else:
        assert_local_container(values)


def test_settings_refuses_reparse_env_before_loading(monkeypatch, tmp_path):
    import stat
    from pathlib import Path
    from types import SimpleNamespace
    import app.config as config
    root = tmp_path / 'workspace'
    root.mkdir()
    env_file = root / '.env'
    env_file.write_text('不应被配置加载器读取', encoding='utf-8')
    original = Path.lstat
    def lstat(path, *args, **kwargs):
        if path == env_file:
            return SimpleNamespace(st_mode=stat.S_IFREG, st_file_attributes=stat.FILE_ATTRIBUTE_REPARSE_POINT)
        return original(path, *args, **kwargs)
    monkeypatch.setattr(config, 'PROJECT_ROOT', root)
    monkeypatch.setattr(Path, 'lstat', lstat)
    with pytest.raises(ValueError, match='重解析点'):
        Settings()
