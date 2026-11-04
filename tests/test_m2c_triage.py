"""Offline M2c triage tests; all records here are fictitious."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from crm_quality.matching import match_records
from crm_quality.matching_triage import (
    triage_matches, _name_only_hints, MAX_EXPLORATORY_NAME_BLOCK,
)
from crm_quality.profiling import load_csv


def contact(rid, first, last, email='', phone=''):
    return {'record_id': rid, 'first_name': first, 'last_name': last, 'email': email, 'phone': phone}


class TestM2cTriage(unittest.TestCase):
    def test_baseline_candidates_preserved(self):
        rows = [contact('C1', 'Ada', 'Stone', 'ada@example.com'),
                contact('C2', 'Ada', 'Stone', 'ADA@EXAMPLE.COM')]
        b = match_records(rows, [], [])
        t = triage_matches(rows, [], [])
        self.assertEqual([r['record_id_1'] for r in b], [r['record_id_1'] for r in t['candidates']])
        self.assertEqual(t['candidates'][0]['route'], 'priority_review')
        self.assertEqual(t['exploratory_hints'], [])

    def test_same_name_no_evidence_is_hint_not_review(self):
        rows = [contact('C1', 'Ava', 'Stone', 'ava@first.example'),
                contact('C2', 'AVA', 'STONE', 'ava@second.example')]
        t = triage_matches(rows, [], [])
        self.assertFalse(t['candidates'])
        self.assertEqual(len(t['exploratory_hints']), 1)
        self.assertFalse(t['exploratory_hints'][0]['eligible_for_review_queue'])

    def test_shared_email_conflicting_names_need_evidence(self):
        rows = [contact('C1', 'Office', 'Admin', 'ops@shared.example'),
                contact('C2', 'Sales', 'Desk', 'ops@shared.example')]
        t = triage_matches(rows, [], [])
        self.assertEqual(t['candidates'][0]['route'], 'needs_external_evidence')
        self.assertFalse(t['candidates'][0]['eligible_for_review_queue'])

    def test_same_name_shared_company_conflicting_emails_needs_evidence(self):
        rows = [contact('C1', 'Alex', 'Kim', 'alex@a.example'),
                contact('C2', 'Alex', 'Kim', 'alex@b.example')]
        comp = [{'record_id': 'O1', 'name': 'Example', 'domain': 'example.org'}]
        assoc = [{'contact_id': 'C1', 'company_id': 'O1'},
                 {'contact_id': 'C2', 'company_id': 'O1'}]
        t = triage_matches(rows, comp, assoc)
        self.assertEqual(t['candidates'][0]['route'], 'needs_external_evidence')

    def test_company_shared_domain_different_name_needs_evidence(self):
        rows = [{'record_id': 'O1', 'name': 'Northstar Holding', 'domain': 'n.example'},
                {'record_id': 'O2', 'name': 'Northstar Venture', 'domain': 'n.example'}]
        t = triage_matches([], rows, [])
        self.assertEqual(t['candidates'][0]['route'], 'needs_external_evidence')

    def test_company_equal_name_different_domain_needs_evidence(self):
        rows = [{'record_id': 'O1', 'name': 'Meridian Analytics', 'domain': 'meridian-a.example'},
                {'record_id': 'O2', 'name': 'Meridian Analytics LLC', 'domain': 'meridian-b.example'}]
        t = triage_matches([], rows, [])
        self.assertEqual(t['candidates'][0]['route'], 'needs_external_evidence')

    def test_no_candidate_authorizes_writes_or_merge(self):
        root = ROOT / 'fixtures' / 'synthetic'
        rows = [load_csv(root / (s + '.csv')) for s in ('contacts', 'companies', 'associations')]
        plan = triage_matches(*rows)
        for r in plan['candidates'] + plan['exploratory_hints']:
            self.assertTrue(r['requires_human_review'])
            self.assertFalse(r['merge_allowed'])
            self.assertFalse(r['approved_for_crm_write'])
        self.assertTrue(all(not r['eligible_for_review_queue'] for r in plan['exploratory_hints']))

    def test_skip_large_name_only_groups(self):
        rows = [contact('C'+str(i), 'Common', 'Name', str(i)+'@example.org')
                for i in range(MAX_EXPLORATORY_NAME_BLOCK + 1)]
        hints, cap = _name_only_hints(rows, set())
        self.assertEqual(hints, [])
        self.assertEqual(cap['oversized_name_groups_skipped'], 1)

    def test_deterministic_reversed_input(self):
        rows = [contact('C3', 'Nora', 'Lane'), contact('C1', 'Nora', 'Lane'),
                contact('C2', 'Other', 'Person')]
        a = triage_matches(rows, [], [])
        b = triage_matches(list(reversed(rows)), [], [])
        self.assertEqual(a, b)

    def test_name_only_hints_contain_ids_not_pii(self):
        rows = [contact('C1', 'Milo', 'Park', 'milo1@example.org'),
                contact('C2', 'Milo', 'Park', 'milo2@example.org')]
        hint = triage_matches(rows, [], [])['exploratory_hints'][0]
        self.assertFalse(any(k in hint for k in ('email', 'phone', 'first_name', 'last_name')))
        self.assertNotIn('Milo', str(hint))


if __name__ == '__main__':
    unittest.main()
