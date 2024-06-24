import unittest
import os
import glob
import shutil

from processing.thermo import Thermo

class TestThermo(unittest.TestCase):

    def setUp(self):
        self.path = 'tests/data/thermo/tei49i'
        self.file = 'tests/data/tei49c/tei49c-202310200130.zip'


    def test_extract_file(self):
        thermo = Thermo()

        df = thermo.extract_thermo_to_dataframe(file=self.file)[0]
        self.assertEqual(len(df), 10)


    # def test_extract_files(self):
    #     thermo = Thermo()

    #     # prepare test
    #     archive = os.path.join(self.path, "archive")
    #     if os.path.exists(archive):
    #         files = os.listdir(archive)
    #         for file in files:
    #             shutil.move(src=os.path.join(archive, file), dst=os.path.join(self.path, file))

    #     df = thermo.extract_thermo_to_dataframe(file=self.path, archive="archive", save='json')
    #     self.assertEqual(len(df), 50)

    #     # clean up after test
    #     files = glob.glob(os.path.join(self.path, "tei49i-*.json"))
    #     for file in files:
    #         os.remove(file)
        
    #     archive = os.path.join(self.path, "archive")
    #     if os.path.exists(archive):
    #         files = os.listdir(archive)
    #         for file in files:
    #             shutil.move(src=os.path.join(archive, file), dst=os.path.join(self.path, file))
    #     os.removedirs(archive)


if __name__ == '__main__':
    unittest.main()
