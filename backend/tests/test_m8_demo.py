import json
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import demo


DATABASE = "vision_zero_m1_test_a820261003de"


def _valid_state(**changes):
    state = {
        "source_facts": {
            "dataset_revision": 4,
            "table_counts": {"collision": demo.EXPECTED_COLLISIONS},
        },
        "profile_count": demo.EXPECTED_PROFILES,
        "profile_counts": {"HIGH": 10, "MEDIUM": 30, "LOW": 40, "UNKNOWN": 15},
        "task_count": 0,
        "demo_user_count": 0,
        "high_profiles": [11, 12, 13, 14, 15, 16],
        "publishable_high_profiles": [11, 12, 13, 14],
    }
    state.update(changes)
    return state


def _prepare_workspace(monkeypatch, root: Path):
    monkeypatch.setattr(demo, "PROJECT_ROOT", root)
    monkeypatch.setattr(demo, "workspace_path", lambda path: Path(path))
    restore, config, output = demo._verified_paths(DATABASE)
    restore.parent.mkdir(parents=True)
    restore.write_text(json.dumps({"status": "completed", "database": DATABASE}), encoding="utf-8")
    config.parent.mkdir(parents=True)
    config.write_text("", encoding="utf-8")
    return restore, config, output


def test_development_database_is_rejected_before_loading_any_runtime(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("invalid database name must be rejected before runtime or DB access")

    monkeypatch.setattr(demo, "_verified_paths", forbidden)
    monkeypatch.setattr(demo, "_maintenance_module", forbidden)
    monkeypatch.setattr(demo, "_inspect_target", forbidden)

    with pytest.raises(demo.DemoSeedError) as error:
        demo.seed_demo("vision_zero_dev")

    assert error.value.code == "DATABASE_NOT_ALLOWED"


def test_existing_demo_directory_is_refused_before_config_or_database_access(monkeypatch, tmp_path):
    _, _, output = _prepare_workspace(monkeypatch, tmp_path)
    output.mkdir(parents=True)

    def forbidden(*args, **kwargs):
        pytest.fail("existing target must be refused before runtime or DB access")

    monkeypatch.setattr(demo, "_maintenance_module", forbidden)
    monkeypatch.setattr(demo, "_inspect_target", forbidden)

    with pytest.raises(demo.DemoSeedError) as error:
        demo.seed_demo(DATABASE)

    assert error.value.code == "DEMO_TARGET_ALREADY_EXISTS"
    assert list(output.iterdir()) == []


@pytest.mark.parametrize(
    ("state_change", "expected_code"),
    [
        ({"task_count": 1}, "TARGET_ALREADY_HAS_TASKS"),
        ({"demo_user_count": 1}, "DEMO_ACCOUNTS_ALREADY_EXIST"),
    ],
)
def test_nonempty_restored_database_is_refused_before_seed_writes(
    monkeypatch, tmp_path, state_change, expected_code
):
    _, _, output = _prepare_workspace(monkeypatch, tmp_path)
    maintenance = SimpleNamespace(isolated_environment=lambda config: nullcontext())
    monkeypatch.setattr(demo, "_maintenance_module", lambda: maintenance)
    monkeypatch.setattr(demo, "_validate_runtime", lambda *args: None)
    monkeypatch.setattr(demo, "_inspect_target", lambda *args: _valid_state(**state_change))
    monkeypatch.setattr(
        demo,
        "_run_demo",
        lambda *args: pytest.fail("nonempty database must be refused before DB writes"),
    )

    with pytest.raises(demo.DemoSeedError) as error:
        demo.seed_demo(DATABASE)

    assert error.value.code == expected_code
    assert not output.exists()


def test_seedability_requires_the_expected_restore_and_four_publishable_high_profiles():
    state = _valid_state()
    demo._assert_seedable(state)

    for altered, expected_code in (
        (_valid_state(source_facts={"dataset_revision": 4, "table_counts": {"collision": 3}}),
         "RESTORED_DATASET_FACTS_MISMATCH"),
        (_valid_state(publishable_high_profiles=[11, 12, 13]),
         "INSUFFICIENT_ELIGIBLE_HIGH_PROFILES"),
    ):
        with pytest.raises(demo.DemoSeedError) as error:
            demo._assert_seedable(altered)
        assert error.value.code == expected_code


def test_public_summary_contains_only_aggregate_facts_and_task_ids():
    before = _valid_state()
    task_summary = {
        "items": [{"task_id": "42", "status": "COMPLETED", "history_count": 6}],
        "status_counts": {status: int(status == "COMPLETED") for status in (
            "DRAFT", "OPEN", "IN_PROGRESS", "PENDING_REVIEW", "COMPLETED", "CANCELLED"
        )},
        "active_account_count": 4,
    }
    summary = demo._make_summary(
        DATABASE, status="completed", before=before, after=before,
        public_tasks=task_summary, created_user_count=4, disabled_account_count=1,
    )
    rendered = json.dumps(summary, ensure_ascii=False).lower()

    assert summary["tasks"]["items"] == task_summary["items"]
    assert "password" not in rendered
    assert "token" not in rendered
    assert "hash" not in rendered
    assert "username" not in rendered
