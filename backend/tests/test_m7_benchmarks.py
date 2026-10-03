from datetime import date
from pathlib import Path
import sys

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from benchmarks.benchmark_core import (  # noqa: E402
    B01_END,
    B01_PAGE_SIZE,
    B01_START,
    MEASURE_REPEATS,
    MIN_YEAR_COLLISIONS,
    YEAR_END,
    YEAR_START,
    equivalent_results,
    median,
    percentile,
    prepare_output_dir,
    result_summary,
    validate_database_name,
)
from benchmarks.run_benchmarks import (  # noqa: E402
    B03_CENTER_SQL,
    B03_MATCH_COUNT_SQL,
    DATE_SQL,
    LOCATION_DATE_SQL,
    NEARBY_SQL,
    VEHICLE_DISTINCT_SQL,
    VEHICLE_EXISTS_SQL,
    _require_b03_nonempty,
    main,
    _query_for,
)


def test_database_name_is_a_single_random_test_database_only():
    assert validate_database_name("vision_zero_m1_test_012345abcdef") == "vision_zero_m1_test_012345abcdef"
    for unsafe in (
        "vision_zero_dev",
        "vision_zero_m1_test_012345abcdeF",
        "vision_zero_m1_test_012345abcdef;drop database vision_zero_dev",
        "vision_zero_m1_test_012345abcde",
        "",
    ):
        with pytest.raises(ValueError):
            validate_database_name(unsafe)


def test_cli_rejects_dev_before_creating_output_or_opening_database(tmp_path, capsys):
    output = tmp_path / "must-not-be-created"
    assert main(["--database", "vision_zero_dev", "--output", str(output)]) == 1
    assert not output.exists()
    assert "ValueError" in capsys.readouterr().err


def test_output_directory_creation_never_overwrites_existing_results(tmp_path):
    empty = tmp_path / "fresh"
    assert prepare_output_dir(empty) == empty.resolve()
    assert list(empty.iterdir()) == []

    occupied = tmp_path / "occupied"
    occupied.mkdir()
    marker = occupied / "summary.md"
    marker.write_text("existing evidence", encoding="utf-8")
    with pytest.raises(FileExistsError):
        prepare_output_dir(occupied)
    assert marker.read_text(encoding="utf-8") == "existing evidence"

    regular_file = tmp_path / "not-a-directory"
    regular_file.write_text("keep", encoding="utf-8")
    with pytest.raises(FileExistsError):
        prepare_output_dir(regular_file)


def test_result_digest_is_stable_and_contains_no_row_values():
    rows = [(17, date(2025, 1, 2)), (18, date(2025, 1, 3))]
    summary = result_summary(rows)
    assert summary == result_summary(iter(rows))
    assert summary["row_count"] == 2
    assert len(summary["sha256"]) == 64
    assert "17" not in str(summary) and "2025-01-02" not in str(summary)
    assert equivalent_results(summary, dict(summary))
    assert not equivalent_results(summary, {"row_count": 3, "sha256": summary["sha256"]})


def test_nearest_rank_p95_and_median_for_twenty_measurements():
    observations = list(range(1, MEASURE_REPEATS + 1))
    assert percentile(observations, 0.95) == 19
    assert median(observations) == 10.5
    with pytest.raises(ValueError):
        percentile([], 0.95)


def test_benchmark_scope_is_fixed_to_full_2025_requirement():
    assert YEAR_START == date(2025, 1, 1)
    assert YEAR_END == date(2026, 1, 1)
    assert MIN_YEAR_COLLISIONS == 85_546
    assert "crash_date >= %s AND c.crash_date < %s" in DATE_SQL
    assert "crash_date >= %s AND c.crash_date < %s" in LOCATION_DATE_SQL


def test_b01_is_january_2025_first_page_with_stable_date_id_order():
    assert B01_START == date(2025, 1, 1)
    assert B01_END == date(2025, 2, 1)
    assert B01_PAGE_SIZE == 100
    assert "ORDER BY c.crash_date DESC, c.collision_id DESC" in DATE_SQL
    assert DATE_SQL.endswith("LIMIT 100")


def test_b03_uses_identical_geography_query_for_both_index_conditions():
    assert _query_for("B03", "A") == _query_for("B03", "B") == NEARBY_SQL
    assert "ST_DWithin" in NEARBY_SQL
    assert "l.geom::geography" in NEARBY_SQL
    assert "ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography" in NEARBY_SQL
    assert "SELECT DISTINCT l.location_id, l.geom" in B03_CENTER_SQL
    assert "ORDER BY ST_Distance(" in B03_CENTER_SQL
    assert "LIMIT 1" in B03_CENTER_SQL
    assert "ST_DWithin" in B03_MATCH_COUNT_SQL
    assert _require_b03_nonempty(1) == 1
    with pytest.raises(ValueError, match="没有 2025 年事故"):
        _require_b03_nonempty(0)


def test_b04_uses_semantically_safe_collision_scope_variants():
    assert "EXISTS" in VEHICLE_EXISTS_SQL
    assert "SELECT DISTINCT v.collision_id" in VEHICLE_DISTINCT_SQL
    assert "SUM(DISTINCT" not in VEHICLE_EXISTS_SQL.upper()
    assert "SUM(DISTINCT" not in VEHICLE_DISTINCT_SQL.upper()
    for field in ("COUNT(*) AS collision_count", "SUM(s.persons_injured)", "SUM(s.persons_killed)"):
        assert field in VEHICLE_EXISTS_SQL
        assert field in VEHICLE_DISTINCT_SQL
