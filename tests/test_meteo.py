import pytest
import polars as pl
from pathlib import Path
from processing.meteo import METEO

TEST_DATA_DIR = Path("tests/data/meteo")

FILES = [
    ("VRXA00.202310190700", True),
    ("VRXA00.202310190530", True),
    ("VRXA00.202310190550.zip", True),
    ("VRXA00.202310190630", True),
]

@pytest.mark.parametrize("filename, is_valid", FILES)
def test_meteo_files(filename: str, is_valid: bool):
    path = TEST_DATA_DIR / filename
    meteo = METEO()
    df, err, ftype = meteo.extract_to_dataframe(path)

    if is_valid:
        assert err is None, f"Unexpected error for {filename}: {err}"
        assert isinstance(df, pl.DataFrame), f"No DataFrame returned for {filename}"
        assert not df.is_empty(), f"DataFrame is empty for {filename}"
    else:
        assert df.is_empty(), f"Expected empty DataFrame for invalid file {filename}"
        assert err is not None, f"Expected error message for {filename}"


# # %%
# import unittest
# import os
# import shutil
# import glob

# from processing.meteo import Meteo

# class TestMeteo(unittest.TestCase):

#     def setUp(self):
#         self.path = 'tests/data/meteo'
#         self.archive = 'tests/data/archive'
#         self.file = 'tests/data/meteo/VRXA00.202310190600'
#         self.target = 'tests/data/'

#     def test_extract_vrxa00_to_dataframe(self):
#         meteo = Meteo()

#         df = meteo.extract_vrxa00_to_dataframe(file=self.file)[0]
#         print(df)
#         self.assertEqual(len(df), 1)

#     def test_compile_vrxa00_to_parquet(self):
#         meteo = Meteo()
#         target = os.path.join(self.target, 'vrxa00.parquet')

#         # prepare test
#         os.makedirs(self.path, exist_ok=True)
#         if os.path.exists(self.archive):
#             files = os.listdir(self.archive)
#             for file in files:
#                 shutil.move(src=os.path.join(self.archive, file), dst=os.path.join(self.path, file))
#             os.rmdir(self.archive)
#         if os.path.exists(target):
#             os.remove(target)

#         # test
#         files = os.listdir(self.path)
#         df, err = meteo.compile_vrxa00_to_parquet(source=self.path, target=self.target, archive=self.archive,)
#         print(len(df), len(files))
#         # self.assertEqual(len(df), len(files))

#         # clean up after test
#         # files = glob.glob(os.path.join(self.path, "meteo-*.json"))
#         # for file in files:
#         #     os.remove(file)
#         if os.path.exists(target):
#             os.remove(target)
#         os.makedirs(self.path, exist_ok=True)
#         if os.path.exists(self.archive):
#             files = os.listdir(self.archive)
#             for file in files:
#                 shutil.move(src=os.path.join(self.archive, file), dst=os.path.join(self.path, file))
#             os.rmdir(self.archive)


#     # def test_mappings2json(self):
#     #     meteo = Meteo()
        
#     #     # prepare test
#     #     fh = os.path.join(self.path, "mappings.json")
#     #     if os.path.exists(fh):
#     #         os.remove(fh)
#     #     fh = meteo.mappings2json(path=self.path)
#     #     self.assertEqual(os.path.exists(fh), True)

# if __name__ == '__main__':
#     unittest.main()