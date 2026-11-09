"""M5b synthetic offline tests; no API, DB or actual credentials."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from crm_quality.timestamp_diagnostics import diagnose  # noqa: E402
from crm_quality.live_preflight import LivePreflightError, PORTAL_ID  # noqa: E402


def make_fixture():
    props = {'firstname': 'Fictional', 'lastname': 'Person', 'email': 'fictitious@example.test', 'phone': None}
    company = {'name': 'Fictional Inc', 'domain': 'fictional.example', 'country': 'US', 'phone': None}
    base = {
        'baseline_run_id': 'fixture-only-run',
        'records': {'contacts': {
            '101': {'updated_at': '2026-11-01T10:00:00+00:00', 'properties': copy.deepcopy(props)},
            '102': {'updated_at': '2026-11-01T11:00:00+00:00', 'properties': copy.deepcopy(props)},
            '103': {'updated_at': '2026-11-01T12:00:00+00:00', 'properties': copy.deepcopy(props)},
        }, 'companies': {'201': {'updated_at': '2026-11-01T10:00:00+00:00', 'properties': company}}},
        'links': {('101', '201'): []},
    }
    live = {'verified_portal': PORTAL_ID, 'records': copy.deepcopy(base['records']),
            'links': copy.deepcopy(base['links']), 'http_get_count': 6}
    return live, base


class TestM5b(unittest.TestCase):
    def report(self, changed=True):
        live, base = make_fixture()
        if changed:
            for i, key in enumerate(('101', '102', '103')):
                live['records']['contacts'][key]['updated_at'] = f'2026-11-09T17:00:{i:02d}+00:00'
        return diagnose(live, base, observed_at='2026-11-09T17:05:00+00:00')

    def test_no_changes(self):
        r = self.report(False)
        self.assertEqual((r['status'], r['contact_count']['timestamps_changed']), ('NO_DETECTED_DRIFT', 0))

    def test_three_changes_aliases(self):
        r = self.report()
        self.assertEqual([x['alias'] for x in r['changed_contact_timestamps']],
                         ['changed_contact_01', 'changed_contact_02', 'changed_contact_03'])

    def test_only_observed_scope(self):
        self.assertEqual(self.report()['status'], 'TIMESTAMP_ONLY_IN_OBSERVED_SCOPE')

    def test_directions_later(self):
        self.assertEqual(self.report()['all_changed_timestamps_direction'], 'later')

    def test_deltas_nonzero(self):
        self.assertTrue(all(x['delta_ms'] > 0 for x in self.report()['changed_contact_timestamps']))

    def test_clusters(self):
        r = self.report()
        self.assertTrue(r['live_updates_within_5_minutes'])
        self.assertEqual(r['changed_live_update_span_seconds'], 2)

    def test_large_span_no_cluster(self):
        live, base = make_fixture()
        live['records']['contacts']['101']['updated_at'] = '2026-11-09T10:00:00Z'
        live['records']['contacts']['102']['updated_at'] = '2026-11-09T12:00:00Z'
        r = diagnose(live, base, observed_at='2026-11-09T13:00:00Z')
        self.assertFalse(r['live_updates_within_5_minutes'])

    def test_single_change_span_none(self):
        live, base = make_fixture()
        live['records']['contacts']['101']['updated_at'] = '2026-11-09T10:00:00Z'
        r = diagnose(live, base, observed_at='2026-11-09T13:00:00Z')
        self.assertIsNone(r['changed_live_update_span_seconds'])

    def test_earlier(self):
        live, base = make_fixture()
        live['records']['contacts']['101']['updated_at'] = '2026-10-31T10:00:00Z'
        r = diagnose(live, base, observed_at='2026-11-09T13:00:00Z')
        self.assertEqual(r['all_changed_timestamps_direction'], 'earlier')

    def test_mixed(self):
        live, base = make_fixture()
        live['records']['contacts']['101']['updated_at'] = '2026-10-31T10:00:00Z'
        live['records']['contacts']['102']['updated_at'] = '2026-11-08T10:00:00Z'
        r = diagnose(live, base, observed_at='2026-11-09T13:00:00Z')
        self.assertEqual(r['all_changed_timestamps_direction'], 'mixed')

    def test_changed_property_other_drift(self):
        live, base = make_fixture()
        live['records']['contacts']['101']['properties']['firstname'] = 'Other'
        r = diagnose(live, base, observed_at='2026-11-09T13:00:00Z')
        self.assertEqual(r['status'], 'OTHER_DRIFT_ALSO_PRESENT')

    def test_added_contact_other_drift(self):
        live, base = make_fixture()
        live['records']['contacts']['104'] = copy.deepcopy(live['records']['contacts']['103'])
        r = diagnose(live, base, observed_at='2026-11-09T13:00:00Z')
        self.assertEqual(r['status'], 'OTHER_DRIFT_ALSO_PRESENT')

    def test_company_timestamp_other_drift(self):
        live, base = make_fixture()
        live['records']['companies']['201']['updated_at'] = '2026-11-09T12:00:00Z'
        r = diagnose(live, base, observed_at='2026-11-09T13:00:00Z')
        self.assertEqual(r['status'], 'OTHER_DRIFT_ALSO_PRESENT')

    def test_link_change_other_drift(self):
        live, base = make_fixture()
        live['links'] = {}
        r = diagnose(live, base, observed_at='2026-11-09T13:00:00Z')
        self.assertEqual(r['status'], 'OTHER_DRIFT_ALSO_PRESENT')

    def test_wrong_portal(self):
        live, base = make_fixture()
        live['verified_portal'] = '999'
        with self.assertRaises(LivePreflightError):
            diagnose(live, base, observed_at='2026-11-09T13:00:00Z')

    def test_naive_timestamp_fails(self):
        live, base = make_fixture()
        live['records']['contacts']['101']['updated_at'] = '2026-11-09T15:00:00'
        with self.assertRaises(LivePreflightError):
            diagnose(live, base, observed_at='2026-11-09T13:00:00Z')

    def test_privacy_no_record_id_or_values(self):
        r = self.report()
        txt = json.dumps(r)
        for item in ('"101"', '"102"', '"103"', 'Fictional', 'fictitious@example.test', 'fictional.example'):
            self.assertNotIn(item, txt)

    def test_deterministic(self):
        self.assertEqual(self.report()['diagnostic_sha256'], self.report()['diagnostic_sha256'])

    def test_no_write_authorization(self):
        r = self.report()
        self.assertFalse(r['write_authorized'])
        self.assertEqual((r['crm_writes'], r['postgres_writes'], r['airtable_writes'], r['approvals']), (0, 0, 0, 0))

    def test_limits_cause_not_inferred(self):
        r = self.report()
        self.assertTrue(any('does not prove' in text for text in r['limitations']))


if __name__ == '__main__':
    unittest.main()
