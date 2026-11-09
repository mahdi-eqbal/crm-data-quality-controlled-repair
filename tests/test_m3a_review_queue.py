"""M3a offline unit tests. No PostgreSQL or CRM access needed."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from crm_quality.review_queue import (build_plan, local_pg_settings, synthetic_fingerprint,
                                      summarize_plan, validate_candidate, validate_fixture)


class TestM3aQueue(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = ROOT / 'fixtures' / 'synthetic'
        cls.plan = build_plan(cls.fixture)

    def test_only_intended_review_candidates_staged(self):
        self.assertEqual(len(self.plan['rows']), 57)
        self.assertEqual(self.plan['excluded_exploratory_hints'], 114)
        self.assertEqual(summarize_plan(self.plan), {'needs_evidence': 7, 'pending_review': 50})

    def test_expected_object_and_route_counts(self):
        c = Counter((r['object_type'], r['route']) for r in self.plan['rows'])
        self.assertEqual(c[('contacts', 'priority_review')], 9)
        self.assertEqual(c[('contacts', 'standard_review')], 25)
        self.assertEqual(c[('contacts', 'needs_external_evidence')], 7)
        self.assertEqual(c[('companies', 'priority_review')], 10)
        self.assertEqual(c[('companies', 'standard_review')], 6)

    def test_idempotent_fingerprint_and_ids(self):
        rerun = build_plan(self.fixture)
        self.assertEqual(self.plan, rerun)
        self.assertEqual(len({r['candidate_id'] for r in rerun['rows']}), 57)
        self.assertEqual(len({r['event_id'] for r in rerun['rows']}), 57)

    def test_no_pii_or_authority_in_candidate_rows(self):
        serialized = json.dumps(self.plan['rows'], default=str).lower()
        for bad in ('@', '"email":', '"first_name":', '"last_name":', '"phone":', '"company_name":', 'approved_for_crm_write'):
            self.assertNotIn(bad, serialized)
        self.assertTrue(all(r['queue_status'] in ('pending_review', 'needs_evidence')
                            for r in self.plan['rows']))

    def test_external_evidence_separate_from_main_queue(self):
        for row in self.plan['rows']:
            if row['route'] == 'needs_external_evidence':
                self.assertEqual(row['queue_status'], 'needs_evidence')
            else:
                self.assertEqual(row['queue_status'], 'pending_review')

    def test_unsafe_candidate_rejected(self):
        base = {
            'object_type': 'contacts', 'record_id_1': 'C0001', 'record_id_2': 'C0002',
            'tier': 'review', 'route': 'standard_review', 'rule': 'name_plus_context',
            'route_reason': 'human_adjudication_required', 'evidence': ['shared_company'],
            'name_similarity': 92, 'requires_human_review': True,
            'merge_allowed': False, 'approved_for_crm_write': False,
            'eligible_for_review_queue': True,
        }
        validate_candidate(base, {'C0001', 'C0002'}, set())
        for change in (
            {'merge_allowed': True}, {'approved_for_crm_write': True},
            {'eligible_for_review_queue': False}, {'route': 'exploratory_only'},
            {'rule': 'unsafe @PII'}, {'record_id_2': 'C9999'},
        ):
            with self.subTest(change=change):
                with self.assertRaises(ValueError):
                    validate_candidate({**base, **change}, {'C0001', 'C0002'}, set())

    def test_not_accept_non_local_database(self):
        env = {'PGHOST': 'db.example.com', 'PGPORT': '5433', 'PGPASSWORD': 'not-a-secret'}
        with self.assertRaises(ValueError):
            local_pg_settings(env)
        with self.assertRaises(ValueError):
            local_pg_settings({'PGHOST': '127.0.0.1', 'PGPORT': '5432', 'PGPASSWORD': 'x'})
        with self.assertRaises(ValueError):
            local_pg_settings({'PGHOST': '127.0.0.1', 'PGPORT': '5433'})
        self.assertEqual(local_pg_settings({'PGPASSWORD': 'test'})['port'], 5433)

    def test_validation_rejects_non_synthetic_email(self):
        # Isolate temporary fixture copies; never modify canonical fixture.
        import shutil
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp)
            for filename in ('manifest.json', 'contacts.csv', 'companies.csv', 'associations.csv'):
                shutil.copyfile(self.fixture / filename, dest / filename)
            src = (dest / 'contacts.csv').read_text(encoding='utf-8')
            src = src.replace('.example', '.com', 1)
            (dest / 'contacts.csv').write_text(src, encoding='utf-8')
            with self.assertRaises(ValueError):
                validate_fixture(dest)

    def test_source_fingerprint_changes_on_fixture_change(self):
        import shutil
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp)
            for name in ('manifest.json', 'contacts.csv', 'companies.csv', 'associations.csv'):
                shutil.copyfile(self.fixture / name, dest / name)
            before = synthetic_fingerprint(dest)
            (dest / 'manifest.json').write_text((dest / 'manifest.json').read_text() + '\n')
            self.assertNotEqual(before, synthetic_fingerprint(dest))

    def test_schema_never_grants_write_or_merge(self):
        sql = (ROOT / 'sql' / '003_m3a_review_queue.sql').read_text(encoding='utf-8')
        self.assertIn('CHECK (NOT merge_allowed)', sql)
        self.assertIn('CHECK (NOT approved_for_crm_write)', sql)
        self.assertIn('UNIQUE (batch_id, object_type, record_id_1, record_id_2)', sql)

    def test_actions_manual_only(self):
        workflow = (ROOT / '.github' / 'workflows' / 'tests.yml').read_text(encoding='utf-8')
        self.assertIn('workflow_dispatch:', workflow)
        self.assertNotIn('\n  push:', workflow)
        self.assertNotIn('\n  pull_request:', workflow)


if __name__ == '__main__':
    unittest.main()
