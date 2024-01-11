# %%
import unittest
import os
import shutil
import glob

import meteo.meteo as meteo

class TestMeteo(unittest.TestCase):

    def setUp(self):
        self.path = os.path.expanduser("~/Documents/git/gawkenya/tests/data/meteo")
        self.file = os.path.expanduser("~/Documents/git/gawkenya/tests/data/meteo/VRXA00.202302172000")

    def test_extract_bulletin(self):
        Meteo = meteo.Meteo()

        df = Meteo.extract_bulletin(file=self.file, pattern="VRXA00")
        print(df)
        self.assertEqual(len(df), 1)

    def test_extract_bulletins(self):
        Meteo = meteo.Meteo()

        # prepare test
        archive = os.path.join(self.path, "archive")
        if os.path.exists(archive):
            files = os.listdir(archive)
            for file in files:
                shutil.move(src=os.path.join(archive, file), dst=os.path.join(self.path, file))

        df = Meteo.extract_bulletins(path=self.path, archive="archive", save='json')
        print(df)
        self.assertEqual(len(df), 11)

        # clean up after test
        files = glob.glob(os.path.join(self.path, "meteo-*.json"))
        for file in files:
            os.remove(file)
        
        archive = os.path.join(self.path, "archive")
        if os.path.exists(archive):
            files = os.listdir(archive)
            for file in files:
                shutil.move(src=os.path.join(archive, file), dst=os.path.join(self.path, file))
        os.removedirs(archive)


    def test_mappings2json(self):
        Meteo = meteo.Meteo()
        
        # prepare test
        fh = os.path.join(self.path, "mappings.json")
        if os.path.exists(fh):
            os.remove(fh)
        fh = Meteo.mappings2json(path=self.path)
        self.assertEqual(os.path.exists(fh), True)

if __name__ == '__main__':
    unittest.main()