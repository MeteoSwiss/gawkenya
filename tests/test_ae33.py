import shutil
import tempfile
import zipfile
from pathlib import Path

import polars as pl
import pytest

from processing.ae33 import AE33


@pytest.fixture
def temp_test_dir():
    """Temporary environment for AE33 tests."""
    tmpdir = Path(tempfile.mkdtemp())
    source = tmpdir / "incoming" / "ae33"
    archive = tmpdir / "archive" / "ae33"
    issues = tmpdir / "issues" / "ae33"
    target = tmpdir / "level1" / "ae33"
    source.mkdir(parents=True)
    yield {
        "source": source,
        "target": target,
        "archive": archive,
        "issues": issues,
        "tmpdir": tmpdir,
    }
    shutil.rmtree(tmpdir)


@pytest.mark.parametrize(
    "filename,should_succeed",
    [
        ("ae33-202310190530.dat", True),
        ("ae33-202310190600.zip", True),
    ]
)
def test_ae33_file_types(temp_test_dir, filename, should_succeed):
    test_data_path = Path("tests/data/ae33") / filename
    if not test_data_path.exists():
        pytest.skip(f"Missing test file: {filename}")

    # Copy the test file into the temp source
    shutil.copy(test_data_path, temp_test_dir["source"] / filename)

    ae33 = AE33()
    df, errors = ae33.compile_to_parquet(
        source=temp_test_dir["source"],
        target=temp_test_dir["target"],
        archive=temp_test_dir["archive"],
        issues=temp_test_dir["issues"],
        append_parquet=True,
        split='month',
    )

    parquet_files = list(temp_test_dir["target"].rglob("ae33.parquet"))

    if should_succeed:
        assert len(parquet_files) > 0, f"Expected Parquet file for {filename}"
        df_all = pl.read_parquet(parquet_files[0])
        assert not df_all.is_empty(), "Extracted DataFrame is empty"
        assert errors == {}, f"No errors expected, got: {errors}"
    else:
        assert errors != {}, f"Expected errors for {filename}"
        issue_files = list(temp_test_dir["issues"].rglob("*"))
        assert any(f.name == filename for f in issue_files), "Expected file in issues folder"


def test_ae33_log_file_is_left_untouched(temp_test_dir):
    source = temp_test_dir["source"]
    archive = temp_test_dir["archive"]
    issues = temp_test_dir["issues"]

    log_file = source / "ae33-log-2026073006.zip"

    with zipfile.ZipFile(log_file, "w") as zf:
        zf.writestr(
            "ae33-log-2026073006.csv",
            "timestamp,message\n2026-07-30T06:00:00,example log entry\n",
        )

    ae33 = AE33()
    df, errors = ae33.compile_to_parquet(
        source=source,
        target=temp_test_dir["target"],
        archive=archive,
        issues=issues,
        append_parquet=True,
        split="month",
    )

    assert df.is_empty()
    assert errors == {}

    # The log file must remain exactly where it arrived.
    assert log_file.exists()

    # It must neither be archived nor classified as an issue.
    assert not list(archive.rglob(log_file.name))
    assert not list(issues.rglob(log_file.name))