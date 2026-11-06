"""Eaton UPS Level-1 ingestion tests; run with pytest tests/test_eaton.py."""
from __future__ import annotations

import csv
from pathlib import Path
from zipfile import ZipFile

import pytest

pl = pytest.importorskip("polars")
from processing.eaton import Eaton


def _export(directory: Path, hour: str, rows: list[dict[str, str]]) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"eaton-{hour}.csv"
    import processing.eaton as eaton
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=eaton.COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    archive = path.with_suffix(".zip")
    with ZipFile(archive, "w") as bundle:
        bundle.write(path, arcname=path.name)
    path.unlink()
    return archive


def _row(minute: int, voltage: str = "238") -> dict[str, str]:
    return dict(dtm=f"2026-11-06 02:{minute:02d}:00", output_source_code="3",
                output_source="normal", on_battery="0", battery_status_code="2",
                battery_status="normal", battery_voltage="83.7",
                battery_capacity_pct="91", battery_runtime_min="115",
                seconds_on_battery="0", input_voltage=voltage,
                input_frequency="50.5", output_voltage="238",
                output_frequency="50.5", output_load="38", active_alarms="0")


def test_extract_zip_and_utc(tmp_path: Path) -> None:
    path = _export(tmp_path, "2026110602", [_row(0), _row(1)])
    df, error = Eaton().extract_to_dataframe(path)
    assert error is None
    assert df.height == 2
    assert df["dtm"].dtype == pl.Datetime("us", "UTC")
    assert df["input_voltage"].to_list() == [238, 238]
    assert df["f_input_voltage"].to_list() == [0, 0]
    assert df["battery_status"].to_list() == ["normal", "normal"]


def test_reject_outside_named_hour(tmp_path: Path) -> None:
    path = _export(tmp_path, "2026110603", [_row(0)])
    df, error = Eaton().extract_to_dataframe(path)
    assert df.is_empty()
    assert error is not None and "outside" in error


def test_missing_value_is_flagged(tmp_path: Path) -> None:
    path = _export(tmp_path, "2026110602", [_row(0, voltage="")])
    df, error = Eaton().extract_to_dataframe(path)
    assert error is None
    assert df["input_voltage"].to_list() == [None]
    assert df["f_input_voltage"].to_list() == [1]


def test_idempotence_preserves_manual_flags(tmp_path: Path) -> None:
    source = tmp_path / "incoming"
    target = tmp_path / "level1"
    _export(source, "2026110602", [_row(0), _row(1)])
    processor = Eaton()
    _, errors = processor.compile_to_parquet(source, target)
    assert not errors
    parquet = target / "2026" / "11" / "eaton.parquet"
    df = pl.read_parquet(parquet)
    assert df.height == 2
    df = df.with_columns(pl.when(pl.col("dtm") == df["dtm"][0]).then(2)
                         .otherwise(pl.col("f_input_voltage")).alias("f_input_voltage"))
    df.write_parquet(parquet)
    _, errors = processor.compile_to_parquet(source, target)
    assert not errors
    after = pl.read_parquet(parquet)
    assert after.height == 2
    assert after["f_input_voltage"].to_list() == [2, 0]
