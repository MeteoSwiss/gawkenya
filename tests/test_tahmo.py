"""Regression tests for hourly TAHMO ZENTRA exports and Level-1 merging.

Use explicitly named hourly fixtures: the fixture directory may also contain
bulk ZENTRA downloads, whose ZIP/CSV layout is deliberately not accepted by
``processing.tahmo.TAHMO``.
"""
from __future__ import annotations

import csv
import io
import shutil
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import polars as pl
import pytest
import yaml

from processing.tahmo import TAHMO


CONFIG = Path(__file__).resolve().parents[1] / "config" / "mch-mkn.yml"
SAMPLES = Path(__file__).resolve().parent / "data" / "tahmo"
HOURLY_SAMPLE_NAMES = (
    "tahmo-z6-02149-mrid652267-652278.zip",
    "tahmo-z6-02149-mrid652279-652290.zip",
)


@pytest.fixture
def processor() -> TAHMO:
    """Create a TAHMO processor from the station configuration."""
    return TAHMO(yaml.safe_load(CONFIG.read_text(encoding="utf-8"))["tahmo"])


@pytest.fixture
def hourly_samples() -> tuple[Path, Path]:
    """Return the two known-good hourly exports, never arbitrary ZIPs."""
    samples = tuple(SAMPLES / name for name in HOURLY_SAMPLE_NAMES)
    for path in samples:
        if not path.is_file():
            pytest.fail(f"Missing TAHMO hourly test fixture: {path}")
    return samples[0], samples[1]


def _make_file(path: Path, rows: list[dict[str, str]]) -> None:
    """Build a single-CSV TAHMO ZIP with the supplied long-format records."""
    with ZipFile(path, "w", ZIP_DEFLATED) as archive:
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
        archive.writestr(path.with_suffix(".csv").name, buf.getvalue())


def test_units_and_flags(
    processor: TAHMO,
    hourly_samples: tuple[Path, Path],
) -> None:
    """Read source errors separately from initial editable QC flags."""
    sample = hourly_samples[0]
    df, err = processor.extract_to_dataframe(sample)
    assert err is None
    assert df.height == 12
    assert df["dtm"].dtype == pl.Datetime("us", "UTC")
    assert "precipitation_amount" in df.columns
    assert "precipitation" not in df.columns
    assert df["f_atmospheric_pressure"].to_list() == [1] * 12
    assert df["f_air_temperature"].to_list() == [0] * 12
    assert df["air_temperature_err"].to_list() == [0] * 12
    assert df["atmospheric_pressure_err"].to_list() == [1] * 12
    assert df["precipitation_amount_err"].dtype == pl.Int8


def test_repeat_and_overlap(
    processor: TAHMO,
    hourly_samples: tuple[Path, Path],
    tmp_path: Path,
) -> None:
    """Importing overlapping or repeated hourly files is idempotent."""
    source = tmp_path / "incoming"
    target = tmp_path / "level1"
    archive = tmp_path / "archive"
    source.mkdir()
    for sample in hourly_samples:
        shutil.copy2(sample, source / sample.name)

    _, errors = processor.compile_to_parquet(source, target, archive=archive)
    assert not errors
    output = target / "2026" / "10" / "tahmo.parquet"
    first = pl.read_parquet(output)
    assert first.height == 24
    assert first["dtm"].n_unique() == 24

    sample = hourly_samples[0]
    shutil.copy2(sample, source / sample.name)
    _, errors = processor.compile_to_parquet(source, target, archive=archive)
    assert not errors
    assert pl.read_parquet(output).equals(first)


def test_bad_unit_keeps_original(
    processor: TAHMO,
    hourly_samples: tuple[Path, Path],
    tmp_path: Path,
) -> None:
    """Reject unexpected measurement units instead of altering values."""
    sample = hourly_samples[0]
    with ZipFile(sample) as archive:
        members = [name for name in archive.namelist() if name.lower().endswith(".csv")]
        assert len(members) == 1
        with archive.open(members[0]) as raw:
            rows = list(csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8-sig")))
    rows[0]["units"] = "Kelvin"
    path = tmp_path / sample.name
    _make_file(path, rows)

    df, error = processor.extract_to_dataframe(path)
    assert df.is_empty()
    assert "Unexpected unit" in (error or "")


def test_existing_manual_qc_preserved_and_source_errors_not_inferred(
    processor: TAHMO,
    hourly_samples: tuple[Path, Path],
    tmp_path: Path,
) -> None:
    """Repeated imports cannot overwrite manual QC or invent old source errors."""
    source = tmp_path / "incoming"
    target = tmp_path / "level1"
    source.mkdir()
    sample = hourly_samples[0]
    shutil.copy2(sample, source / sample.name)
    _, errors = processor.compile_to_parquet(source, target)
    assert not errors

    output = target / "2026" / "10" / "tahmo.parquet"
    current = pl.read_parquet(output).with_columns(
        pl.lit(2, dtype=pl.Int8).alias("f_air_temperature")
    )
    current.write_parquet(output)

    _, errors = processor.compile_to_parquet(source, target)
    assert not errors
    result = pl.read_parquet(output)
    assert result["f_air_temperature"].to_list() == [2] * 12
    assert result["air_temperature_err"].to_list() == [0] * 12

    legacy = result.drop([col for col in result.columns if col.endswith("_err")])
    legacy.write_parquet(output)
    _, errors = processor.compile_to_parquet(source, target)
    assert not errors
    upgraded = pl.read_parquet(output)
    assert upgraded["air_temperature_err"].null_count() == upgraded.height
    assert upgraded["f_air_temperature"].to_list() == [2] * 12


def test_batch_download_is_not_an_hourly_input(
    processor: TAHMO,
    tmp_path: Path,
) -> None:
    """An unrelated ZIP must not prevent compilation or create output data."""
    source = tmp_path / "incoming"
    target = tmp_path / "level1"
    source.mkdir()
    batch = source / "GAW Station(z6-02149)-1792165034.zip"
    with ZipFile(batch, "w", ZIP_DEFLATED) as archive:
        archive.writestr("Configuration.csv", "dummy")
        archive.writestr("Metadata.csv", "dummy")
    assert not processor.should_process_file(batch)
    result, errors = processor.compile_to_parquet(source, target)
    assert result.is_empty()
    assert not errors
    assert batch.exists()
    assert not (target / "2026" / "10" / "tahmo.parquet").exists()
