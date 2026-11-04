"""M1b association snapshot tests: offline only, no API/DB calls."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
# When tested in a project checkout, the original M1a/probe scripts are present.
# During isolated patch test we inject tiny import stubs if needed.
if not (SCRIPTS / 'm1_snapshot_hubspot.py').exists():
    import types
    m = types.ModuleType('m1_snapshot_hubspot')
    m.collect = lambda kind, token: []
    m.digest = lambda v: '0' * 64
    m.local_env = lambda: {}
    m.pg_config = lambda env: {}
    sys.modules['m1_snapshot_hubspot'] = m
if not (SCRIPTS / 'm1b_probe_associations.py').exists():
    import types
    p = types.ModuleType('m1b_probe_associations')
    p.ASSOCIATION_BASE = 'https://api.hubapi.com/crm/v4/objects/contacts'
    p.EXPECTED_PORTAL_ID = '149703596'
    p.MAX_ASSOC_PAGES = 10
    p.get_json = lambda url, token: {'results': []}
    p.verify_account = lambda token: 'VERIFIED'
    sys.modules['m1b_probe_associations'] = p
sys.path.insert(0, str(SCRIPTS))
import m1b_snapshot_associations as mod


class TestAssociationSnapshot(unittest.TestCase):
    def test_primary_and_unlabeled_association_labels_preserved(self):
        obj = [{'category': 'HUBSPOT_DEFINED', 'typeId': 1, 'label': 'Primary'},
               {'category': 'HUBSPOT_DEFINED', 'typeId': 279, 'label': None}]
        self.assertEqual(len(mod.normalize_types(obj)), 2)
        self.assertEqual(mod.normalize_types(obj)[0]['label'], 'Primary')

    def test_repeated_association_types_normalized(self):
        row = {'category': 'HUBSPOT_DEFINED', 'typeId': 1, 'label': 'Primary'}
        self.assertEqual(mod.normalize_types([row, row]), [row])

    def test_invalid_association_types_rejected(self):
        for bad in ('bad', [{'category': 'X'}], [{'typeId': 1}]):
            with self.assertRaises(ValueError):
                mod.normalize_types(bad)

    def test_paginated_links_preserve_union_of_labels(self):
        data = [
            {'results': [{'toObjectId': 11,
                          'associationTypes': [{'category': 'HUBSPOT_DEFINED', 'typeId': 1, 'label': 'Primary'}]}],
             'paging': {'next': {'after': 'page2'}}},
            {'results': [{'toObjectId': 11,
                          'associationTypes': [{'category': 'HUBSPOT_DEFINED', 'typeId': 279, 'label': None}]},
                         {'toObjectId': 12, 'associationTypes': []}]},
        ]
        with patch.object(mod, 'get_json', side_effect=data), patch.object(mod.time, 'sleep'):
            links = mod.get_links('c1', 'unused')
        self.assertEqual(set(links), {'11', '12'})
        self.assertEqual(len(links['11']), 2)

    def test_missing_results_fails_closed(self):
        with patch.object(mod, 'get_json', return_value={'unexpected': []}):
            with self.assertRaises(ValueError):
                mod.get_links('c1', 'unused')

    def test_repeated_page_cursor_fails_closed(self):
        data = {'results': [], 'paging': {'next': {'after': 'stuck'}}}
        with patch.object(mod, 'get_json', return_value=data), patch.object(mod.time, 'sleep'):
            with self.assertRaises(ValueError):
                mod.get_links('c1', 'unused')

    def test_dangling_company_reference_blocked(self):
        contacts = [{'id': 'contact-1'}]
        companies = [{'id': 'company-2'}]
        with patch.object(mod, 'get_links', return_value={'other-company': []}):
            with self.assertRaisesRegex(ValueError, 'missing from this snapshot'):
                mod.make_relationships(contacts, companies, 'unused')

    def test_missing_association_is_supported(self):
        with patch.object(mod, 'get_links', return_value={}):
            self.assertEqual(mod.make_relationships([{'id': 'c1'}], [], 'unused'), [])

    def test_wrong_account_id_blocked(self):
        with self.assertRaises(ValueError):
            mod.assert_safe_env({'HUBSPOT_ACCOUNT_ID': '999',
                                 'HUBSPOT_SERVICE_KEY': 'dummy', 'PGPASSWORD': 'dummy'})

    def test_missing_db_password_blocked(self):
        with self.assertRaises(ValueError):
            mod.assert_safe_env({'HUBSPOT_ACCOUNT_ID': '149703596', 'HUBSPOT_SERVICE_KEY': 'dummy'})

    def test_unverified_account_cannot_snapshot(self):
        env = {'HUBSPOT_ACCOUNT_ID': '149703596', 'HUBSPOT_SERVICE_KEY': 'dummy',
               'PGPASSWORD': 'dummy'}
        with patch.object(mod, 'verify_account', return_value='UNVERIFIED'), \
             patch.dict(sys.modules, {'psycopg': type(sys)('psycopg')}):
            with self.assertRaisesRegex(ValueError, 'not independently verified'):
                mod.snapshot(env)

if __name__ == '__main__':
    unittest.main()
