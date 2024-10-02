import os
import unittest
from processing.ecc import ECC

class TestECCSONDE(unittest.TestCase):
    def test_extract_ecc_asap_file(self):
        ecc_asap = ECC()
        source = "tests/data/ecc_asap/20220504C37105.TXT"
        res = ecc_asap.extract_ecc_asap(source)

        self.assertEqual(res['date'], '2022-05-04')
        self.assertEqual(res['file'], source)
        self.assertEqual(len(res['metadata']), 8)
        self.assertEqual(res['data'].shape, (480, 7))


if __name__ == '__main__':
    unittest.main()