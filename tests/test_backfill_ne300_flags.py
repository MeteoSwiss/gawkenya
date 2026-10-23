"""Regression for one-off state-1/2 transient correction, safe QC, and IO."""
from datetime import UTC, datetime, timedelta
from pathlib import Path

import polars as pl

from housekeeping.backfill_ne300_flags import reflag_ne300, process_file


def sample() -> pl.DataFrame:
    t0 = datetime(2026, 10, 23, tzinfo=UTC)
    states = [0, 1, 1, 4, 0, 2, 2, 6, 0, 1, 3, 0, 2, 5, 7]
    return pl.DataFrame({
        "dtm": [t0 + timedelta(minutes=i) for i in range(len(states))],
        "4035": states,
        "2635000": [1.0] * len(states),
        "6635000": [3.0] * len(states),
        "5002": [42.0] * len(states),
        # Values from previous conflicting mapping packages.
        "f_2635000": pl.Series([0, 5, 3, 3, 2, 6, 4, 4, 2, 3, 5, 0, 4, 5, 6], dtype=pl.Int8),
        "manual": ["unchanged"] * len(states),
    }, schema_overrides={"dtm": pl.Datetime("us", "UTC")})


def test_corrects_known_incorrect_flags_without_lookahead() -> None:
    frame = sample()
    result, info = reflag_ne300(frame)
    assert info.status == "would-update"
    assert result["f_2635000"].to_list() == [0, 2, 2, 5, 2, 2, 2, 6, 2, 2, 3, 0, 2, 4, 6]
    assert result["4035"].to_list() == frame["4035"].to_list()
    assert result["2635000"].to_list() == frame["2635000"].to_list()
    assert result["manual"].to_list() == frame["manual"].to_list()
    assert "f_6635000" in result.columns
    again, second = reflag_ne300(result)
    assert second.changed_flags == 0
    assert again.equals(result)


def test_preserves_manual_invalid_unless_explicit_override() -> None:
    frame = sample().with_columns(pl.Series("f_6635000", [1] * 15, dtype=pl.Int8))
    safe, _ = reflag_ne300(frame)
    assert safe["f_6635000"].to_list() == [1] * 15
    forced, _ = reflag_ne300(frame, overwrite_all=True)
    assert forced["f_6635000"].to_list() == [1, 2, 2, 5, 1, 2, 2, 6, 1, 2, 3, 1, 2, 4, 1]


def test_dry_run_write_and_backup(tmp_path: Path) -> None:
    path = tmp_path / "ne300.parquet"
    original = sample()
    original.write_parquet(path)
    assert process_file(path).status == "would-update"
    assert pl.read_parquet(path).equals(original)
    assert process_file(path, write=True, backup=True).status == "updated"
    assert path.with_name("ne300.parquet.bak").exists()
    assert process_file(path).status == "unchanged"


def test_missing_status_is_skipped() -> None:
    frame = sample().drop("4035")
    result, outcome = reflag_ne300(frame)
    assert outcome.status == "skipped"
    assert result.equals(frame)


def test_preserves_row_order() -> None:
    frame = sample().reverse()
    revised, _ = reflag_ne300(frame)
    assert revised["dtm"].to_list() == frame["dtm"].to_list()
