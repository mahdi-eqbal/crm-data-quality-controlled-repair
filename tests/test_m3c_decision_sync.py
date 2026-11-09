"""M3c offline safety tests: no Airtable API/DB/HubSpot calls."""
from __future__ import annotations

import copy
import io
import json
import sys
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from crm_quality.decision_sync import (FIELD, IntakeError, apply_snapshot, prepare_snapshot,
                                      request_records, _score)


class FakeAPIResponse:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode('utf-8')

    def __enter__(self):
        return io.BytesIO(self.payload)

    def __exit__(self, *args):
        pass


class TestM3cIntake(unittest.TestCase):
    def setUp(self):
        self.batch = uuid.uuid5(uuid.NAMESPACE_DNS, 'm3c-test-batch')
        self.fingerprint = 'f' * 64
        self.plan = {'batch_id': self.batch, 'source_fingerprint': self.fingerprint,
                     'rule_version': 'synthetic-test', 'rows': []}
        self.raw = []
        for i in range(57):
            a, b = f'C{i + 1:04}', f'C{i + 101:04}'
            route = 'needs_external_evidence' if i >= 50 else 'standard_review'
            kind = 'contacts'
            candidate_id = uuid.uuid5(uuid.NAMESPACE_DNS, f'm3c-test-candidate-{i}')
            p = {'candidate_id': candidate_id, 'object_type': kind, 'record_id_1': a,
                 'record_id_2': b, 'tier': 'review', 'route': route,
                 'queue_status': 'needs_evidence' if i >= 50 else 'pending_review',
                 'evidence_codes': ['shared_company', 'human_review'],
                 'rule_code': 'name_plus_context', 'route_reason': 'human_adjudication_required',
                 'name_similarity': 90.25}
            self.plan['rows'].append(p)
            f = {FIELD['key']: f'{kind}:{a}:{b}', FIELD['uuid']: str(candidate_id),
                 FIELD['kind']: kind, FIELD['id1']: a, FIELD['id2']: b,
                 FIELD['tier']: 'review', FIELD['route']: route,
                 FIELD['status']: p['queue_status'],
                 FIELD['evidence']: ';'.join(p['evidence_codes']),
                 FIELD['rule']: p['rule_code'], FIELD['reason']: p['route_reason'],
                 FIELD['similarity']: 90.25, FIELD['batch']: str(self.batch),
                 FIELD['source']: self.fingerprint, FIELD['decision']: 'Not Reviewed'}
            self.raw.append({'id': f'rec{i:014}', 'fields': f})
        self.raw += [{'id': f'rec{i:014}', 'fields': {}} for i in range(57, 60)]

    def decide(self, i=0, decision='Different Entity', notes='Distinct company identifiers despite similar names'):
        x = self.raw[i]['fields']
        x[FIELD['decision']] = decision
        x[FIELD['notes']] = notes
        x[FIELD['edited_at']] = '2026-11-09T16:50:30.000Z'
        x[FIELD['edited_by']] = {'id': 'usrABCdef01234567', 'name': 'Demo Reviewer', 'email': 'do-not-copy@example.test'}

    def test_initial_state_57_unreviewed_and_three_empty_template_rows(self):
        s = prepare_snapshot(self.raw, self.plan)
        self.assertEqual(s['total'], 57)
        self.assertEqual(s['blanks'], 3)
        self.assertEqual(s['not_reviewed'], 57)
        self.assertEqual(s['decisions'], [])

    def test_decision_event_has_no_editor_email_or_name(self):
        self.decide()
        s = prepare_snapshot(self.raw, self.plan)
        self.assertEqual(len(s['decisions']), 1)
        event = s['decisions'][0]
        self.assertEqual(event['reviewer_id'], 'usrABCdef01234567')
        self.assertNotIn('email', json.dumps(event).lower())
        self.assertNotIn('Demo Reviewer', json.dumps(event))

    def test_digest_independent_of_order_and_repeatable(self):
        self.decide()
        a = prepare_snapshot(self.raw, self.plan)
        b = prepare_snapshot(list(reversed(self.raw)), self.plan)
        self.assertEqual(a, b)

    def test_changed_notes_change_digest(self):
        self.decide()
        a = prepare_snapshot(self.raw, self.plan)
        self.raw[0]['fields'][FIELD['notes']] = 'Additional synthetic reason for decision'
        b = prepare_snapshot(self.raw, self.plan)
        self.assertNotEqual(a['sha256'], b['sha256'])

    def test_missing_candidate_fails_closed(self):
        self.raw.pop(0)
        with self.assertRaises(IntakeError):
            prepare_snapshot(self.raw, self.plan)

    def test_extra_blank_record_fails_closed(self):
        self.raw.append({'id':'rec00000000000100','fields':{}})
        with self.assertRaises(IntakeError):
            prepare_snapshot(self.raw, self.plan)

    def test_duplicate_candidate_fails_closed(self):
        self.raw[1]['fields'][FIELD['uuid']] = self.raw[0]['fields'][FIELD['uuid']]
        with self.assertRaises(IntakeError):
            prepare_snapshot(self.raw, self.plan)

    def test_candidate_metadata_tampering_fails_closed(self):
        for field, val in ((FIELD['route'], 'priority_review'),
                           (FIELD['batch'], str(uuid.uuid4())),
                           (FIELD['similarity'], 100),
                           (FIELD['evidence'], 'other_code'),
                           (FIELD['source'], '0' * 64),
                           (FIELD['id2'], 'C9999')):
            with self.subTest(field=field):
                copy_rows = copy.deepcopy(self.raw)
                copy_rows[0]['fields'][field] = val
                with self.assertRaises(IntakeError):
                    prepare_snapshot(copy_rows, self.plan)

    def test_missing_decision_fails_closed(self):
        self.raw[0]['fields'].pop(FIELD['decision'])
        with self.assertRaises(IntakeError):
            prepare_snapshot(self.raw, self.plan)

    def test_unidentified_record_with_review_decision_fails_closed(self):
        self.raw[-1]['fields'][FIELD['decision']] = 'Same Entity'
        with self.assertRaises(IntakeError):
            prepare_snapshot(self.raw, self.plan)

    def test_needs_evidence_cannot_be_decided_same_or_different(self):
        for verdict in ('Same Entity', 'Different Entity'):
            self.decide(i=56, decision=verdict)
            with self.assertRaises(IntakeError):
                prepare_snapshot(self.raw, self.plan)
        self.decide(i=56, decision='Needs More Evidence')
        self.assertEqual(len(prepare_snapshot(self.raw, self.plan)['decisions']), 1)

    def test_pending_review_can_be_referred_for_evidence(self):
        self.decide(decision='Needs More Evidence')
        self.assertEqual(prepare_snapshot(self.raw, self.plan)['decisions'][0]['decision'], 'Needs More Evidence')

    def test_missing_reason_fails_closed(self):
        self.decide(notes='short')
        with self.assertRaises(IntakeError):
            prepare_snapshot(self.raw, self.plan)

    def test_email_url_or_phone_in_notes_fails_closed(self):
        for note in ('email me at real@example.org', 'More information at https://example.com',
                     'Please call +1 202 555 0171'):
            with self.subTest(note=note):
                self.decide(notes=note)
                with self.assertRaises(IntakeError):
                    prepare_snapshot(self.raw, self.plan)

    def test_editor_and_timestamp_required(self):
        self.decide()
        self.raw[0]['fields'].pop(FIELD['edited_by'])
        with self.assertRaises(IntakeError):
            prepare_snapshot(self.raw, self.plan)
        self.decide()
        self.raw[0]['fields'][FIELD['edited_at']] = 'not-date'
        with self.assertRaises(IntakeError):
            prepare_snapshot(self.raw, self.plan)

    def test_score_invalid_or_nan_fails_closed(self):
        for value in (-1, 101, float('nan'), 'NaN', True):
            with self.subTest(value=value):
                with self.assertRaises(IntakeError):
                    _score(value)

    def test_request_records_get_only_single_page(self):
        requests = []
        def opener(req, timeout):
            requests.append(req)
            return FakeAPIResponse({'records':self.raw})
        found = request_records('pat' + 'x' * 25, opener=opener)
        self.assertEqual(len(found), 60)
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0].get_method(), 'GET')
        self.assertIn('returnFieldsByFieldId=true', requests[0].full_url)
        self.assertNotIn('x' * 25, requests[0].full_url)

    def test_request_records_repeated_offsets_fail(self):
        def opener(req, timeout):
            return FakeAPIResponse({'records': [], 'offset':'repeated'})
        with self.assertRaises(IntakeError):
            request_records('pat' + 'x' * 25, opener=opener)

    def test_rollback_and_idempotent_event_logic(self):
        self.decide()
        snap = prepare_snapshot(self.raw, self.plan)
        class FakeCursor:
            def __init__(self):
                self.q = ''; self.latest = {}; self.insert_count = 0
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def execute(self, sql, args=None):
                self.q = sql
                if sql.strip().startswith('INSERT INTO crm_reviewer_decision_events'):
                    self.insert_count += 1
                    self.latest[str(args[1])] = (args[3], args[7])
            def fetchall(self):
                return [(uuid.UUID(x),) for x in self.latest]
            def fetchone(self):
                if 'source_modified_at, payload_sha256' in self.q:
                    return next(iter(self.latest.values())) if self.latest else None
                return None
        class FakeConn:
            def __init__(self): self.cur = FakeCursor()
            def cursor(self): return self.cur
        conn = FakeConn()
        with patch('crm_quality.decision_sync.ensure_db_plan'):
            first = apply_snapshot(conn, snap, self.plan)
            second = apply_snapshot(conn, snap, self.plan)
        self.assertEqual(first['inserted'], 1)
        self.assertEqual(second['inserted'], 0)
        self.assertEqual(second['replayed_without_change'], 1)
        self.assertEqual(conn.cur.insert_count, 1)

    def test_cleared_prior_decision_is_rejected(self):
        snap = prepare_snapshot(self.raw, self.plan)  # All Not Reviewed
        original_id = str(self.plan['rows'][0]['candidate_id'])
        class Cur:
            def __enter__(self): return self
            def __exit__(self, *_): pass
            def execute(self, sql, args=None): self.sql = sql
            def fetchall(self): return [(uuid.UUID(original_id),)]
        class Conn:
            def cursor(self): return Cur()
        with patch('crm_quality.decision_sync.ensure_db_plan'):
            with self.assertRaises(IntakeError):
                apply_snapshot(Conn(), snap, self.plan)

    def test_conflicting_same_timestamp_is_rejected(self):
        self.decide()
        snap = prepare_snapshot(self.raw, self.plan)
        class Cur:
            def __enter__(self): return self
            def __exit__(self, *_): pass
            def execute(self, sql, args=None): self.sql = sql
            def fetchall(self): return [(uuid.UUID(snap['decisions'][0]['candidate_id']),)]
            def fetchone(self):
                return (datetime.fromisoformat(snap['decisions'][0]['edited_at']), 'a' * 64)
        class Conn:
            def cursor(self): return Cur()
        with patch('crm_quality.decision_sync.ensure_db_plan'):
            with self.assertRaises(IntakeError):
                apply_snapshot(Conn(), snap, self.plan)

    def test_stale_older_revision_is_rejected(self):
        self.decide()
        snap = prepare_snapshot(self.raw, self.plan)
        class Cur:
            def __enter__(self): return self
            def __exit__(self, *_): pass
            def execute(self, sql, args=None): self.sql = sql
            def fetchall(self): return [(uuid.UUID(snap['decisions'][0]['candidate_id']),)]
            def fetchone(self):
                return (datetime(2026, 11, 10, tzinfo=timezone.utc), 'a' * 64)
        class Conn:
            def cursor(self): return Cur()
        with patch('crm_quality.decision_sync.ensure_db_plan'):
            with self.assertRaises(IntakeError):
                apply_snapshot(Conn(), snap, self.plan)

    def test_no_code_path_to_crm_write(self):
        source = (ROOT / 'src' / 'crm_quality' / 'decision_sync.py').read_text(encoding='utf-8')
        sql = (ROOT / 'sql' / '004_m3c_decision_events.sql').read_text(encoding='utf-8')
        self.assertIn('append-only', sql)
        self.assertIn('BEFORE UPDATE OR DELETE', sql)
        self.assertIn('CHECK (decision IN', sql)
        self.assertNotIn('api.hubapi.com', source)
        self.assertNotIn('crm.objects.contacts.write', source)
        self.assertNotIn('approved_for_crm_write=true', sql)


if __name__ == '__main__':
    unittest.main()
