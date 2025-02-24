import unittest
import os
import polars as pl
from toolbox.utils import load_config
from housekeeping.organize_files import get_file_counts, plot_file_counts

cfg = load_config('mch-mkn.yml')


class TestOrganizeFiles(unittest.TestCase):

    def setUp(self):
        self.base_path = cfg['root']


    def test_plot_available_files(self):
        df = get_file_counts(base_path=self.base_path, base_name='ne300', base_folders=cfg['branches'])

        plot_file_counts(df=df)
       
if __name__ == '__main__':
    unittest.main()
