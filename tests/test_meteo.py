from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from processing.meteo import Meteo


TEST_DATA_DIR = Path(__file__).parent / "data" / "meteo"

FILES = [
    "VRXA00.202310190700",
    "VRXA00.202310190530",
    "VRXA00.202310190550.zip",
    "VRXA00.202310190630",
]


@pytest.mark.parametrize("filename", FILES)
def test_meteo_files(filename: str) -> None:
    path = TEST_DATA_DIR / filename
    processor = Meteo()

    df, error = processor.extract_to_dataframe(path)

    assert error is None, f"Unexpected error for {filename}: {error}"
    assert isinstance(df, pl.DataFrame)
    assert not df.is_empty()
    assert "dtm" in df.columns
    assert df.schema["dtm"] == pl.Datetime("us", "UTC")
