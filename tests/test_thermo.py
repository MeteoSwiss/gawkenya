from pathlib import Path

import polars as pl
import pytest

from processing.thermo import Thermo

TEST_DATA_DIR = Path("tests/data/thermo")


@pytest.mark.parametrize(
    "filename",
    [
        "tei49c-202310200140.dat",
        "tei49c-202310200130.zip",
        "tei49i-202310220440.dat",
        "tei49i-202211010310.zip",
        "tei49c-202410080810.zip",
    ],
)
def test_extract_to_dataframe_valid(filename: str) -> None:
    thermo = Thermo()
    df, err = thermo.extract_to_dataframe(TEST_DATA_DIR / filename)

    assert err is None, f"Unexpected error for {filename}: {err}"
    assert isinstance(df, pl.DataFrame)
    assert not df.is_empty(), f"DataFrame should not be empty for {filename}"
    assert "dtm" in df.columns, f"Missing 'dtm' column in {filename}"


def test_headers_defined() -> None:
    thermo = Thermo()
    assert "tei49c" in thermo.headers
    assert "tei49i" in thermo.headers
    assert len(thermo.headers["tei49c"]) > 0
    assert len(thermo.headers["tei49i"]) > 0
