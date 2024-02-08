import os
import polars as pl
import unittest
from processing.ae33 import AE33

class AE33_TestCases(unittest.TestCase):
    def test_extract_zipfile_to_dataframe(self): 
        ae33 = AE33()
        path="tests/data/ae33/ae33-202310190000.zip"
        if os.path.exists(path):
            obj = ae33.extract_zipfile_to_dataframe(path=path)
        self.assertEqual(obj[0].shape, (10, 74))
        self.assertEqual(obj[1], None)


    def test_zipfiles_to_parquet(self):
        ae33 = AE33()
        source = "tests/data/ae33"
        target = "tests/data/_level1"
        df, errors = ae33.zipfiles_to_parquet(source=source, target=target, plot=False)

        self.assertEqual(df.shape, (307, 74))
        self.assertEqual(errors, {})


if __name__ == '__main__':
    unittest.main()