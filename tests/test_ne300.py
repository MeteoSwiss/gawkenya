import unittest
import os
import polars as pl
from toolbox.utils import load_config
from processing.ne300 import NE300

config = load_config('mch-mkn.yml')


class TestNE300(unittest.TestCase):

    def setUp(self):
        self.path = 'tests/data/ne300'
        self.file_aurora = os.path.join(self.path, '00230690 2024_07_16 21_18_01 1 min.txt')
        self.file_mkndaq = os.path.join(self.path, 'ne300-202407161200.dat')

    def test_extract_file(self):
        ne300 = NE300(config=config)

        df = ne300.extract_to_dataframe(file=self.file_aurora)
        self.assertEqual(isinstance(df, pl.DataFrame), True)
        self.assertEqual(df.is_empty(), False)

        df = ne300.extract_to_dataframe(file=self.file_mkndaq)
        self.assertEqual(isinstance(df, pl.DataFrame), True)
        self.assertEqual(df.is_empty(), False)

if __name__ == '__main__':
    unittest.main()
