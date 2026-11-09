"""M5a offline contract tests: no network, database, CRM writes or real data."""
from __future__ import annotations

import copy
import json
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'scripts'))
from crm_quality.live_preflight import (  # noqa: E402
    FIELDS, PORTAL_ID, LivePreflightError, _sha, _types, compare,
    fetch_live, read_baseline,
)
import m5a_live_readonly_preflight as cli  # noqa: E402


class FakeCursor:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []
        self.current = None

    def execute(self, sql, params):
        self.calls.append((sql, params))
        self.current = next(self.responses)

    def fetchone(self):
        return self.current

    def fetchall(self):
        return self.current


class TestM5a(unittest.TestCase):
    def setUp(self):
        self.mock_token = 'test-only-token-long-enough'
        self.contacts = [dict(id='101', updatedAt='2026-11-01T13:00:00Z', archived=False,
                              properties={'firstname': 'Fictional', 'lastname': 'Person',
                                          'email': 'fake@example.test', 'phone': None})]
        self.companies = [dict(id='201', updatedAt='2026-11-01T14:00:00Z', archived=False,
                               properties={'name': 'Example Inc', 'domain': 'example.test',
                                           'country': 'United States', 'phone': None})]
        self.associations = [dict(toObjectId=201, associationTypes=[
            {'category': 'HUBSPOT_DEFINED', 'typeId': 1, 'label': 'Primary'}])]
        self.calls = []

        def opener(url, token):
            self.calls.append(url)
            self.assertEqual(token, self.mock_token)
            if 'account-info/' in url:
                return {'portalId': int(PORTAL_ID)}
            if '/contacts?' in url:
                return {'results': self.contacts}
            if '/associations/companies?' in url:
                return {'results': self.associations}
            if '/companies?' in url:
                return {'results': self.companies}
            self.fail('Unknown URL ' + url)
        self.get = opener
        self.live = fetch_live(self.mock_token, PORTAL_ID, self.get)
        self.base = {'baseline_run_id': 'test-run-id',
                     'records': copy.deepcopy(self.live['records']),
                     'links': copy.deepcopy(self.live['links'])}

    def report(self, live=None, baseline=None):
        return compare(live or self.live, baseline or self.base, '2026-11-09T13:00:00Z')

    def test_01_bounded_verified_gets(self):
        self.assertEqual(self.calls[0].count('account-info'), 1)
        self.assertEqual(self.live['http_get_count'], 4)
        self.assertEqual(len(self.calls), 4)
        self.assertTrue(all(x.startswith('https://api.hubapi.com/') for x in self.calls))

    def test_02_clean_diff(self):
        r = self.report()
        self.assertEqual(r['status'], 'READ_ONLY_IN_SYNC')
        self.assertEqual(r['crm_writes'], 0)
        self.assertFalse(r['write_authorized'])

    def test_03_no_pii_or_record_ids_in_report(self):
        dump = json.dumps(self.report())
        for value in ('Fictional', 'fake@example.test', 'Example Inc', '"101"', '"201"', self.mock_token):
            self.assertNotIn(value, dump)

    def test_04_added_contact_is_drift(self):
        live = copy.deepcopy(self.live)
        live['records']['contacts']['102'] = copy.deepcopy(live['records']['contacts']['101'])
        r = self.report(live)
        self.assertEqual((r['status'], r['metrics']['contacts']['added']), ('DRIFT_REQUIRES_REVIEW', 1))

    def test_05_removed_company_is_drift(self):
        base = copy.deepcopy(self.base)
        base['records']['companies']['202'] = copy.deepcopy(base['records']['companies']['201'])
        self.assertEqual(self.report(baseline=base)['metrics']['companies']['removed'], 1)

    def test_06_changed_properties_detected(self):
        live = copy.deepcopy(self.live)
        live['records']['companies']['201']['properties']['country'] = 'US'
        self.assertEqual(self.report(live)['metrics']['companies']['changed_properties'], 1)

    def test_07_changed_update_time_detected(self):
        live = copy.deepcopy(self.live)
        live['records']['companies']['201']['updated_at'] = '2026-11-10T00:00:00+00:00'
        self.assertEqual(self.report(live)['metrics']['companies']['changed_updated_at'], 1)

    def test_08_new_association_detected(self):
        live = copy.deepcopy(self.live)
        live['links'][('101', '202')] = []
        self.assertEqual(self.report(live)['metrics']['associations']['added'], 1)

    def test_09_removed_association_detected(self):
        live = copy.deepcopy(self.live)
        live['links'].clear()
        self.assertEqual(self.report(live)['metrics']['associations']['removed'], 1)

    def test_10_modified_label_detected(self):
        live = copy.deepcopy(self.live)
        live['links'][('101', '201')][0]['label'] = 'Secondary'
        self.assertEqual(self.report(live)['metrics']['associations']['changed_types'], 1)

    def test_11_wrong_portal_blocks_before_api(self):
        with self.assertRaises(LivePreflightError):
            fetch_live(self.mock_token, '987654', self.get)
        self.assertEqual(len(self.calls), 4)

    def test_12_mismatched_api_portal_fails_closed(self):
        with self.assertRaises(LivePreflightError):
            fetch_live(self.mock_token, PORTAL_ID, lambda *_: {'portalId': 222})

    def test_13_object_page_overflow_rejected(self):
        def fake(url, token):
            if '/contacts?' in url:
                return {'results': self.contacts, 'paging': {'next': {'after': 'abc'}}}
            return self.get(url, token)
        with self.assertRaises(LivePreflightError):
            fetch_live(self.mock_token, PORTAL_ID, fake)

    def test_14_assoc_page_overflow_rejected(self):
        def fake(url, token):
            if '/associations/companies?' in url:
                return {'results': self.associations, 'paging': {'next': {'after': 'other'}}}
            return self.get(url, token)
        with self.assertRaises(LivePreflightError):
            fetch_live(self.mock_token, PORTAL_ID, fake)

    def test_15_unknown_assoc_target_rejected(self):
        self.associations = [dict(toObjectId=999, associationTypes=[])]
        with self.assertRaises(LivePreflightError):
            fetch_live(self.mock_token, PORTAL_ID, self.get)

    def test_16_repeated_assoc_pair_rejected(self):
        self.associations.append(copy.deepcopy(self.associations[0]))
        with self.assertRaises(LivePreflightError):
            fetch_live(self.mock_token, PORTAL_ID, self.get)

    def test_17_repeated_id_rejected(self):
        self.contacts.append(copy.deepcopy(self.contacts[0]))
        with self.assertRaises(LivePreflightError):
            fetch_live(self.mock_token, PORTAL_ID, self.get)

    def test_18_invalid_record_timestamp_rejected(self):
        self.contacts[0]['updatedAt'] = 'not-a-time'
        with self.assertRaises(LivePreflightError):
            fetch_live(self.mock_token, PORTAL_ID, self.get)

    def test_19_invalid_association_types_rejected(self):
        with self.assertRaises(LivePreflightError):
            _types([{'category': 'X', 'typeId': 'bad'}])

    def test_20_conflicting_association_label_rejected(self):
        with self.assertRaises(LivePreflightError):
            _types([{'category': 'X', 'typeId': 1, 'label': 'A'},
                    {'category': 'X', 'typeId': 1, 'label': 'B'}])

    def test_21_stored_baseline_read_verified(self):
        c = self.live['records']['contacts']['101']
        p = self.live['records']['companies']['201']
        cursor = FakeCursor([
            ('00000000-0000-0000-0000-000000000001', 1, 1, 1, 1, 0),
            [('contacts', '101', datetime.fromisoformat(c['updated_at']), c['properties'], _sha(c['properties'])),
             ('companies', '201', datetime.fromisoformat(p['updated_at']), p['properties'], _sha(p['properties']))],
            [('101', '201', self.live['links'][('101','201')])],
        ])
        baseline = read_baseline(cursor)
        self.assertEqual(baseline['records'], self.base['records'])
        self.assertEqual(self.report(baseline=baseline)['status'], 'READ_ONLY_IN_SYNC')
        self.assertEqual(len(cursor.calls), 3)
        self.assertTrue(all(q.lstrip().upper().startswith('SELECT') for q, _ in cursor.calls))

    def test_22_corrupt_stored_sha_rejected(self):
        c = self.live['records']['contacts']['101']
        cursor = FakeCursor([
            ('run-id', 1, 0, 1, 0, 1),
            [('contacts', '101', datetime.fromisoformat(c['updated_at']), c['properties'], '0' * 64)],
            [],
        ])
        with self.assertRaises(LivePreflightError):
            read_baseline(cursor)

    def test_23_stored_missing_record_rejected(self):
        cursor = FakeCursor([('run-id', 1, 1, 1, 0, 1), [], []])
        with self.assertRaises(LivePreflightError):
            read_baseline(cursor)

    def test_24_stored_manifest_mismatch_rejected(self):
        cursor = FakeCursor([('run-id', 1, 1, 0, 0, 0)])
        with self.assertRaises(LivePreflightError):
            read_baseline(cursor)

    def test_25_stored_no_verified_run_rejected(self):
        cursor = FakeCursor([None])
        with self.assertRaises(LivePreflightError):
            read_baseline(cursor)

    def test_26_cli_defaults_and_no_credential_output(self):
        code = (ROOT / 'scripts' / 'm5a_live_readonly_preflight.py').read_text('utf-8')
        self.assertIn("options='-c default_transaction_read_only=on'", code)
        self.assertIn("method='GET'", code)
        self.assertNotIn("method='POST'", code)
        self.assertNotIn("method='PATCH'", code)
        self.assertNotIn('print(key)', code)

    def test_27_repeated_report_stable_digest(self):
        self.assertEqual(self.report()['report_sha256'], self.report()['report_sha256'])

    def test_28_extra_pagination_is_never_silently_accepted(self):
        self.contacts[:] = [copy.deepcopy(self.contacts[0]) for _ in range(11)]
        for i, rec in enumerate(self.contacts):
            rec['id'] = str(101+i)
        with self.assertRaises(LivePreflightError):
            fetch_live(self.mock_token, PORTAL_ID, self.get)

    def test_29_offline_no_secrets_or_network(self):
        # The pure comparison cannot access APIs or write any external data.
        with patch('urllib.request.urlopen', side_effect=AssertionError('network not allowed')):
            self.assertEqual(self.report()['crm_writes'], 0)


if __name__ == '__main__':
    unittest.main()
