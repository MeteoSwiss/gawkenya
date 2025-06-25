import pytest
from processing.thermo import Thermo
from pathlib import Path
import polars as pl

TEST_DATA_DIR = Path("tests/data/thermo")

@pytest.mark.parametrize("filename", [
    "tei49c-202310200140.dat",
    "tei49c-202310200130.zip",
    "tei49i-202310220440.dat",
    "tei49i-202211010310.zip",
    "tei49c-202410080810.zip",
])
def test_extract_to_dataframe_valid(filename):
    thermo = Thermo()
    test_file = TEST_DATA_DIR / filename

    df, err, file_type = thermo.extract_to_dataframe(test_file)

    assert err is None, f"Unexpected error for {filename}: {err}"
    assert isinstance(df, pl.DataFrame)
    assert not df.is_empty(), f"DataFrame should not be empty for {filename}"
    assert "dtm" in df.columns, f"Missing 'dtm' column in {filename}"
    assert file_type in ("tei49c", "tei49i")

# def test_extract_to_dataframe_invalid():
#     thermo = Thermo()
#     bad_file = TEST_DATA_DIR / "tei49c-202410080810.zip"

#     df, err, file_type = thermo.extract_to_dataframe(bad_file)

#     assert isinstance(err, str)
#     assert df.is_empty(), "DataFrame should be empty if extraction fails"
#     assert file_type in ("tei49c", "tei49i")

def test_headers_defined():
    thermo = Thermo()
    assert "tei49c" in thermo.headers
    assert "tei49i" in thermo.headers
    assert len(thermo.headers["tei49c"]) > 0
    assert len(thermo.headers["tei49i"]) > 0

# import unittest
# from toolbox.utils import load_config

# from processing.thermo import Thermo

# class TestThermo(unittest.TestCase):

#     def setUp(self):
#         self.config = load_config("mch-mkn.yml")
#         self.path = 'tests/data/thermo/tei49i'
#         self.file = 'tests/data/tei49c/tei49c-202310200130.zip'
#         self.file = 'tests/data/tei49c/tei49c-202412170700.zip'


#     def test_extract_file(self):
#         thermo = Thermo(config=self.config)

#         df = thermo.extract_thermo_to_dataframe(file=self.file)[0]
#         self.assertEqual(len(df), 58)


#     # def test_extract_files(self):
#     #     thermo = Thermo()

#     #     # prepare test
#     #     archive = os.path.join(self.path, "archive")
#     #     if os.path.exists(archive):
#     #         files = os.listdir(archive)
#     #         for file in files:
#     #             shutil.move(src=os.path.join(archive, file), dst=os.path.join(self.path, file))

#     #     df = thermo.extract_thermo_to_dataframe(file=self.path, archive="archive", save='json')
#     #     self.assertEqual(len(df), 50)

#     #     # clean up after test
#     #     files = glob.glob(os.path.join(self.path, "tei49i-*.json"))
#     #     for file in files:
#     #         os.remove(file)
        
#     #     archive = os.path.join(self.path, "archive")
#     #     if os.path.exists(archive):
#     #         files = os.listdir(archive)
#     #         for file in files:
#     #             shutil.move(src=os.path.join(archive, file), dst=os.path.join(self.path, file))
#     #     os.removedirs(archive)


# if __name__ == '__main__':
#     unittest.main()
