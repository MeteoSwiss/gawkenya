import pytest
import polars as pl
from pathlib import Path
from processing.neph import NEPH

TEST_DATA_DIR = Path("tests/data/ne300")

VALID_NO_HEADER = TEST_DATA_DIR / "ne300-202407161200.dat"
VALID_WITH_HEADER = TEST_DATA_DIR / "ne300-202410282320.zip"
INVALID_EMPTY = TEST_DATA_DIR / "ne300-202411140400.zip"
INVALID_HEADER_ONLY = TEST_DATA_DIR / "ne300-202412030914.zip"


@pytest.mark.parametrize("path, expected_type, min_rows", [
    (VALID_NO_HEADER, "acoem_no_header", 1),
    (VALID_WITH_HEADER, "acoem_with_header", 1),
])
def test_valid_files(path: Path, expected_type: str, min_rows: int):
    ne300 = NEPH(name="ne300")
    df, err, ftype = ne300.extract_to_dataframe(path)

    assert err is None, f"Unexpected error: {err}"
    assert isinstance(df, pl.DataFrame)
    assert not df.is_empty(), "DataFrame is unexpectedly empty"
    assert (dtm := "dtm") in df.columns, "Missing 'dtm' column"
    assert ftype == expected_type, f"Expected file type {expected_type}, got {ftype}"
    assert len(df) >= min_rows


def test_invalid_empty_file():
    ne300 = NEPH(name="ne300")
    df, err, ftype = ne300.extract_to_dataframe(INVALID_EMPTY)

    assert df.is_empty()
    assert err is not None
    assert "file is empty" in err.lower()


def test_invalid_header_only_file():
    ne300 = NEPH(name="ne300")
    df, err, ftype = ne300.extract_to_dataframe(INVALID_HEADER_ONLY)

    assert df.is_empty()
    assert err is not None
    assert "file contains only header" in err.lower()


def test_dtm_parsing():
    ne300 = NEPH(name="ne300")
    df, err, ftype = ne300.extract_to_dataframe(VALID_WITH_HEADER)
    assert err is None
    # assert pl.datatypes.is_datetime(df.schema["dtm"])


def test_detect_format():
    ne300 = NEPH(name="ne300")
    df, err, ftype = ne300.extract_to_dataframe(VALID_WITH_HEADER)
    assert ftype in {"acoem_with_header", "acoem_no_header", "aurora"}


# import unittest
# import os
# import polars as pl
# from toolbox.utils import load_config
# from processing.ne300 import NE300

# config = load_config('mch-mkn.yml')


# class TestNE300(unittest.TestCase):

#     def setUp(self):
#         self.path = 'tests/data/ne300'
#         # self.file_mkndaq = os.path.join(self.path, 'ne300-202407161200.dat')
#         self.file_mkndaq = os.path.join(self.path, 'ne300-202411250040.zip')
#         self.file_mkndaq_2 = os.path.join(self.path, 'ne300-202502240900.zip')
#         self.file_aurora = os.path.join(self.path, '00230690 2024_07_16 21_18_01 1 min.txt')
#         self.file_empty = os.path.join(self.path, 'ne300-202411140400.zip')

#     def test_extract_to_dataframe(self):
#         ne300 = NE300(config=config)

#         df = ne300.extract_to_dataframe(file_path=self.file_mkndaq)
#         self.assertEqual(df.shape, (10, 40))

#         df = ne300.extract_to_dataframe(file_path=self.file_mkndaq_2)
#         self.assertEqual(df.shape, (10, 40))

#         df = ne300.extract_to_dataframe(file_path=self.file_aurora)
#         self.assertEqual(df.shape, (162, 49))

#         df = ne300.extract_to_dataframe(file_path=self.file_empty)
#         self.assertEqual(isinstance(df, pl.DataFrame), True)
#         self.assertEqual(df.is_empty(), True)

#     def test_files_dataframes_to_parquet(self):
#         ne300 = NE300(config=config)

#         ne300.compile_files_to_parquet(source='tests/data/ne300',
#                                        archive='tests/data/ne300/archive',
#                                        issues='tests/data/ne300/issues',
#                                        target='tests/data/ne300/target',
#                                        move_processed_files=True,)
       
# if __name__ == '__main__':
#     unittest.main()
