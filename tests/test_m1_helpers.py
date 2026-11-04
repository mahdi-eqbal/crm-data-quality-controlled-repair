"""M1 offline tests: no network, database or CRM access required."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from m1_snapshot_hubspot import digest, safe_properties, PROPERTIES, MAX_RECORDS_PER_OBJECT  # noqa: E402


class TestM1Safety(unittest.TestCase):
    def test_only_two_objects(self):
        self.assertEqual(set(PROPERTIES), {'contacts', 'companies'})

    def test_sensitive_unrequested_properties_filtered(self):
        item = {'properties': {'firstname': 'Example', 'email': 'user@example.test',
                               'private_custom_value': 'DO_NOT_COPY'}}
        result = safe_properties(item, 'contacts')
        self.assertEqual(result['firstname'], 'Example')
        self.assertNotIn('private_custom_value', result)

    def test_digest_order_independence(self):
        self.assertEqual(digest({'a': 1, 'b': 2}), digest({'b': 2, 'a': 1}))

    def test_caps_low(self):
        self.assertEqual(MAX_RECORDS_PER_OBJECT, 1000)


if __name__ == '__main__':
    unittest.main()
