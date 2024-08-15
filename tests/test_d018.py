import os
import polars as pl
import unittest
from processing.dobson import DData

class TestDData(unittest.TestCase):
    def setUp(self):
        self.source = "tests/data/d018"
        self.target = "tests/data"
        self.config = {'root': '/product_data/data/pay/Kenya',
                  'logging': 'gawkenya.log',
                  }

    def test_extract_file_no_data(self): 
        ddata = DData(config=self.config)
        header, df_data = ddata.read_file(file='tests/data/d018/D2722009.018')
        header_expected = ('Dobson2', '29', '9', '2009', 'Nairobi', '018', '-1.271', '36.803', '1795')
        self.assertTupleEqual(header[0:9], header_expected)
        self.assertEqual(df_data.is_empty(), True)

    def test_extract_file_data_incomplete(self): 
        ddata = DData(config=self.config)
        header, df_data = ddata.read_file(file='tests/data/d018/D0122000.018')
        self.assertEqual(df_data.is_empty(), True)

    def test_extract_file_data_complete(self): 
        ddata = DData(config=self.config)
        header, df_data = ddata.read_file(file='tests/data/d018/DDataD0172022.018')
        header_expected = ('Dobson2', '17', '1', '2022', 'Nairobi', '018', '-1.271', '36.803', '1795')
        columns_expected = ['source', 'type', 'sequence', 'comments', 'dtm', 'sza', 'mu', 'XAD', 'XCD', 'X1', 'X2', 'X3', 'X4', 'X5', 'X6', 'X7']
        self.assertTupleEqual(header[0:9], header_expected)
        self.assertListEqual(df_data.columns, columns_expected)

    def test_process_directory(self):
        ddata = DData(config=self.config)
        num_files = len(os.listdir(self.source))
        columns_expected = ['source', 'type', 'sequence', 'comments', 'dtm', 'sza', 'mu', 'XAD', 'XCD', 'X1', 'X2', 'X3', 'X4', 'X5', 'X6', 'X7']
        header, df_data = ddata.process_directory(self.source)
        self.assertEqual(len(header), num_files)
        self.assertListEqual(df_data.columns, columns_expected)


if __name__ == '__main__':
    unittest.main()