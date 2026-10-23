"""Concise, instrument-style console logging for hourly TAHMO ingestion."""
from __future__ import annotations

import logging
import shutil
from pathlib import Path

import polars as pl
import yaml

from processing.tahmo import TAHMO

ROOT = Path(__file__).resolve().parents[1]
SAMPLE_NAMES = (
    "tahmo-z6-02149-mrid652267-652278.zip",
    "tahmo-z6-02149-mrid652279-652290.zip",
)


def _processor() -> TAHMO:
    config = yaml.safe_load((ROOT / "config/mch-mkn.yml").read_text(encoding="utf-8"))
    return TAHMO(config["tahmo"])


def _info_messages(caplog) -> list[str]:
    return [record.getMessage() for record in caplog.records
            if record.name == "tahmo" and record.levelno == logging.INFO]


def test_concise_logging_per_file_one_partition_summary(tmp_path: Path, caplog) -> None:
    source, target, archive = (tmp_path / name for name in ("incoming", "level1", "archive"))
    source.mkdir()
    for name in SAMPLE_NAMES:
        sample = ROOT / "tests/data/tahmo" / name
        assert sample.exists(), f"Missing hourly fixture: {sample}"
        shutil.copy2(sample, source / name)

    with caplog.at_level(logging.INFO, logger="tahmo"):
        _result, errors = _processor().compile_to_parquet(source, target, archive=archive)
    assert errors == {}
    messages = _info_messages(caplog)

    for name in SAMPLE_NAMES:
        assert messages.count(f"Processing {name}") == 1
        assert (archive / "2026/10" / name).exists()

    path = target / "2026/10/tahmo.parquet"
    assert messages.count(f"✔ Written 24 new rows to {path}") == 1
    assert messages.count("✔ Parquet compilation completed. Total rows: 24") == 1
    assert len(messages) == 4  # 2 input files + 1 monthly summary + 1 completion
    assert pl.read_parquet(path).height == 24


def test_repeated_file_reports_zero_new_rows(tmp_path: Path, caplog) -> None:
    source, target = tmp_path / "incoming", tmp_path / "level1"
    source.mkdir()
    sample = ROOT / "tests/data/tahmo" / SAMPLE_NAMES[0]
    assert sample.exists()
    shutil.copy2(sample, source / sample.name)
    processor = _processor()
    processor.compile_to_parquet(source, target)
    caplog.clear()

    with caplog.at_level(logging.INFO, logger="tahmo"):
        _result, errors = processor.compile_to_parquet(source, target)
    assert errors == {}
    messages = _info_messages(caplog)
    assert f"✔ Written 0 new rows to {target / '2026/10/tahmo.parquet'}" in messages
    assert "✔ Parquet compilation completed. Total rows: 12" in messages


def test_empty_and_invalid_inputs_are_reported(tmp_path: Path, caplog) -> None:
    source, target = tmp_path / "incoming", tmp_path / "level1"
    source.mkdir()
    with caplog.at_level(logging.INFO, logger="tahmo"):
        _result, errors = _processor().compile_to_parquet(source, target)
    assert not errors
    assert _info_messages(caplog) == ["✔ Parquet compilation completed. Total rows: 0"]

    bad = source / SAMPLE_NAMES[0]
    bad.write_bytes(b"not a ZIP")
    caplog.clear()
    with caplog.at_level(logging.INFO, logger="tahmo"):
        _result, errors = _processor().compile_to_parquet(source, target)
    assert str(bad) in errors
    assert f"Processing {bad.name}" in _info_messages(caplog)
    assert any(r.levelno == logging.ERROR and "Invalid TAHMO source" in r.getMessage()
               for r in caplog.records)
    assert not list(target.rglob("*.parquet"))
