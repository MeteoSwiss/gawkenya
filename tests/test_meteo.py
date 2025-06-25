# # %%
# import unittest
# import os
# import shutil
# import glob

# from processing.meteo import Meteo

# class TestMeteo(unittest.TestCase):

#     def setUp(self):
#         self.path = 'tests/data/meteo'
#         self.archive = 'tests/data/archive'
#         self.file = 'tests/data/meteo/VRXA00.202310190600'
#         self.target = 'tests/data/'

#     def test_extract_vrxa00_to_dataframe(self):
#         meteo = Meteo()

#         df = meteo.extract_vrxa00_to_dataframe(file=self.file)[0]
#         print(df)
#         self.assertEqual(len(df), 1)

#     def test_compile_vrxa00_to_parquet(self):
#         meteo = Meteo()
#         target = os.path.join(self.target, 'vrxa00.parquet')

#         # prepare test
#         os.makedirs(self.path, exist_ok=True)
#         if os.path.exists(self.archive):
#             files = os.listdir(self.archive)
#             for file in files:
#                 shutil.move(src=os.path.join(self.archive, file), dst=os.path.join(self.path, file))
#             os.rmdir(self.archive)
#         if os.path.exists(target):
#             os.remove(target)

#         # test
#         files = os.listdir(self.path)
#         df, err = meteo.compile_vrxa00_to_parquet(source=self.path, target=self.target, archive=self.archive,)
#         print(len(df), len(files))
#         # self.assertEqual(len(df), len(files))

#         # clean up after test
#         # files = glob.glob(os.path.join(self.path, "meteo-*.json"))
#         # for file in files:
#         #     os.remove(file)
#         if os.path.exists(target):
#             os.remove(target)
#         os.makedirs(self.path, exist_ok=True)
#         if os.path.exists(self.archive):
#             files = os.listdir(self.archive)
#             for file in files:
#                 shutil.move(src=os.path.join(self.archive, file), dst=os.path.join(self.path, file))
#             os.rmdir(self.archive)


#     # def test_mappings2json(self):
#     #     meteo = Meteo()
        
#     #     # prepare test
#     #     fh = os.path.join(self.path, "mappings.json")
#     #     if os.path.exists(fh):
#     #         os.remove(fh)
#     #     fh = meteo.mappings2json(path=self.path)
#     #     self.assertEqual(os.path.exists(fh), True)

# if __name__ == '__main__':
#     unittest.main()