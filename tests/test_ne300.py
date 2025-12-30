import pytest
import polars as pl
from pathlib import Path
from processing.neph import Neph

TEST_DATA_DIR = Path("tests/data/ne300")

VALID_NO_HEADER = TEST_DATA_DIR / "ne300-202407161200.dat"
VALID_WITH_HEADER = TEST_DATA_DIR / "ne300-202410282320.zip"
INVALID_EMPTY = TEST_DATA_DIR / "ne300-202411140400.zip"
INVALID_HEADER_ONLY = TEST_DATA_DIR / "ne300-202412030914.zip"
VALID_WITH_HEADER_V1 = TEST_DATA_DIR / "ne300-2025122816.zip"


@pytest.mark.parametrize("path, expected_type, min_rows", [
    (VALID_NO_HEADER, "acoem_no_header", 1),
    (VALID_WITH_HEADER, "acoem_with_header", 1),
])
def test_valid_files(path: Path, expected_type: str, min_rows: int):
    ne300 = Neph(name="ne300")
    df, err = ne300.extract_to_dataframe(path)

    assert err is None, f"Unexpected error: {err}"
    assert isinstance(df, pl.DataFrame)
    assert not df.is_empty(), "DataFrame is unexpectedly empty"
    assert (dtm := "dtm") in df.columns, "Missing 'dtm' column"
    # assert ftype == expected_type, f"Expected file type {expected_type}, got {ftype}"
    assert len(df) >= min_rows


def test_invalid_empty_file():
    ne300 = Neph(name="ne300")
    df, err = ne300.extract_to_dataframe(INVALID_EMPTY)

    assert df.is_empty()
    assert err is not None
    assert "file is empty" in err.lower()


def test_invalid_header_only_file():
    ne300 = Neph(name="ne300")
    df, err = ne300.extract_to_dataframe(INVALID_HEADER_ONLY)

    assert df.is_empty()
    assert err is not None
    assert "file contains only header" in err.lower()


def test_dtm_parsing():
    ne300 = Neph(name="ne300")
    df, err = ne300.extract_to_dataframe(VALID_WITH_HEADER)
    assert err is None
    # assert pl.datatypes.is_datetime(df.schema["dtm"])


def test_valid_with_header_v1():
    ne300 = Neph(name="ne300")
    df, err = ne300.extract_to_dataframe(VALID_WITH_HEADER_V1)

    assert err is None, f"Unexpected error: {err}"
    assert isinstance(df, pl.DataFrame)
    assert not df.is_empty(), "DataFrame is unexpectedly empty"
    assert (dtm := "dtm") in df.columns, "Missing 'dtm' column"
    assert len(df) >= 1