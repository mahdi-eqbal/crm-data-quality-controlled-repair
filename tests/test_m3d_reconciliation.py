"""M3d offline reconciliation safety tests — no Airtable/API/DB/HubSpot calls."""
from __future__ import annotations

import copy
import hashlib
import json
import sys
import unittest
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'scripts'))
from crm_quality.review_queue import build_plan
from crm_quality.reconciliation import (
    ReconcileError, event_fingerprint, reconcile, utc_timestamp, validate_history,
)
from m3d_reconcile import db_history


class TestM3dReconciliation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plan = build_plan(ROOT / 'fixtures' / 'synthetic')
        cls.row = cls.plan['rows'][0]
        cls.cid = str(cls.row['candidate_id'])

    def setUp(self):
        self.base_event = {
            'candidate_id': self.cid,
            'airtable_record_id': 'rec0123456789ABCD',
            'decision': 'Needs More Evidence',
            'notes': 'Legal entity identity needs independent verification',
            'edited_at': '2026-11-09T17:01:33.000000+00:00',
            'reviewer_id': 'usr0123456789ABCD',
        }
        self.base_event = self.attach(self.base_event)
        self.snapshot = {
            'sha256': 'a' * 64,
            'batch_id': str(self.plan['batch_id']),
            'total': 57,
            'not_reviewed': 56,
            'blanks': 3,
            'decisions': [copy.deepcopy(self.base_event)],
        }

    @staticmethod
    def attach(event):
        item = dict(event)
        sha, event_id = event_fingerprint(item)
        return {**item, 'payload_sha256': sha, 'event_id': event_id}

    def check(self, snapshot=None, db=None):
        return reconcile(snapshot if snapshot is not None else self.snapshot,
                         db if db is not None else [self.base_event], self.plan)

    def test_matching_decision_is_in_sync(self):
        r = self.check()
        self.assertTrue(r['reconciled'])
        self.assertEqual(r['summary']['in_sync'], 1)
        self.assertEqual(r['summary']['not_reviewed'], 56)
        self.assertEqual(r['postgres_events'], 1)
        self.assertEqual(r['discrepancies'], [])

    def test_two_revisions_one_classified(self):
        old = dict(self.base_event)
        old['notes'] = 'Earlier review requested additional legal identity evidence'
        old['edited_at'] = '2026-11-09T16:44:09.000000+00:00'
        old = self.attach(old)
        r = self.check(db=[old, self.base_event])
        self.assertTrue(r['reconciled'])
        self.assertEqual(r['postgres_events'], 2)
        self.assertEqual(r['postgres_revisions'], 1)
        self.assertEqual(r['postgres_classified_candidates'], 1)

    def test_no_decisions_is_reconciled(self):
        snap = {**self.snapshot, 'decisions': [], 'not_reviewed': 57}
        r = self.check(snapshot=snap, db=[])
        self.assertTrue(r['reconciled'])
        self.assertEqual(r['summary']['not_reviewed'], 57)
        self.assertEqual(r['summary']['in_sync'], 0)

    def test_pending_import_new_decision(self):
        r = self.check(db=[])
        self.assertFalse(r['reconciled'])
        self.assertEqual(r['summary']['pending_import'], 1)
        self.assertEqual(r['discrepancies'][0]['action'], 'manual_preview_and_digest_gated_apply')

    def test_pending_import_later_revision(self):
        old = dict(self.base_event)
        old['edited_at'] = '2026-11-09T16:44:09+00:00'
        old['notes'] = 'Old review requested legal verification first'
        r = self.check(db=[self.attach(old)])
        self.assertEqual(r['summary']['pending_import'], 1)

    def test_stale_airtable_snapshot(self):
        future = dict(self.base_event)
        future['edited_at'] = '2026-11-09T18:00:00+00:00'
        future['notes'] = 'Newer revision still requires legal identity verification'
        r = self.check(db=[self.base_event, self.attach(future)])
        self.assertEqual(r['summary']['stale_airtable'], 1)
        self.assertFalse(r['reconciled'])

    def test_cleared_already_imported_decision(self):
        snap = {**self.snapshot, 'decisions': [], 'not_reviewed': 57}
        r = self.check(snapshot=snap)
        self.assertEqual(r['summary']['cleared_in_airtable'], 1)
        self.assertEqual(r['discrepancies'][0]['action'], 'manual_investigation_required')

    def test_same_timestamp_different_notes_is_conflict(self):
        db = dict(self.base_event)
        db['notes'] = 'Different content saved at same last modified timestamp'
        r = self.check(db=[self.attach(db)])
        self.assertFalse(r['reconciled'])
        self.assertEqual(r['summary']['same_timestamp_conflict'], 1)

    def test_same_timestamp_different_verdict_is_conflict(self):
        db = dict(self.base_event)
        db['decision'] = 'Different Entity'
        r = self.check(db=[self.attach(db)])
        self.assertEqual(r['summary']['same_timestamp_conflict'], 1)

    def test_unknown_candidate_in_db_fails_closed(self):
        fake = dict(self.base_event)
        fake['candidate_id'] = str(uuid.uuid4())
        with self.assertRaises(ReconcileError):
            self.check(db=[self.attach(fake)])

    def test_invalid_db_payload_hash_fails_closed(self):
        broken = {**self.base_event, 'payload_sha256': '0' * 64}
        with self.assertRaises(ReconcileError):
            self.check(db=[broken])

    def test_invalid_db_event_id_fails_closed(self):
        broken = {**self.base_event, 'event_id': str(uuid.uuid4())}
        with self.assertRaises(ReconcileError):
            self.check(db=[broken])

    def test_invalid_incoming_payload_fails_closed(self):
        snap = copy.deepcopy(self.snapshot)
        snap['decisions'][0]['payload_sha256'] = '0' * 64
        with self.assertRaises(ReconcileError):
            self.check(snapshot=snap)

    def test_duplicate_incoming_candidate_fails_closed(self):
        snap = copy.deepcopy(self.snapshot)
        snap['decisions'].append(copy.deepcopy(self.base_event))
        snap['not_reviewed'] = 55
        with self.assertRaises(ReconcileError):
            self.check(snapshot=snap)

    def test_invalid_incoming_batch_fails_closed(self):
        snap = {**self.snapshot, 'batch_id': str(uuid.uuid4())}
        with self.assertRaises(ReconcileError):
            self.check(snapshot=snap)

    def test_incomplete_candidate_coverage_fails_closed(self):
        snap = {**self.snapshot, 'not_reviewed': 55}
        with self.assertRaises(ReconcileError):
            self.check(snapshot=snap)

    def test_out_of_order_revisions_fail_closed(self):
        old = dict(self.base_event)
        old['edited_at'] = '2026-11-09T16:44:09+00:00'
        old['notes'] = 'Earlier revision still requires verification'
        with self.assertRaises(ReconcileError):
            self.check(db=[self.base_event, self.attach(old)])

    def test_duplicate_stored_event_fails_closed(self):
        with self.assertRaises(ReconcileError):
            self.check(db=[self.base_event, self.base_event])

    def test_record_provenance_change_in_history_fails_closed(self):
        old = dict(self.base_event)
        old['edited_at'] = '2026-11-09T16:44:09+00:00'
        old['airtable_record_id'] = 'rec99999999999999'
        old['notes'] = 'Previous synthetic reviewer note verified'
        with self.assertRaises(ReconcileError):
            self.check(db=[self.attach(old), self.base_event])

    def test_unsafe_journal_note_fails_closed(self):
        x = dict(self.base_event)
        x['notes'] = 'short'
        with self.assertRaises(ReconcileError):
            self.check(db=[x])

    def test_missing_time_zone_fails_closed(self):
        with self.assertRaises(ReconcileError):
            utc_timestamp('2026-11-09T17:00:00')

    def test_event_limit_fails_closed(self):
        # No actual database writes: high record counts rejected before processing.
        with self.assertRaises(ReconcileError):
            validate_history([self.base_event] * 501, {self.cid})

    def test_report_contains_no_reviewer_note_or_email(self):
        r = self.check()
        serialized = json.dumps(r)
        self.assertNotIn(self.base_event['notes'], serialized)
        self.assertNotIn(self.base_event['reviewer_id'], serialized)
        self.assertNotIn('AIRTABLE_REVIEW_PAT', serialized)
        self.assertEqual(r['policy'], 'read_only_no_crm_writes_no_automatic_resolution')

    def test_db_history_accepts_unchanged_synthetic_queue(self):
        plan = self.plan
        row = self.row
        class Cursor:
            def __init__(self): self.n = 0
            def execute(self, query, params):
                self.n += 1
                self.params = params
            def fetchone(self):
                return (plan['batch_id'], plan['source_fingerprint'], 'synthetic_fixture_only',
                        plan['rule_version'], 57)
            def fetchall(self):
                if self.n == 2:
                    return [(str(x['candidate_id']), x['object_type'], x['record_id_1'], x['record_id_2'],
                             x['tier'], x['route'], x['queue_status'], x['rule_code'], x['route_reason'],
                             x['evidence_codes'], x['name_similarity'], False, False)
                            for x in plan['rows']]
                return []
        c=Cursor()
        self.assertEqual(db_history(c, plan), [])
        self.assertEqual(c.n, 3)

    def test_db_history_rejects_enabled_crm_write_flag(self):
        plan = self.plan
        class Cursor:
            def __init__(self): self.n = 0
            def execute(self, query, params): self.n += 1
            def fetchone(self):
                return (plan['batch_id'], plan['source_fingerprint'], 'synthetic_fixture_only',
                        plan['rule_version'], 57)
            def fetchall(self):
                if self.n == 2:
                    return [(str(x['candidate_id']), x['object_type'], x['record_id_1'], x['record_id_2'],
                             x['tier'], x['route'], x['queue_status'], x['rule_code'], x['route_reason'],
                             x['evidence_codes'], x['name_similarity'], False, i == 0)
                            for i,x in enumerate(plan['rows'])]
                return []
        with self.assertRaises(ReconcileError):
            db_history(Cursor(), plan)

    def test_comparison_has_no_crm_or_db_write_path(self):
        from pathlib import Path
        script = (ROOT / 'scripts' / 'm3d_reconcile.py').read_text()
        self.assertNotIn('requests.post(', script)
        self.assertNotIn('INSERT INTO', script)
        self.assertNotIn('UPDATE crm_', script)
        self.assertNotIn('DELETE FROM', script)
        self.assertIn('conn.read_only = True', script)
        self.assertIn('REPEATABLE_READ', script)


if __name__ == '__main__':
    unittest.main()
