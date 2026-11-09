"""M4b offline acceptance and adversarial tests; no network/DB/API calls."""
from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from crm_quality.approval_preflight import (  # noqa: E402
    DEMO_KIND, GateError, build_approval_plan, evaluate_current_plan,
    preflight_request, validate_demo_decision, validate_fresh_source_gate,
)
from crm_quality.repair_planning import canonical_sha256  # noqa: E402
from crm_quality.review_queue import validate_fixture  # noqa: E402


class TestM4BApprovalPreflight(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = ROOT / 'fixtures' / 'synthetic'
        cls.policy_path = ROOT / 'config' / 'quality_policy.json'
        cls.plan = build_approval_plan(cls.folder, cls.policy_path)
        _, cls.companies, cls.associations = validate_fixture(cls.folder)
        cls.policy = json.loads(cls.policy_path.read_text(encoding='utf-8'))
        cls.eligible = next(r for r in cls.plan['requests'] if r['status'] == 'awaiting_independent_approval')
        cls.held = next(r for r in cls.plan['requests'] if r['status'] == 'held_duplicate_dependency')
        cls.row = next(x for x in cls.companies if x['record_id'] == cls.eligible['source_record_id'])
        cls.held_row = next(x for x in cls.companies if x['record_id'] == cls.held['source_record_id'])
        cls.now = datetime(2026, 11, 9, 13, tzinfo=timezone.utc)

    def decide(self, request=None, **overrides):
        request = request or self.eligible
        result = {
            'kind': DEMO_KIND, 'request_id': request['request_id'],
            'request_sha256': request['request_sha256'],
            'decision': 'approve_demo_preflight', 'proposed_by': 'fixture.proposer',
            'reviewed_by': 'fixture.independent',
            'reason': 'Fixture-only review simulation with explicit separation.',
            'reviewed_at': (self.now-timedelta(minutes=1)).isoformat(),
            'expires_at': (self.now+timedelta(hours=1)).isoformat(),
        }
        result.update(overrides)
        return result

    def check(self, request=None, row=None, associations=None, policy=None, plan_hash=None,
              decision=None, now=None):
        request = request or self.eligible
        if row is None:
            row = self.row if request == self.eligible else self.held_row
        return preflight_request(request, row, self.associations if associations is None else associations,
                                 self.policy if policy is None else policy,
                                 self.plan['source_plan_sha256'] if plan_hash is None else plan_hash,
                                 demo_decision=decision, now=now or self.now)

    def test_01_counts_31_requests_22_pending_9_held(self):
        self.assertEqual(self.plan['counts']['requests'], 31)
        self.assertEqual(self.plan['counts']['awaiting_independent_approval'], 22)
        self.assertEqual(self.plan['counts']['held_duplicate_dependency'], 9)
        self.assertEqual(self.plan['counts']['actual_approvals'], 0)

    def test_02_all_requests_are_company_country_only(self):
        self.assertTrue(all((r['object_type'], r['field'], r['old_value'], r['proposed_value']) ==
                            ('company', 'country', 'United States', 'US') for r in self.plan['requests']))

    def test_03_deterministic_gate_plan(self):
        self.assertEqual(self.plan, build_approval_plan(self.folder, self.policy_path))

    def test_04_unique_request_and_proposal_ids(self):
        for field in ('request_id','proposal_id'):
            self.assertEqual(len({r[field] for r in self.plan['requests']}), 31)

    def test_05_valid_digest_anchor(self):
        self.assertEqual(self.plan['gate_plan_sha256'], canonical_sha256({k:v for k,v in self.plan.items() if k!='gate_plan_sha256'}))
        self.assertEqual(self.eligible['request_sha256'], canonical_sha256({k:v for k,v in self.eligible.items() if k!='request_sha256'}))

    def test_06_no_authorization_flags(self):
        self.assertTrue(all(r['write_authorized'] is False and r['merge_authorized'] is False and
                            r['approval_recorded'] is False for r in self.plan['requests']))
        self.assertEqual(self.plan['guarantees']['approvals_granted'], 0)

    def test_07_no_sensitive_fields_in_gate_report(self):
        text = json.dumps(self.plan).lower()
        for value in ('@', 'first_name', 'last_name', 'phone', 'email', '.example', 'amber consulting'):
            self.assertNotIn(value, text)

    def test_08_held_dependency_never_approval_eligible(self):
        result = self.check(self.held, decision=self.decide(self.held))
        self.assertEqual(result['status'], 'held_duplicate_dependency')
        self.assertFalse(result['crm_write_authorized'])

    def test_09_pending_by_default(self):
        self.assertEqual(self.check()['status'], 'awaiting_independent_approval')

    def test_10_demo_success_is_not_real_approval(self):
        result = self.check(decision=self.decide())
        self.assertEqual(result['status'], 'demo_only_preflight_eligible')
        self.assertFalse(result['crm_write_authorized'])
        self.assertFalse(result['authenticated_approval_verified'])
        self.assertFalse(result['real_hubspot_preflight_performed'])

    def test_11_stale_source_rejected_before_demo_decision(self):
        changed = dict(self.row, industry='different')
        self.assertEqual(self.check(row=changed, decision=self.decide())['status'], 'stale_source_record')

    def test_12_stale_country_rejected(self):
        changed = dict(self.row, country='US')
        self.assertEqual(self.check(row=changed)['status'], 'stale_source_record')

    def test_13_record_timestamp_changed_blocked(self):
        changed = dict(self.row, updated_at='2026-11-01T00:00:00Z')
        self.assertEqual(self.check(row=changed)['status'], 'stale_source_record')

    def test_14_missing_source_blocked(self):
        self.assertEqual(self.check(row={}, decision=self.decide())['status'], 'missing_source_record')

    def test_15_association_changed_without_count_change_blocked(self):
        changed = copy.deepcopy(self.associations)
        match = next((a for a in changed if a['company_id'] == self.row['record_id']), None)
        if match is None:
            changed.append({'company_id':self.row['record_id'],'contact_id':'C9999','association_type':'primary'})
        else:
            match['association_type'] = 'tampered_type'
        self.assertEqual(self.check(associations=changed)['status'], 'association_changed')

    def test_16_source_plan_hash_mismatch(self):
        self.assertEqual(self.check(plan_hash='0'*64)['status'], 'stale_plan')

    def test_17_policy_version_change(self):
        changed=copy.deepcopy(self.policy)
        changed['policy_version']='new'
        self.assertEqual(self.check(policy=changed)['status'], 'policy_changed')

    def test_17b_policy_change_without_version_bump_detected(self):
        changed=copy.deepcopy(self.policy)
        changed['policy_notes'].append('additional rule')
        self.assertEqual(self.check(policy=changed)['status'], 'policy_changed')

    def test_18_policy_writes_true_rejected(self):
        changed=copy.deepcopy(self.policy)
        changed['writes_enabled']=True
        with self.assertRaises(ValueError):
            self.check(policy=changed)

    def test_19_request_digest_tamper_rejected(self):
        changed=copy.deepcopy(self.eligible)
        changed['field']='email'
        with self.assertRaises(GateError):
            self.check(request=changed)

    def test_20_request_fake_write_permission_rejected(self):
        changed=copy.deepcopy(self.eligible)
        changed['write_authorized']=True
        changed['request_sha256']=canonical_sha256({k:v for k,v in changed.items() if k!='request_sha256'})
        with self.assertRaises(GateError):
            self.check(request=changed)

    def test_21_nonindependent_actor_rejected(self):
        with self.assertRaises(GateError):
            self.check(decision=self.decide(reviewed_by='fixture.proposer'))

    def test_22_unknown_approval_binding_rejected(self):
        with self.assertRaises(GateError):
            self.check(decision=self.decide(request_sha256='0'*64))

    def test_23_approval_expired(self):
        d=self.decide(expires_at=(self.now-timedelta(seconds=1)).isoformat())
        self.assertEqual(self.check(decision=d)['status'],'expired_demo_decision')

    def test_24_future_approval_rejected(self):
        d=self.decide(reviewed_at=(self.now+timedelta(minutes=1)).isoformat())
        with self.assertRaises(GateError):
            self.check(decision=d)

    def test_25_overlong_approval_window_rejected(self):
        d=self.decide(expires_at=(self.now+timedelta(days=5)).isoformat())
        with self.assertRaises(GateError):
            self.check(decision=d)

    def test_26_notes_email_url_rejected(self):
        for note in ('Please contact me@example.org ASAP', 'Please refer to https://example.org'):
            with self.subTest(note=note), self.assertRaises(GateError):
                self.check(decision=self.decide(reason=note))

    def test_27_demo_reject_not_approval(self):
        self.assertEqual(self.check(decision=self.decide(decision='reject_demo'))['status'],'rejected_demo')

    def test_28_demo_request_changes_not_approval(self):
        self.assertEqual(self.check(decision=self.decide(decision='request_changes_demo'))['status'],'changes_requested_demo')

    def test_29_invalid_demo_extra_fields(self):
        with self.assertRaises(GateError):
            self.check(decision=self.decide(crm_write_authorized=True))

    def test_30_bad_digest_gate_plan_fails_closed(self):
        changed=copy.deepcopy(self.plan)
        changed['counts']['requests']=30
        with self.assertRaises(GateError):
            validate_fresh_source_gate(changed,self.folder,self.policy_path)

    def test_31_report_freshness_can_be_verified(self):
        self.assertEqual(validate_fresh_source_gate(self.plan,self.folder,self.policy_path),self.plan)

    def test_32_full_source_gates_and_counts(self):
        result=evaluate_current_plan(self.folder,self.policy_path,report=self.plan)
        self.assertEqual(result['counts'],{'awaiting_independent_approval':22,'held_duplicate_dependency':9})
        self.assertEqual(result['crm_writes'],0)

    def test_33_modified_fixture_fails_fresh_gate(self):
        with tempfile.TemporaryDirectory() as temp:
            target=Path(temp)
            for src in self.folder.iterdir():
                if src.is_file():
                    (target/src.name).write_bytes(src.read_bytes())
            companies=target/'companies.csv'
            raw=companies.read_text(encoding='utf-8')
            self.assertIn('United States',raw)
            companies.write_text(raw.replace('United States','US',1),encoding='utf-8')
            with self.assertRaises(GateError):
                validate_fresh_source_gate(self.plan,target,self.policy_path)

    def test_34_no_network_db_credential_imports(self):
        code='\n'.join((ROOT/name).read_text(encoding='utf-8') for name in
                       ['src/crm_quality/approval_preflight.py','scripts/m4b_approval_preflight.py'])
        for forbidden in ('import requests', 'import psycopg', 'urlopen(', 'HTTP PATCH', 'hubspot_api', 'AIRTABLE_REVIEW_PAT', 'PGPASSWORD'):
            self.assertNotIn(forbidden,code)


if __name__ == '__main__':
    unittest.main()
