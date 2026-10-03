"""备份恢复的路径和目标拒绝边界；实库演练另保留M7原始证据。"""

import json

import pytest

from app import maintenance


@pytest.mark.parametrize("database", ["vision_zero_dev", "postgres", "vision_zero_m1_test_AABBCCDDEEFF",
                                      "vision_zero_m1_test_123456789abc;DROP DATABASE x", "other_project"])
def test_restore_rejects_unapproved_target_before_io(monkeypatch, database):
    monkeypatch.setattr(maintenance, "bundle_path", lambda *a, **k: pytest.fail("不应读取备份或访问数据库"))
    with pytest.raises(maintenance.MaintenanceError, match="DATABASE_NOT_ALLOWED"):
        maintenance.restore_database("unused", database)


@pytest.mark.parametrize("path", ["../escape", ".m7-work/backups/../escape", "data/raw/backup", ".m7-work/backups/nested/backup"])
def test_bundle_rejects_paths_outside_direct_private_directory(path):
    with pytest.raises((ValueError, maintenance.MaintenanceError)):
        maintenance.bundle_path(path, create=False)


@pytest.mark.parametrize("relative", ["../.env", "raw/../../.env", "snapshots/evil.json", "raw/" + "a" * 32 + "/other.csv"])
def test_external_file_paths_are_not_manifest_controlled(relative):
    with pytest.raises(maintenance.MaintenanceError, match="BACKUP_FILE_REFERENCE_INVALID"):
        maintenance.restored_file_target("vision_zero_m1_test_123456789abc", relative)


def test_restore_detects_corrupt_dump_before_creating_database(monkeypatch, tmp_path):
    monkeypatch.setattr(maintenance, "bundle_path", lambda *a, **k: tmp_path)
    monkeypatch.setattr(maintenance, "workspace_path", lambda p: p)
    monkeypatch.setattr(maintenance, "migration_files", lambda: {"migration": "abc"})
    monkeypatch.setattr(maintenance, "new_database", lambda *a, **k: pytest.fail("校验失败不得建库"))
    (tmp_path / "database.dump").write_bytes(b"corrupt")
    (tmp_path / "manifest.json").write_text(json.dumps({"format": maintenance.FORMAT,
        "migration_files": {"migration": "abc"}, "dump_sha256": "0" * 64, "dump_bytes": 7}), encoding="utf-8")
    with pytest.raises(maintenance.MaintenanceError, match="BACKUP_OR_MIGRATION_MISMATCH"):
        maintenance.restore_database("unused", "vision_zero_m1_test_123456789abc")


@pytest.mark.parametrize("prior", ["config", "restore", "demo"])
def test_existing_target_config_is_never_reused(monkeypatch, tmp_path, prior):
    monkeypatch.setattr(maintenance, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(maintenance, "workspace_path", lambda p: p)
    monkeypatch.setattr(maintenance, "admin_connect", lambda *a, **k: pytest.fail("已有目标材料不得连接"))
    target = "vision_zero_m1_test_123456789abc"
    directory = tmp_path / {"config": ".m1-work/model", "restore": ".m7-work/restores", "demo": ".m8-work/demo"}[prior]
    directory.mkdir(parents=True)
    if prior == "config":
        (directory / (target + ".env")).write_text("retained", encoding="utf-8")
    else:
        (directory / target).mkdir()
    with pytest.raises(maintenance.MaintenanceError, match="TARGET_ALREADY_EXISTS"):
        maintenance.new_database(target)


def test_backup_directory_is_exclusive(monkeypatch, tmp_path):
    monkeypatch.setattr(maintenance, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(maintenance, "workspace_path", lambda p: p)
    monkeypatch.setattr(maintenance, "protect_directory", lambda p: None)
    first = maintenance.bundle_path(".m7-work/backups/retained", create=True)
    (first / "manifest.json").write_text("preserved", encoding="utf-8")
    with pytest.raises(FileExistsError):
        maintenance.bundle_path(".m7-work/backups/retained", create=True)
    assert (first / "manifest.json").read_text(encoding="utf-8") == "preserved"
