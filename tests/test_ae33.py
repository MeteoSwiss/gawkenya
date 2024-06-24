import os
import polars as pl
import unittest
from processing.ae33 import AE33

class TestAE33(unittest.TestCase):
    def setUp(self):
        self.source = "tests/data/ae33"
        self.target = "tests/data"

    def test_extract_zipfile_to_dataframe(self): 
        ae33 = AE33()
        path="tests/data/ae33/ae33-202310190000.zip"
        if os.path.exists(path):
            obj = ae33.extract_zipfile_to_dataframe(path=path)
        self.assertEqual(obj[0].shape, (10, 74))
        self.assertEqual(obj[1], None)


    def test_zipfiles_to_parquet(self):
        ae33 = AE33()
        target = os.path.join(self.target, 'ae33.parquet')
        if os.path.exists(target):
            os.remove(target)

        df, errors = ae33.zipfiles_to_parquet(source=self.source, target=self.target, plot=False)

        self.assertEqual(df.shape, (307, 74))
        self.assertEqual(errors, {})

        # clean up
        if os.path.exists(target):
            os.remove(target)

if __name__ == '__main__':
    unittest.main()