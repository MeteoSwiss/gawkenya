import unittest
import os
import polars as pl
from toolbox.utils import load_config
from processing.ne300 import NE300

config = load_config('mch-mkn.yml')


class TestNE300(unittest.TestCase):

    def setUp(self):
        self.path = 'tests/data/ne300'
        # self.file_mkndaq = os.path.join(self.path, 'ne300-202407161200.dat')
        self.file_mkndaq = os.path.join(self.path, 'ne300-202411250040.zip')
        self.file_mkndaq_2 = os.path.join(self.path, 'ne300-202502240900.zip')
        self.file_aurora = os.path.join(self.path, '00230690 2024_07_16 21_18_01 1 min.txt')
        self.file_empty = os.path.join(self.path, 'ne300-202411140400.zip')

    def test_extract_to_dataframe(self):
        ne300 = NE300(config=config)

        df = ne300.extract_to_dataframe(file_path=self.file_mkndaq)
        self.assertEqual(df.shape, (10, 40))

        df = ne300.extract_to_dataframe(file_path=self.file_mkndaq_2)
        self.assertEqual(df.shape, (10, 40))

        df = ne300.extract_to_dataframe(file_path=self.file_aurora)
        self.assertEqual(df.shape, (162, 49))

        df = ne300.extract_to_dataframe(file_path=self.file_empty)
        self.assertEqual(isinstance(df, pl.DataFrame), True)
        self.assertEqual(df.is_empty(), True)

    def test_files_dataframes_to_parquet(self):
        ne300 = NE300(config=config)

        ne300.compile_files_to_parquet(source='tests/data/ne300',
                                       archive='tests/data/ne300/archive',
                                       issues='tests/data/ne300/issues',
                                       target='tests/data/ne300/target',
                                       move_processed_files=True,)
       
if __name__ == '__main__':
    unittest.main()
