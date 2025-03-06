import os
import unittest

import polars as pl

from processing.ae31 import AE31
from toolbox.utils import load_config

config = load_config('mch-nrb.yml')['nrb-aq']

class TestAE31(unittest.TestCase):
    def setUp(self):
        self.source = "tests/data/ae31"
        self.target = "tests/data/ae31-test"

    def test_extract_to_dataframe(self): 
        ae31 = AE31(config=config)
        file_path="tests/data/ae31/ae31-2025022008.zip"
        df = ae31.extract_to_dataframe(file_path=file_path)
        self.assertEqual(df.shape, (12, 62))

    def test_read_csv_no_header(self):
        ae31 = AE31(config=config)
        file_path="tests/data/ae31/AE31_2024091119.csv"
        df = ae31.read_csv_no_header(file_path=file_path)
        self.assertEqual(df.shape, (12, 55))
        file_path="tests/data/ae31/AE31_20240829.csv"
        df = ae31.read_csv_no_header(file_path=file_path)
        self.assertEqual(df.shape, (276, 55))

    def test_compile_data(self):
        ae31 = AE31(config=config)
        file_name=f"{ae31.name}.parquet"
        df = ae31.compile_data(source=self.source, target=self.target, file_name=file_name, move_processed_files=False)
        self.assertEqual(df.shape, (35, 62))

        # clean up
        try:
            os.remove(os.path.join(self.target, file_name))
        except:
            os.remove(os.path.join(self.target, "2025", "02", file_name))
            os.removedirs(os.path.join(self.target, "2025", "02"))


if __name__ == '__main__':
    unittest.main()