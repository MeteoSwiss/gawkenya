from __future__ import annotations

import csv
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import polars as pl

from processing.ae33 import AE33


FIXTURE = Path(__file__).parent / "data" / "ae33-2026092305.zip"
ABSORPTION_COLUMNS = [f"b{channel}_abs" for channel in range(1, 8)]


def _fixture_header_and_first_row() -> tuple[list[str], list[str]]:
    with zipfile.ZipFile(FIXTURE) as zf:
        [member] = zf.namelist()
        lines = zf.read(member).decode("utf-8").splitlines()
    header = next(csv.reader([lines[0]]))
    row = next(csv.reader([lines[1]]))
    return header, row


def _expected_level1_columns(processor: AE33) -> list[str]:
    """Return the raw canonical AE33 schema plus intrinsic Level-1 products."""
    return processor._canonical_columns() + ABSORPTION_COLUMNS


def test_new_pydaq_zip_is_parsed_to_canonical_schema() -> None:
    processor = AE33()

    df, error = processor.extract_to_dataframe(FIXTURE)

    assert error is None
    assert df.shape == (60, 81)
    assert df.columns == _expected_level1_columns(processor)
    assert df.schema[processor.dtm] == pl.Datetime("us", "UTC")
    assert df.get_column(processor.dtm)[0] == datetime(2026, 9, 23, 5, 0, tzinfo=UTC)
    assert df.get_column(processor.dtm)[-1] == datetime(2026, 9, 23, 5, 59, tzinfo=UTC)

    first = df.row(0, named=True)
    assert first["Inst_SN"] == "AE33-S10-01394"
    assert first["BB"] == 0.0
    assert first["Pressure"] == 101325.0
    assert first["Temperature"] == 0.0
    assert first["ContTemp"] == 24.0
    assert first["SupplyTemp"] == 40.0
    assert first["LedTemp"] == 26.0
    assert first["ContStatus"] == 0
    assert first["LedStatus"] == 10
    assert first["DetectStatus"] == 10
    assert first["ValveStatus"] == 0
    assert first["Status"] == 0
    assert first["TapeAdvCount"] == 517
    assert first["TapeAdvLeft"] == 139

    for channel in range(1, 8):
        assert f"b{channel}_abs" in df.columns


def test_legacy_headerless_data_and_timestamp_remain_supported(tmp_path: Path) -> None:
    processor = AE33()
    _, row = _fixture_header_and_first_row()
    row[3] = "09/23/2026 05:00:00 AM"
    path = tmp_path / "ae33-legacy.dat"
    with path.open("w", newline="", encoding="utf-8") as stream:
        csv.writer(stream).writerow(row)

    df, error = processor.extract_to_dataframe(path)

    assert error is None
    assert df.height == 1
    assert df.columns == _expected_level1_columns(processor)
    assert df.get_column(processor.dtm)[0] == datetime(2026, 9, 23, 5, 0, tzinfo=UTC)
    assert "unclear_2" not in df.columns
    assert "Pres" not in df.columns
    assert "Temp_1" not in df.columns
    assert "Stat_5" not in df.columns
    assert "unclear_3" not in df.columns


def test_headered_legacy_aliases_are_normalized(tmp_path: Path) -> None:
    processor = AE33()
    header, row = _fixture_header_and_first_row()
    reverse_aliases = {value: key for key, value in processor._LEGACY_COLUMN_ALIASES.items()}
    legacy_header = [reverse_aliases.get(name, name) for name in header]
    row[3] = "09/23/2026 05:00:00 AM"
    path = tmp_path / "ae33-legacy.csv"
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(legacy_header)
        writer.writerow(row)

    df, error = processor.extract_to_dataframe(path)

    assert error is None
    assert df.height == 1
    assert df.columns == _expected_level1_columns(processor)
    assert df.get_column("Pressure")[0] == 101325.0
    assert df.get_column("TapeAdvLeft")[0] == 139


def test_invalid_dtm_is_an_extraction_error_not_silent_success(tmp_path: Path) -> None:
    processor = AE33()
    header, row = _fixture_header_and_first_row()
    row[3] = "not-a-timestamp"
    path = tmp_path / "ae33-invalid.csv"
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(header)
        writer.writerow(row)

    df, error = processor.extract_to_dataframe(path)

    assert error is not None
    assert "datetime parsing failed" in error
    assert df.is_empty()


def test_canonicalize_dataframe_renames_existing_legacy_columns() -> None:
    processor = AE33()
    df = pl.DataFrame(
        {
            processor.dtm: [datetime(2026, 9, 23, 5, 0, tzinfo=UTC)],
            "unclear_2": [12.5],
            "Pres": [101325.0],
            "Temp": [20.0],
            "Temp_1": [24.0],
            "Temp_2": [40.0],
            "Temp_3": [26.0],
            "Stat_1": [0],
            "Stat_2": [10],
            "Stat_3": [10],
            "Stat_4": [0],
            "Stat_5": [0],
            "unclear_3": [139],
            "source": ["legacy.zip"],
        }
    )

    result = processor.canonicalize_dataframe(df)

    assert result.columns == [
        processor.dtm,
        "BB",
        "Pressure",
        "Temperature",
        "ContTemp",
        "SupplyTemp",
        "LedTemp",
        "ContStatus",
        "LedStatus",
        "DetectStatus",
        "ValveStatus",
        "Status",
        "TapeAdvLeft",
        "source",
    ]
    assert result.schema[processor.dtm] == pl.Datetime("us", "UTC")


def test_canonicalize_dataframe_rejects_conflicting_aliases() -> None:
    processor = AE33()
    df = pl.DataFrame(
        {
            processor.dtm: [datetime(2026, 9, 23, 5, 0, tzinfo=UTC)],
            "Pres": [101000.0],
            "Pressure": [101325.0],
        }
    )

    try:
        processor.canonicalize_dataframe(df)
    except ValueError as exc:
        assert "conflicting rows" in str(exc)
    else:
        raise AssertionError("Expected conflicting legacy/canonical columns to fail.")
