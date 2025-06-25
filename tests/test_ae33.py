import shutil
import tempfile
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

# import os
# import polars as pl
# import unittest
# from processing.ae33 import AE33

# class TestAE33(unittest.TestCase):
#     def setUp(self):
#         self.source = "tests/data/ae33"
#         self.target = "tests/data"

#     def test_extract_zipfile_to_dataframe(self): 
#         ae33 = AE33()
#         path="tests/data/ae33/ae33-202310190000.zip"
#         if os.path.exists(path):
#             obj = ae33.extract_zipfile_to_dataframe(path=path)
#         self.assertEqual(obj[0].shape, (10, 74))
#         self.assertEqual(obj[1], None)


#     def test_zipfiles_to_parquet(self):
#         ae33 = AE33()
#         target = os.path.join(self.target, 'ae33.parquet')
#         if os.path.exists(target):
#             os.remove(target)

#         df, errors = ae33.zipfiles_to_parquet(source=self.source, target=self.target, plot=False)

#         self.assertEqual(df.shape, (307, 74))
#         self.assertEqual(errors, {})

#         # clean up
#         if os.path.exists(target):
#             os.remove(target)

# if __name__ == '__main__':
#     unittest.main()