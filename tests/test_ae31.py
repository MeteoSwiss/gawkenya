from pathlib import Path

import polars as pl
import pytest

from processing.ae31 import AE31

TEST_DATA_DIR = Path("tests/data/ae31")

@pytest.mark.parametrize("filename", [
    "ae31-2025022006.zip",
    "AE31_20240804.csv",
    "AE31_20240828.csv",
    "AE31_2024090818.csv",
    "AE31_2024091119.csv",
    "AE31_2024091309.csv",
    "AE31_2024091506.csv"
])
def test_extract_to_dataframe_valid(filename):
    ae31 = AE31()
    test_file = TEST_DATA_DIR / filename

    df, err, file_type = ae31.extract_to_dataframe(test_file)

    assert err is None, f"Unexpected error for {filename}: {err}"
    assert isinstance(df, pl.DataFrame)
    assert not df.is_empty(), f"DataFrame should not be empty for {filename}"
    assert "dtm" in df.columns, f"Missing 'dtm' column in {filename}"
    assert file_type == "ae31"

# def test_extract_to_dataframe_invalid():
#     ae31 = AE31()
#     bad_file = TEST_DATA_DIR / "invalid.dat"

#     df, err, file_type = ae31.extract_to_dataframe(bad_file)

#     assert isinstance(err, str)
#     assert df.is_empty(), "DataFrame should be empty if extraction fails"
#     assert file_type == "ae31"

# import os
# import unittest

# import polars as pl

# from processing.ae31 import AE31
# from toolbox.utils import load_config

# config = load_config('mch-nrb.yml')['nrb-aq']

# class TestAE31(unittest.TestCase):
#     def setUp(self):
#         self.source = "tests/data/ae31"
#         self.target = "tests/data/ae31-test"

#     def test_extract_to_dataframe(self): 
#         ae31 = AE31(config=config)
#         file_path="tests/data/ae31/ae31-2025022008.zip"
#         df = ae31.extract_to_dataframe(file_path=file_path)
#         self.assertEqual(df.shape, (12, 62))

#     def test_read_csv_no_header(self):
#         ae31 = AE31(config=config)
#         file_path="tests/data/ae31/AE31_2024091119.csv"
#         df = ae31.read_csv_no_header(file_path=file_path)
#         self.assertEqual(df.shape, (12, 55))
#         file_path="tests/data/ae31/AE31_20240829.csv"
#         df = ae31.read_csv_no_header(file_path=file_path)
#         self.assertEqual(df.shape, (276, 55))

#     def test_compile_data(self):
#         ae31 = AE31(config=config)
#         file_name=f"{ae31.name}.parquet"
#         df = ae31.compile_data(source=self.source, target=self.target, file_name=file_name, move_processed_files=False)
#         self.assertEqual(df.shape, (35, 62))

#         # clean up
#         try:
#             os.remove(os.path.join(self.target, file_name))
#         except:
#             os.remove(os.path.join(self.target, "2025", "02", file_name))
#             os.removedirs(os.path.join(self.target, "2025", "02"))


# if __name__ == '__main__':
#     unittest.main()