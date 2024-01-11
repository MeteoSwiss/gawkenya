import unittest
import os
import glob
import shutil

import thermo.thermo as thermo

class TestThermo(unittest.TestCase):

    def setUp(self):
        self.path = os.path.expanduser("~/Documents/git/gawkenya/tests/data/thermo/tei49i")
        self.file = os.path.expanduser("~/Documents/git/gawkenya/tests/data/thermo/tei49c/tei49c-202301010000.zip")


    def test_extract_file(self):
        Thermo = thermo.Thermo()

        df = Thermo.extract_file(file=self.file)
        self.assertEqual(len(df), 10)


    def test_extract_files(self):
        Thermo = thermo.Thermo()

        # prepare test
        archive = os.path.join(self.path, "archive")
        if os.path.exists(archive):
            files = os.listdir(archive)
            for file in files:
                shutil.move(src=os.path.join(archive, file), dst=os.path.join(self.path, file))

        df = Thermo.extract_files(path=self.path, pattern=["tei49i"], archive="archive", save='json')
        self.assertEqual(len(df), 50)

        # clean up after test
        files = glob.glob(os.path.join(self.path, "tei49i-*.json"))
        for file in files:
            os.remove(file)
        
        archive = os.path.join(self.path, "archive")
        if os.path.exists(archive):
            files = os.listdir(archive)
            for file in files:
                shutil.move(src=os.path.join(archive, file), dst=os.path.join(self.path, file))
        os.removedirs(archive)


if __name__ == '__main__':
    unittest.main()
