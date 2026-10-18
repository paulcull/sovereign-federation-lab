"""Configuration boundaries only; real database evidence is in MDM acceptance."""
import importlib.util
import os
from pathlib import Path
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('deployment',Path(__file__).resolve().parents[2]/'poc/deployment.py')
deployment=importlib.util.module_from_spec(spec);spec.loader.exec_module(deployment)


class FootprintTests(unittest.TestCase):
    def test_default_keeps_full_four_store_acceptance(self):
        with patch.dict(os.environ,{},clear=True):
            self.assertEqual(deployment.active_regions(),('SG','UK','US','IN'))
            self.assertTrue(deployment.description()['full_lab'])
            self.assertEqual(deployment.description()['suspended_regions'],[])

    def test_compact_is_exactly_two_stores_with_explicit_suspensions(self):
        with patch.dict(os.environ,{'LAB_FOOTPRINT':'mdm-compact'}):
            self.assertEqual(deployment.enabled_store_ids(),{'STORE-SG-01','STORE-GB-01'})
            self.assertFalse(deployment.description()['full_lab'])
            self.assertEqual(deployment.description()['suspended_regions'],['US','IN'])
            self.assertEqual(deployment.description()['telemetry'],'suspended')

    def test_unknown_footprint_cannot_implicitly_start_a_partial_lab(self):
        with patch.dict(os.environ,{'LAB_FOOTPRINT':'production'}):
            with self.assertRaises(RuntimeError):
                deployment.description()


if __name__=='__main__':unittest.main()
