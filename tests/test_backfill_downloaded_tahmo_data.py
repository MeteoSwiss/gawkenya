"""Regression tests for TAHMO calibrated batch-download backfill."""
from __future__ import annotations

import csv
import io
from datetime import date, datetime, timezone
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import polars as pl
import pytest

from housekeeping.backfill_downloaded_tahmo_data import (
    BatchBackfill,
    SOURCE_UNITS,
    _source_column_indices,
)


VARIABLES = {
    "Air Temperature": "air_temperature",
    "Atmospheric Pressure": "atmospheric_pressure",
    "Battery Percent": "battery_percent",
    "Battery Voltage": "battery_voltage",
    "Gust Speed": "gust_speed",
    "Lightning Activity": "lightning_activity",
    "Lightning Distance": "lightning_distance",
    "Logger Temperature": "logger_temperature",
    "Max Precip Rate": "max_precip_rate",
    "Precipitation": "precipitation_amount",
    "RH Sensor Temp": "rh_sensor_temp",
    "Reference Pressure": "reference_pressure",
    "Solar Radiation": "solar_radiation",
    "VPD": "vpd",
    "Vapor Pressure": "vapor_pressure",
    "Wind Direction": "wind_direction",
    "Wind Speed": "wind_speed",
    "X-axis Level": "x_axis_level",
    "Y-axis Level": "y_axis_level",
}
CONFIG = {"device_sn": "z6-02149", "variables": VARIABLES}


def _fixture_csvs(*, temperature: float, missing_pressure: bool = True) -> tuple[bytes, bytes]:
    calibrated_header = ["Timestamps", *[f"{SOURCE_UNITS[name]} {name}".strip() for name in VARIABLES]]
    raw_header = ["Timestamps", "Device RID", "UTC Offset"]
    dtm = "2026/10/15 12:00:00"
    values = {
        "Air Temperature": str(temperature),
        "Atmospheric Pressure": "" if missing_pressure else "80.2",
        "Precipitation": "1.2",
    }
    calibrated = io.StringIO()
    writer = csv.writer(calibrated)
    writer.writerow(["z6-02149", *(["Port1"] * len(VARIABLES))])
    writer.writerow(["# Records: 1", *([""] * len(VARIABLES))])
    writer.writerow(calibrated_header)
    writer.writerow([dtm, *[values.get(name, "1") for name in VARIABLES]])
    raw = io.StringIO()
    writer = csv.writer(raw)
    writer.writerow(["z6-02149", "", ""])
    writer.writerow(["# Records: 1", "", ""])
    writer.writerow(raw_header)
    writer.writerow([dtm, "550738", "UTC+03:00"])
    return calibrated.getvalue().encode("utf-8-sig"), raw.getvalue().encode("utf-8-sig")


def _make_export(archive: Path, *, temperature: float = 6.0, multiple: bool = False) -> None:
    calibrated, raw = _fixture_csvs(temperature=temperature)
    with ZipFile(archive, "w", ZIP_DEFLATED) as z:
        z.writestr("GAW Station(z6-02149)-Configuration 1-123.5.csv", calibrated)
        z.writestr("GAW Station(z6-02149)-Raw-Configuration 1-123.5.csv", raw)
        z.writestr("GAW Station(z6-02149)-Metadata-123.5.csv", b"Configuration,Device Name,GAW Station\n")
        if multiple:
            z.writestr("set2/GAW Station(z6-02149)-Configuration 1-456.5.csv", calibrated)
            z.writestr("set2/GAW Station(z6-02149)-Raw-Configuration 1-456.5.csv", raw)


def _writer(
    target: Path,
    *,
    write: bool = True,
    replace_values: bool = False,
    batch_rows: int = 1,
    utc_offset: str | None = None,
) -> BatchBackfill:
    return BatchBackfill(
        CONFIG,
        target,
        write=write,
        replace_values=replace_values,
        batch_rows=batch_rows,
        utc_offset=utc_offset,
    )


def test_create_level1_native_units_timezone_and_source_errors(tmp_path: Path) -> None:
    source = tmp_path / "download.zip"
    _make_export(source)
    target = tmp_path / "level1" / "mkn"
    importer = _writer(target)
    importer.process_zip(source)
    parquet = target / "2026" / "10" / "tahmo.parquet"
    df = pl.read_parquet(parquet)
    assert df.height == 1
    assert df["dtm"].dtype == pl.Datetime("us", "UTC")
    assert df["dtm"][0] == datetime(2026, 10, 15, 9, tzinfo=timezone.utc)
    assert df["device_rid"][0] == 550738
    assert df["mrid"][0] is None
    assert df["air_temperature"][0] == 6.0
    assert df["precipitation_amount"][0] == 1.2
    assert df["f_air_temperature"][0] == 0
    assert df["air_temperature_err"][0] is None  # no Boolean source error in export
    assert df["f_atmospheric_pressure"][0] == 1
    assert df["atmospheric_pressure_err"][0] is None


def test_overlap_preserves_qc_and_source_errors_but_fills_missing(tmp_path: Path) -> None:
    source = tmp_path / "download.zip"
    _make_export(source)
    target = tmp_path / "level1" / "mkn"
    parquet = target / "2026" / "10" / "tahmo.parquet"
    parquet.parent.mkdir(parents=True)
    date = datetime(2026, 10, 15, 9, tzinfo=timezone.utc)
    original = pl.DataFrame({
        "dtm": [date], "device_sn": ["z6-02149"], "mrid": [652200],
        "air_temperature": [11.0], "f_air_temperature": [2], "air_temperature_err": [1],
        "precipitation_amount": [None], "f_precipitation_amount": [1],
        "atmospheric_pressure": [None], "f_atmospheric_pressure": [1],
        "custom_comment": ["reviewed"],
    }, schema_overrides={"dtm": pl.Datetime("us", "UTC")})
    original.write_parquet(parquet)
    backfill = _writer(target)
    backfill.process_zip(source)
    df = pl.read_parquet(parquet)
    assert df.height == 1
    assert df["air_temperature"][0] == 11.0  # default fill-only
    assert df["f_air_temperature"][0] == 2  # manual flag
    assert df["air_temperature_err"][0] == 1  # previous original source flag
    assert df["mrid"][0] == 652200  # ZENTRA MRID != Device RID
    assert df["device_rid"][0] == 550738
    assert df["precipitation_amount"][0] == 1.2
    assert df["f_precipitation_amount"][0] == 1  # never infer manual flag change
    assert df["custom_comment"][0] == "reviewed"

    backfill.process_zip(source)
    assert pl.read_parquet(parquet).equals(df)  # re-run is idempotent


def test_replace_measurements_not_flags(tmp_path: Path) -> None:
    source = tmp_path / "download.zip"
    _make_export(source, temperature=15.0)
    target = tmp_path / "level1"
    initial = _writer(target)
    initial.process_zip(source)
    parquet = target / "2026" / "10" / "tahmo.parquet"
    df = pl.read_parquet(parquet).with_columns(pl.lit(2, dtype=pl.Int8).alias("f_air_temperature"))
    df.write_parquet(parquet)
    _make_export(source, temperature=17.0)
    _writer(target, replace_values=True).process_zip(source)
    after = pl.read_parquet(parquet)
    assert after["air_temperature"][0] == 17.0
    assert after["f_air_temperature"][0] == 2
    assert after["air_temperature_err"][0] is None


def test_dry_run_creates_no_files(tmp_path: Path) -> None:
    source = tmp_path / "download.zip"
    _make_export(source, multiple=True)
    target = tmp_path / "level1"
    importer = _writer(target, write=False)
    importer.process_zip(source)
    assert importer.stats["input_rows"] == 2
    assert importer.stats["exports"] == 2
    assert not target.exists()


def test_invalid_raw_timestamp_rejected(tmp_path: Path) -> None:
    source = tmp_path / "download.zip"
    calibrated, raw = _fixture_csvs(temperature=8.0)
    bad_raw = raw.replace(b"2026/10/15 12:00:00", b"2026/10/15 12:05:00")
    with ZipFile(source, "w") as z:
        z.writestr("GAW Station(z6-02149)-Configuration 1-123.csv", calibrated)
        z.writestr("GAW Station(z6-02149)-Raw-Configuration 1-123.csv", bad_raw)
    with pytest.raises(ValueError, match="timestamps do not match"):
        _writer(tmp_path / "out", write=False).process_zip(source)


@pytest.mark.parametrize(
    ("symbolic", "textual"),
    [
        ("°C Air Temperature", "degree_C Air Temperature"),
        ("°C Logger Temperature", "degree_C Logger Temperature"),
        ("°C RH Sensor Temp", "degree_C RH Sensor Temp"),
        ("° Wind Direction", "degrees Wind Direction"),
        ("° X-axis Level", "degrees X-axis Level"),
        ("° Y-axis Level", "degrees Y-axis Level"),
        ("W/m² Solar Radiation", "W/m2 Solar Radiation"),
    ],
)
def test_calibrated_header_unit_aliases(symbolic: str, textual: str) -> None:
    """Both ZENTRA spellings must resolve to the same variable index."""
    headers = ["Timestamps", *[f"{unit} {name}".strip() for name, unit in SOURCE_UNITS.items()]]
    before = _source_column_indices(headers, VARIABLES)
    headers[headers.index(symbolic)] = textual
    after = _source_column_indices(headers, VARIABLES)
    assert after == before


def test_full_archive_header_spellings_end_to_end(tmp_path: Path) -> None:
    """A calibrated CSV using all seven alternate prefixes imports normally."""
    calibrated, raw = _fixture_csvs(temperature=14.5)
    calibrated = calibrated.replace(b"W/m\xc2\xb2 Solar Radiation", b"W/m2 Solar Radiation")
    calibrated = calibrated.replace("°C ".encode("utf-8"), b"degree_C ")
    calibrated = calibrated.replace("° ".encode("utf-8"), b"degrees ")
    archive = tmp_path / "complete-export.zip"
    with ZipFile(archive, "w", ZIP_DEFLATED) as z:
        z.writestr("GAW Station(z6-02149)-Configuration 1-123.5.csv", calibrated)
        z.writestr("GAW Station(z6-02149)-Raw-Configuration 1-123.5.csv", raw)
    output = tmp_path / "level1" / "mkn"
    _writer(output).process_zip(archive)
    df = pl.read_parquet(output / "2026" / "10" / "tahmo.parquet")
    assert df.height == 1
    assert df["air_temperature"].to_list() == [14.5]
    assert df["precipitation_amount"].to_list() == [1.2]


def test_unknown_unit_is_still_rejected() -> None:
    """Unit spelling tolerance must not conceal changes in measurement units."""
    headers = ["Timestamps", *[f"{unit} {name}".strip() for name, unit in SOURCE_UNITS.items()]]
    headers[headers.index("mm Precipitation")] = "inches Precipitation"
    with pytest.raises(ValueError, match="Calibrated CSV header mismatch"):
        _source_column_indices(headers, VARIABLES)


def test_normalization_detects_duplicate_equivalent_headers() -> None:
    """A source must not contain both unit spellings for the same variable."""
    headers = ["Timestamps", *[f"{unit} {name}".strip() for name, unit in SOURCE_UNITS.items()]]
    headers[headers.index("°C Air Temperature")] = "degree_C Air Temperature"
    headers.append("°C Air Temperature")
    # _source_column_indices also canonicalizes, matching direct callers.
    with pytest.raises(ValueError, match="Duplicate calibrated CSV column headers"):
        _source_column_indices(headers, VARIABLES)


def _make_unset_offset_export(path: Path, *, offset: str = "Not Set") -> None:
    """Build a calibrated/raw export with a specified raw UTC Offset cell."""
    calibrated, raw = _fixture_csvs(temperature=13.2)
    raw = raw.replace(b"UTC+03:00", offset.encode("utf-8"))
    with ZipFile(path, "w", ZIP_DEFLATED) as archive:
        archive.writestr("GAW Station(z6-02149)-Configuration 1-123.csv", calibrated)
        archive.writestr("GAW Station(z6-02149)-Raw-Configuration 1-123.csv", raw)


def test_unset_raw_utc_offset_requires_explicit_fallback(tmp_path: Path) -> None:
    """Never reinterpret an unset raw offset as UTC or EAT without consent."""
    source = tmp_path / "download.zip"
    _make_unset_offset_export(source)
    target = tmp_path / "level1"
    with pytest.raises(ValueError, match="raw UTC Offset 'Not Set' is unset; supply --utc-offset"):
        _writer(target, write=False).process_zip(source)
    assert not target.exists()


def test_verified_offset_recovers_unset_raw_offset(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """An explicit fallback yields the expected UTC timestamp and an audit warning."""
    source = tmp_path / "download.zip"
    _make_unset_offset_export(source)
    target = tmp_path / "level1"
    importer = _writer(target, utc_offset="UTC+03:00")
    importer.process_zip(source)
    df = pl.read_parquet(target / "2026" / "10" / "tahmo.parquet")
    assert df["dtm"][0] == datetime(2026, 10, 15, 9, tzinfo=timezone.utc)
    assert df["air_temperature"][0] == 13.2
    assert df["air_temperature_err"][0] is None
    assert "using verified --utc-offset UTC+03:00" in caplog.text


def test_explicit_raw_offset_mismatch_is_rejected(tmp_path: Path) -> None:
    """Override must not silently replace a differently configured raw offset."""
    source = tmp_path / "download.zip"
    _make_unset_offset_export(source, offset="UTC+02:00")
    with pytest.raises(ValueError, match="disagrees with --utc-offset"):
        _writer(tmp_path / "out", write=False, utc_offset="UTC+03:00").process_zip(source)


@pytest.mark.parametrize("offset", ["", "not set", " Not Set "])
def test_blank_or_mixed_case_not_set_offset(tmp_path: Path, offset: str) -> None:
    """All observed unset-offset variants require the same explicit fallback."""
    source = tmp_path / "download.zip"
    _make_unset_offset_export(source, offset=offset)
    _writer(tmp_path / "out", utc_offset="UTC+03:00").process_zip(source)
    df = pl.read_parquet(tmp_path / "out" / "2026" / "10" / "tahmo.parquet")
    assert df["dtm"][0] == datetime(2026, 10, 15, 9, tzinfo=timezone.utc)


def _historical_pair(
    records: list[tuple[str, str, float]],
) -> tuple[bytes, bytes]:
    """Create historical calibrated/raw rows with matching timestamps and offsets."""
    calibrated, raw = _fixture_csvs(temperature=10.0)
    calibrated_rows = list(csv.reader(io.StringIO(calibrated.decode("utf-8-sig"))))
    raw_rows = list(csv.reader(io.StringIO(raw.decode("utf-8-sig"))))
    calibrated_rows[1][0] = f"# Records: {len(records)}"
    raw_rows[1][0] = f"# Records: {len(records)}"
    temp_index = calibrated_rows[2].index("°C Air Temperature")
    calibrated_sample = calibrated_rows[3]
    raw_sample = raw_rows[3]
    calibrated_rows = calibrated_rows[:3]
    raw_rows = raw_rows[:3]
    for n, (timestamp, utc_offset, temperature) in enumerate(records):
        calibrated_record = calibrated_sample.copy()
        calibrated_record[0] = timestamp
        calibrated_record[temp_index] = str(temperature)
        calibrated_rows.append(calibrated_record)
        raw_record = raw_sample.copy()
        raw_record[0] = timestamp
        raw_record[1] = str(550700 + n)
        raw_record[2] = utc_offset
        raw_rows.append(raw_record)

    def encode(rows: list[list[str]]) -> bytes:
        stream = io.StringIO()
        csv.writer(stream).writerows(rows)
        return stream.getvalue().encode("utf-8-sig")

    return encode(calibrated_rows), encode(raw_rows)


def test_only_config7_skips_other_configuration_before_parsing(tmp_path: Path) -> None:
    """Pre-installation configurations must not trigger Not Set/header errors."""
    source = tmp_path / "all-configurations.zip"
    config2_cal, config2_raw = _historical_pair(
        [("2023/07/24 12:00:00", "Not Set", 13.0)]
    )
    config7_cal, config7_raw = _historical_pair(
        [("2023/10/19 12:00:00", "UTC+03:00", 21.5)]
    )
    with ZipFile(source, "w", ZIP_DEFLATED) as archive:
        archive.writestr("GAW Station(z6-02149)-Configuration 2-123.csv", config2_cal)
        archive.writestr("GAW Station(z6-02149)-Raw-Configuration 2-123.csv", config2_raw)
        archive.writestr("GAW Station(z6-02149)-Configuration 7-123.csv", config7_cal)
        archive.writestr("GAW Station(z6-02149)-Raw-Configuration 7-123.csv", config7_raw)

    importer = BatchBackfill(
        CONFIG, tmp_path / "level1", write=True, configuration=7,
        start_date=date(2023, 10, 1), skip_utc_offsets=("UTC+00:00",),
    )
    importer.process_zip(source)
    frame = pl.read_parquet(tmp_path / "level1" / "2023" / "10" / "tahmo.parquet")
    assert frame["air_temperature"].to_list() == [21.5]
    assert frame["dtm"][0] == datetime(2023, 10, 19, 9, tzinfo=timezone.utc)
    assert importer.stats["skipped_configurations"] == 1
    assert importer.stats["input_rows"] == 1


def test_historical_cutoff_and_five_zero_offsets_are_excluded(tmp_path: Path) -> None:
    """Do not import July records or the five explicitly UTC+00:00 records."""
    source = tmp_path / "historical.zip"
    records = [("2023/07/24 14:10:00", "UTC+03:00", 13.0)]
    records += [
        (f"2023/10/20 10:{minute:02d}:00", "UTC+00:00", 14.0)
        for minute in (5, 10, 15, 20, 25)
    ]
    records.append(("2023/10/20 13:30:00", "UTC+03:00", 24.1))
    calibrated, raw = _historical_pair(records)
    with ZipFile(source, "w", ZIP_DEFLATED) as archive:
        archive.writestr("GAW Station(z6-02149)-Configuration 7-123.csv", calibrated)
        archive.writestr("GAW Station(z6-02149)-Raw-Configuration 7-123.csv", raw)

    importer = BatchBackfill(
        CONFIG, tmp_path / "level1", write=True, configuration=7,
        start_date=date(2023, 10, 1), skip_utc_offsets=("UTC+00:00",),
    )
    importer.process_zip(source)
    frame = pl.read_parquet(tmp_path / "level1" / "2023" / "10" / "tahmo.parquet")
    assert frame.height == 1
    assert frame["dtm"][0] == datetime(2023, 10, 20, 10, 30, tzinfo=timezone.utc)
    assert frame["air_temperature"].to_list() == [24.1]
    assert importer.stats["skipped_before_start"] == 1
    assert importer.stats["skipped_utc_offset"] == 5
    assert importer.stats["input_rows"] == 1


def test_filters_keep_dry_run_read_only(tmp_path: Path) -> None:
    """Filtering and counting must work in a dry-run without creating Parquet."""
    source = tmp_path / "historical.zip"
    calibrated, raw = _historical_pair([
        ("2023/07/24 14:10:00", "UTC+03:00", 13.0),
        ("2023/10/20 10:05:00", "UTC+00:00", 14.0),
        ("2023/10/20 13:30:00", "UTC+03:00", 24.1),
    ])
    with ZipFile(source, "w", ZIP_DEFLATED) as archive:
        archive.writestr("GAW Station(z6-02149)-Configuration 7-123.csv", calibrated)
        archive.writestr("GAW Station(z6-02149)-Raw-Configuration 7-123.csv", raw)
    target = tmp_path / "level1"
    importer = BatchBackfill(
        CONFIG, target, write=False, configuration=7,
        start_date=date(2023, 10, 1), skip_utc_offsets=("UTC+00:00",),
    )
    importer.process_zip(source)
    assert importer.stats["input_rows"] == 1
    assert importer.stats["skipped_before_start"] == 1
    assert importer.stats["skipped_utc_offset"] == 1
    assert not target.exists()


def test_skipped_zero_offset_does_not_conflict_with_explicit_fallback(tmp_path: Path) -> None:
    """Explicit UTC+03:00 must not reject UTC+00:00 rows expressly skipped."""
    source = tmp_path / "historical.zip"
    calibrated, raw = _historical_pair([
        ("2023/10/20 10:05:00", "UTC+00:00", 14.0),
        ("2023/10/20 13:30:00", "UTC+03:00", 24.1),
    ])
    with ZipFile(source, "w", ZIP_DEFLATED) as archive:
        archive.writestr("GAW Station(z6-02149)-Configuration 7-123.csv", calibrated)
        archive.writestr("GAW Station(z6-02149)-Raw-Configuration 7-123.csv", raw)
    importer = BatchBackfill(
        CONFIG, tmp_path / "level1", write=False, configuration=7,
        start_date=date(2023, 10, 1), skip_utc_offsets=("UTC+00:00",),
        utc_offset="UTC+03:00",
    )
    importer.process_zip(source)
    assert importer.stats["skipped_utc_offset"] == 1
    assert importer.stats["input_rows"] == 1
