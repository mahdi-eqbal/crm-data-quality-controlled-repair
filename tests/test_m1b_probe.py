"""Offline M1b tests; no network access or account credentials required."""
import types
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
# During isolated patch tests, the existing M1a module is not part of the patch.
# Supply only the import-time names; the real project loads the actual M1a code.
if not (SCRIPTS / "m1_snapshot_hubspot.py").exists():
    m1_mock = types.ModuleType("m1_snapshot_hubspot")
    m1_mock.collect = lambda kind, token: []
    m1_mock.local_env = lambda: {}
    sys.modules["m1_snapshot_hubspot"] = m1_mock
from m1b_probe_associations import verify_account, get_association_count

class TestProbe(unittest.TestCase):
    def test_valid_account(self):
        with patch("m1b_probe_associations.get_json", return_value={"portalId": 149703596}):
            self.assertEqual(verify_account("fake-token"), "VERIFIED")

    def test_wrong_account_is_blocked(self):
        with patch("m1b_probe_associations.get_json", return_value={"portalId": 111}):
            with self.assertRaises(ValueError):
                verify_account("fake-token")

    def test_forbidden_account_info_is_not_claimed_verified(self):
        error = HTTPError("https://api.hubapi.com", 403, "Forbidden", {}, None)
        with patch("m1b_probe_associations.get_json", side_effect=error):
            self.assertEqual(verify_account("fake-token"), "UNVERIFIED")

    def test_paginated_associations_deduplicate_company_ids(self):
        responses = [
            {"results": [{"toObjectId": 10}, {"toObjectId": 20}], "paging": {"next": {"after": "next"}}},
            {"results": [{"toObjectId": 20}, {"toObjectId": 30}]},
        ]
        with patch("m1b_probe_associations.get_json", side_effect=responses), patch("m1b_probe_associations.time.sleep"):
            self.assertEqual(get_association_count("contact-01", "fake-token"), 3)

    def test_empty_associations(self):
        with patch("m1b_probe_associations.get_json", return_value={"results": []}):
            self.assertEqual(get_association_count("contact-01", "fake-token"), 0)

    def test_malformed_associations_fail(self):
        with patch("m1b_probe_associations.get_json", return_value={"results": [{"wrongKey": 3}]}):
            with self.assertRaises(ValueError):
                get_association_count("contact-01", "fake-token")

if __name__ == "__main__":
    unittest.main()
