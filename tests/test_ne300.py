from pathlib import Path

import polars as pl
import pytest

from processing.neph import Neph

TEST_DATA_DIR = Path("tests/data/ne300")

VALID_NO_HEADER = TEST_DATA_DIR / "ne300-202407161200.dat"
VALID_WITH_HEADER = TEST_DATA_DIR / "ne300-202410282320.zip"
INVALID_HEADER_ONLY = TEST_DATA_DIR / "ne300-202412030914.zip"
VALID_WITH_HEADER_V1 = TEST_DATA_DIR / "ne300-2025122816.zip"


@pytest.mark.parametrize(
    "path, min_rows",
    [
        (VALID_NO_HEADER, 1),
        (VALID_WITH_HEADER, 1),
    ],
)
def test_valid_files(path: Path, min_rows: int) -> None:
    ne300 = Neph(name="ne300")
    df, err = ne300.extract_to_dataframe(path)

    assert err is None, f"Unexpected error: {err}"
    assert isinstance(df, pl.DataFrame)
    assert not df.is_empty(), "DataFrame is unexpectedly empty"
    assert "dtm" in df.columns, "Missing 'dtm' column"
    assert len(df) >= min_rows


def test_invalid_empty_file(tmp_path: Path) -> None:
    # Keep this test self-contained: the old named fixture is not in the repo.
    empty_file = tmp_path / "empty.dat"
    empty_file.write_bytes(b"")

    ne300 = Neph(name="ne300")
    df, err = ne300.extract_to_dataframe(
        empty_file,
        delete_if_empty=False,
    )

    assert df.is_empty()
    assert err is not None
    assert "file is empty" in err.lower()


def test_invalid_header_only_file() -> None:
    ne300 = Neph(name="ne300")
    df, err = ne300.extract_to_dataframe(INVALID_HEADER_ONLY)

    assert df.is_empty()
    assert err is not None
    # Polars reports this header-only input as an empty CSV. What matters here
    # is that it is rejected cleanly rather than accepted as a valid dataset.
    assert "empty csv" in err.lower()


def test_dtm_parsing() -> None:
    ne300 = Neph(name="ne300")
    df, err = ne300.extract_to_dataframe(VALID_WITH_HEADER)

    assert err is None
    assert isinstance(df, pl.DataFrame)
    assert df.schema["dtm"] == pl.Datetime("us", "UTC")


def test_valid_with_header_v1() -> None:
    ne300 = Neph(name="ne300")
    df, err = ne300.extract_to_dataframe(VALID_WITH_HEADER_V1)

    assert err is None, f"Unexpected error: {err}"
    assert isinstance(df, pl.DataFrame)
    assert not df.is_empty(), "DataFrame is unexpectedly empty"
    assert "dtm" in df.columns, "Missing 'dtm' column"
    assert len(df) >= 1
