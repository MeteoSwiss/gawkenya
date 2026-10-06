from pathlib import Path

import polars as pl
import pytest

from processing.ae31 import AE31

TEST_DATA_DIR = Path("tests/data/ae31")


@pytest.mark.parametrize(
    "filename",
    [
        "ae31-2025022006.zip",
        "AE31_20240804.csv",
        "AE31_20240828.csv",
        "AE31_2024090818.csv",
        "AE31_2024091119.csv",
        "AE31_2024091309.csv",
        "AE31_2024091506.csv",
    ],
)
def test_extract_to_dataframe_valid(filename: str) -> None:
    ae31 = AE31()
    df, err = ae31.extract_to_dataframe(TEST_DATA_DIR / filename)

    assert err is None, f"Unexpected error for {filename}: {err}"
    assert isinstance(df, pl.DataFrame)
    assert not df.is_empty(), f"DataFrame should not be empty for {filename}"
    assert "dtm" in df.columns, f"Missing 'dtm' column in {filename}"
