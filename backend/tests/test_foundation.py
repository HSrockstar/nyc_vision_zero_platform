import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.config import Settings
from app.main import app


@pytest.mark.parametrize("url,name", [
    ("sqlite:///data.db", "vision_zero_dev"),
    ("postgresql+psycopg://postgres:secret@127.0.0.1:55433/vision_zero_m0", "vision_zero_m0"),
    ("postgresql+psycopg://postgres:secret@example.com:55433/vision_zero_dev", "vision_zero_dev"),
    ("postgresql+psycopg://postgres:secret@127.0.0.1:55433/other", "vision_zero_dev"),
    ("postgresql+psycopg://postgres:secret@127.0.0.1:55433/vision_zero_dev?host=example.com", "vision_zero_dev"),
])
def test_rejects_targets_outside_project(url, name):
    settings = Settings(_env_file=None, database_url=SecretStr(url), database_name=name)
    with pytest.raises(ValueError, match="本机专用库") as rejected:
        settings.connection_url()
    assert "secret" not in str(rejected.value)


def test_live_does_not_require_database_and_ready_hides_invalid_config(monkeypatch):
    monkeypatch.setenv("VISION_ZERO_DATABASE_URL", "invalid-secret-dsn")
    with TestClient(app) as client:
        assert client.get("/health/live").json() == {"status": "alive"}
        response = client.get("/health/ready")
        assert response.status_code == 503
        assert response.json()["reason"] == "configuration_invalid"
        assert "invalid-secret-dsn" not in response.text


@pytest.mark.parametrize("change", ["port", "database", "credentials"])
def test_process_overrides_cannot_redirect_approved_database(monkeypatch, change):
    approved = Settings().connection_url(migration=True)
    if change == "port":
        redirected = approved.set(port=5432)
        monkeypatch.setenv("VISION_ZERO_DB_PORT", "5432")
    elif change == "database":
        redirected = approved.set(database="vision_zero_m1_test_0123456789ab")
        monkeypatch.setenv("VISION_ZERO_DATABASE_NAME", redirected.database)
        monkeypatch.setenv("VISION_ZERO_RUN_DB_TESTS", "0")
    else:
        redirected = approved.set(password="override-secret")
    monkeypatch.setenv("VISION_ZERO_MIGRATION_DATABASE_URL", redirected.render_as_string(hide_password=False))
    with pytest.raises(ValueError, match="本机专用库") as rejected:
        Settings().connection_url(migration=True)
    assert "override-secret" not in str(rejected.value)
