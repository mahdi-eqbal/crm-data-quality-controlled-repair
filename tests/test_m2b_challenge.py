"""M2b fully labeled synthetic challenge and diagnostic invariants; no external I/O."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'scripts'))
from crm_quality.matching import match_records
from crm_quality.profiling import load_csv
from m2b_diagnose_and_benchmark import evaluate_complete_groups, run, diagnosed_missed


class TestM2BChallenge(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        base = ROOT / 'fixtures' / 'm2b_challenge'
        cls.contacts = load_csv(base / 'contacts.csv')
        cls.companies = load_csv(base / 'companies.csv')
        cls.links = load_csv(base / 'associations.csv')
        cls.group_labels = json.loads((base / 'identity_groups.json').read_text())

    def test_all_challenge_emails_are_fictional(self):
        for row in self.contacts:
            self.assertTrue(row['email'] == '' or row['email'].strip().endswith('.example'))
        for row in self.companies:
            self.assertTrue(row['domain'].endswith('.example'))

    def test_identity_groups_cover_every_record(self):
        self.assertEqual(set(self.group_labels['contact_identity_groups']),
                         {x['record_id'] for x in self.contacts})
        self.assertEqual(set(self.group_labels['company_identity_groups']),
                         {x['record_id'] for x in self.companies})

    def test_benchmark_is_deterministic(self):
        a = match_records(self.contacts, self.companies, self.links)
        b = match_records(list(reversed(self.contacts)),
                          list(reversed(self.companies)), list(reversed(self.links)))
        self.assertEqual(a, b)

    def test_full_pair_metrics_account_for_every_pair(self):
        report = run()
        for metric in report['m2b_challenge'].values():
            self.assertEqual(metric['true_positive'] + metric['false_positive'] +
                             metric['false_negative'] + metric['true_negative'],
                             metric['all_unordered_pairs'])

    def test_challenge_catches_review_false_positives(self):
        report = run()
        self.assertGreater(report['m2b_challenge']['contacts']['false_positive'], 0)
        self.assertGreater(report['m2b_challenge']['companies']['false_positive'], 0)
        self.assertEqual(report['m2b_challenge']['contacts']['strong_false_positives'], 0)
        self.assertEqual(report['m2b_challenge']['companies']['strong_false_positives'], 0)

    def test_original_missed_pairs_have_evidence_explanations(self):
        report = run()['m0_missed_positive_diagnostics']
        self.assertEqual(report['missed_pairs'], 7)
        self.assertEqual(report['failure_reason_counts'], {
            'different_emails_without_independent_evidence': 3,
            'insufficient_independent_evidence_missing_email': 4,
        })
        self.assertTrue(all(r['was_blocked'] for r in report['details']))

    def test_incomplete_identity_labels_rejected(self):
        with self.assertRaises(ValueError):
            evaluate_complete_groups(self.contacts, [], 'contacts', {'XCT01': 'x'})

    def test_merge_eligible_predictions_rejected(self):
        pred = [{'object_type': 'contacts', 'record_id_1': 'XCT01',
                 'record_id_2': 'XCT02', 'tier': 'strong_evidence',
                 'merge_allowed': True, 'requires_human_review': True}]
        with self.assertRaises(ValueError):
            evaluate_complete_groups(self.contacts, pred, 'contacts',
                                     self.group_labels['contact_identity_groups'])

    def test_confusion_matrix_example(self):
        rows = [{'record_id': 'A'}, {'record_id': 'B'}, {'record_id': 'C'}]
        groups = {'A': 'same', 'B': 'same', 'C': 'different'}
        matches = [{'object_type': 'contacts', 'record_id_1': 'A', 'record_id_2': 'B',
                    'tier': 'review', 'merge_allowed': False, 'requires_human_review': True},
                   {'object_type': 'contacts', 'record_id_1': 'B', 'record_id_2': 'C',
                    'tier': 'review', 'merge_allowed': False, 'requires_human_review': True}]
        stats = evaluate_complete_groups(rows, matches, 'contacts', groups)
        self.assertEqual((stats['true_positive'], stats['false_positive'],
                          stats['false_negative'], stats['true_negative']), (1, 1, 0, 1))
        self.assertEqual(stats['candidate_precision_pct'], 50.0)
        self.assertEqual(stats['candidate_recall_pct'], 100.0)

    def test_all_challenge_candidates_require_review(self):
        pred = match_records(self.contacts, self.companies, self.links)
        self.assertTrue(all(p['requires_human_review'] and not p['merge_allowed'] for p in pred))


if __name__ == '__main__':
    unittest.main()
