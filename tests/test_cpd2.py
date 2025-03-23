import os
import shutil
import unittest

import polars as pl

from processing.cpd2 import CPD2
from toolbox.utils import load_config

config = load_config('mch-mkn.yml')

class TestCPD2(unittest.TestCase):
    def setUp(self):
        self.source = "tests/data/aerosol"
        self.target = "tests/data/aerosol-test"

    def test_extract_tarball_to_dataframe(self): 
        cpd2 = CPD2()
        file_path="tests/data/aerosol/mkn_20190514T090031Z.tar.gz"  # no valid A11 data, valid S11a data
        data, errors = cpd2.extract_tarball_to_dataframe(path=file_path)
        self.assertEqual(data['S11a'].shape, (60, 17))
        self.assertEqual(data['A11a'].shape, (0,0))

    def test_tarballs_to_parquet(self): 
        cpd2 = CPD2()
        errors = cpd2.tarballs_to_parquet(source=self.source, target=self.target)
        self.assertEqual(errors['S11_20231019T051341Z'], '78 column names provided for a DataFrame of width 16')
        self.assertEqual(errors['A11_20231019T000140Z'], 'empty CSV')

        # clean up
        if os.path.exists(self.target):
            shutil.rmtree(self.target)  # Deletes the folder and its contents

if __name__ == '__main__':
    unittest.main()