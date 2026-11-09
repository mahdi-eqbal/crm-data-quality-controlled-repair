"""M4c self-contained synthetic contract tests, no CRM, network or database calls.

The generated input is deliberately independent of M4a's ground-truth labels.
Additional whole-project acceptance happens when run in the existing repo.
"""
from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'scripts'))
from crm_quality.execution_simulation import (  # noqa: E402
    DEMO_TIME, MemoryExecutor, SimulationError, build_context, demo_decision,
    execution_plan, execute_demo_batch, run_demo_scenarios,
)
from crm_quality.repair_planning import canonical_sha256  # noqa: E402
from crm_quality.approval_preflight import GateError  # noqa: E402
from m4c_simulate_execution import main, write_report  # noqa: E402


def context_fixture():
    """Construct the precise 120/268/31/22/9 synthetic M4b-shaped contract."""
    companies = [dict(record_id=f'O{i:04d}', name=f'Synthetic Business {i}',
                      domain=f'fiction-{i}.example',
                      country='United States' if i <= 31 else 'US',
                      industry='Research', updated_at='2026-10-20T00:00:00Z')
                 for i in range(1, 121)]
    associations = [dict(contact_id=f'C{(i % 300)+1:04d}',
                         company_id=f'O{(i % 120)+1:04d}', association_type='secondary')
                    for i in range(268)]
    policy = {'policy_version': 'm1a-0.2.0', 'writes_enabled': False,
              'automatic_merges_enabled': False,
              'human_approval_required_for_all_writes': True,
              'allowlisted_patch_fields_future_only': {'company': ['country']},
              'protected_fields': ['associations', 'email']}
    policy_hash = canonical_sha256(policy)
    requests = []
    for i in range(1, 32):
        row = companies[i-1]
        linked = sorted((dict(a) for a in associations if a['company_id'] == row['record_id']),
                        key=lambda a: (a['contact_id'], a['company_id'], a['association_type']))
        held = i > 22
        req = {
            'request_id': f'00000000-0000-5000-8000-{i:012d}',
            'proposal_id': f'00000000-0000-5000-9000-{i:012d}',
            'source_type': 'synthetic_fixture_only',
            'source_record_id': row['record_id'], 'object_type': 'company',
            'field': 'country', 'old_value': 'United States', 'proposed_value': 'US',
            'risk': 'medium' if held else 'low',
            'status': 'held_duplicate_dependency' if held else 'awaiting_independent_approval',
            'source_record_sha256': canonical_sha256(row),
            'source_modified_at': row['updated_at'],
            'associations_sha256': canonical_sha256(linked),
            'association_count': len(linked),
            'dependency_candidate_keys': ['companies:O0001:O0002'] if held else [],
            'rollback_value': 'United States',
            'source_plan_sha256': 'a'*64,
            'source_fingerprint': 'b'*64,
            'policy_version': policy['policy_version'], 'policy_sha256': policy_hash,
            'requires_separate_authorized_reviewer': True,
            'requires_fresh_hubspot_read_before_any_future_write': True,
            'approval_recorded': False, 'write_authorized': False, 'merge_authorized': False,
        }
        req['request_sha256'] = canonical_sha256(req)
        requests.append(req)
    plan = {
        'schema_version': 'm4b-1', 'source_type': 'synthetic_fixture_only',
        'source_plan_sha256': 'a'*64, 'source_fingerprint': 'b'*64,
        'counts': {'requests': 31, 'awaiting_independent_approval': 22,
                   'held_duplicate_dependency': 9, 'actual_approvals': 0,
                   'crm_write_eligible': 0},
        'requests': requests,
    }
    plan['gate_plan_sha256'] = canonical_sha256(plan)
    return {'approval_plan': plan, 'companies': companies, 'associations': associations,
            'policy': policy, 'fixtures_dir': ROOT / 'fixtures' / 'synthetic',
            'policy_path': ROOT / 'config' / 'quality_policy.json'}


class TestM4cSimulation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = context_fixture()
        cls.req = cls.ctx['approval_plan']['requests'][0]
        cls.held = cls.ctx['approval_plan']['requests'][-1]
        cls.now = DEMO_TIME + timedelta(minutes=1)

    def setUp(self):
        self.work = MemoryExecutor(self.ctx)
        self.decision = demo_decision(self.req)

    def test_01_execution_plan_exact_counts(self):
        self.assertEqual(execution_plan(self.ctx)['counts']['mock_gate_required'], 22)

    def test_02_held_requests_still_held(self):
        self.assertEqual(execution_plan(self.ctx)['counts']['held_duplicate_dependency'], 9)

    def test_03_no_authorized_writes_or_merges(self):
        rows = execution_plan(self.ctx)['operations']
        self.assertTrue(all(x['write_authorized'] is False and x['merge_authorized'] is False for x in rows))

    def test_04_plan_determinism(self):
        self.assertEqual(execution_plan(self.ctx), execution_plan(copy.deepcopy(self.ctx)))

    def test_05_plan_digest_detects_mutation(self):
        context = copy.deepcopy(self.ctx)
        context['approval_plan']['requests'][0]['field'] = 'email'
        with self.assertRaises((SimulationError, GateError)):
            execution_plan(context)

    def test_06_protect_email_field(self):
        context = copy.deepcopy(self.ctx)
        req = context['approval_plan']['requests'][0]
        req['field'] = 'email'
        req['request_sha256'] = canonical_sha256({k:v for k,v in req.items() if k!='request_sha256'})
        context['approval_plan']['gate_plan_sha256'] = canonical_sha256({k:v for k,v in context['approval_plan'].items() if k!='gate_plan_sha256'})
        with self.assertRaises((SimulationError, GateError)):
            execution_plan(context)

    def test_07_no_request_can_claim_authorization(self):
        context = copy.deepcopy(self.ctx)
        context['approval_plan']['requests'][0]['write_authorized'] = True
        with self.assertRaises((SimulationError, GateError)):
            execution_plan(context)

    def test_08_valid_mock_attempt(self):
        result = self.work.run(self.req, self.decision, attempt_id='synthetic-attempt:8', now=self.now)
        self.assertEqual(result['status'], 'simulated_verified')
        self.assertEqual(self.work.records[self.req['source_record_id']]['country'], 'US')

    def test_09_mock_approval_is_not_real_approval(self):
        self.assertEqual(self.decision['kind'], 'synthetic_in_memory_demo_only')
        self.assertFalse(self.work.plan['counts']['actual_approvals'])

    def test_10_idempotent_exact_replay(self):
        args = dict(attempt_id='synthetic-attempt:10', now=self.now)
        self.work.run(self.req, self.decision, **args)
        self.assertEqual(self.work.run(self.req, self.decision, **args)['status'], 'idempotent_replay')
        self.assertEqual(sum(e['action']=='simulated_country_change' for e in self.work.journal), 1)

    def test_11_same_id_changed_payload_fails(self):
        self.work.run(self.req, self.decision, attempt_id='synthetic-attempt:11', now=self.now)
        decision = dict(self.decision, reason='Different synthetic reason for negative test.')
        with self.assertRaises(SimulationError):
            self.work.run(self.req, decision, attempt_id='synthetic-attempt:11', now=self.now)

    def test_12_invalid_attempt_id_fails(self):
        with self.assertRaises(SimulationError):
            self.work.run(self.req, self.decision, attempt_id='real-write-id', now=self.now)

    def test_13_cannot_execute_held_request(self):
        with self.assertRaises(SimulationError):
            self.work.run(self.held, demo_decision(self.held), attempt_id='synthetic-attempt:13', now=self.now)

    def test_14_stale_after_preflight_blocked(self):
        result = self.work.run(self.req, self.decision, attempt_id='synthetic-attempt:14', now=self.now,
                               before_write=lambda row: row.__setitem__('industry','concurrent-drift'))
        self.assertEqual(result['status'], 'blocked_stale')
        self.assertEqual(self.work.records[self.req['source_record_id']]['country'], 'United States')

    def test_15_stale_source_before_preflight_blocked(self):
        self.work.records[self.req['source_record_id']]['industry'] = 'drift'
        result = self.work.run(self.req, self.decision, attempt_id='synthetic-attempt:15', now=self.now)
        self.assertEqual(result['status'], 'blocked_preflight')

    def test_16_non_independent_demo_review_blocked(self):
        decision = dict(self.decision, reviewed_by='synthetic.proposer')
        result = self.work.run(self.req, decision, attempt_id='synthetic-attempt:16', now=self.now)
        self.assertEqual(result['status'], 'blocked_preflight')

    def test_17_expired_mock_decision_blocked(self):
        result = self.work.run(self.req, self.decision, attempt_id='synthetic-attempt:17',
                               now=DEMO_TIME+timedelta(hours=2))
        self.assertEqual(result['status'], 'blocked_preflight')

    def test_18_mock_rejection_not_approved(self):
        decision = dict(self.decision, decision='reject_demo')
        result = self.work.run(self.req, decision, attempt_id='synthetic-attempt:18', now=self.now)
        self.assertEqual(result['status'], 'blocked_preflight')

    def test_19_mock_change_request_not_approved(self):
        decision = dict(self.decision, decision='request_changes_demo')
        result = self.work.run(self.req, decision, attempt_id='synthetic-attempt:19', now=self.now)
        self.assertEqual(result['status'], 'blocked_preflight')

    def test_20_unchanged_original_list(self):
        before = copy.deepcopy(self.ctx['companies'])
        self.work.run(self.req, self.decision, attempt_id='synthetic-attempt:20', now=self.now)
        self.assertEqual(before, self.ctx['companies'])

    def test_21_exact_compensation(self):
        self.work.run(self.req, self.decision, attempt_id='synthetic-attempt:21', now=self.now)
        self.assertEqual(self.work.compensate(self.req, attempt_id='synthetic-attempt:21'), 'compensated')
        self.assertTrue(self.work.unchanged_source())

    def test_22_compensation_replay(self):
        self.work.run(self.req, self.decision, attempt_id='synthetic-attempt:22', now=self.now)
        self.work.compensate(self.req, attempt_id='synthetic-attempt:22')
        self.assertEqual(self.work.compensate(self.req, attempt_id='synthetic-attempt:22'), 'compensated')

    def test_23_compensation_conflict_requires_manual(self):
        self.work.run(self.req, self.decision, attempt_id='synthetic-attempt:23', now=self.now)
        self.work.records[self.req['source_record_id']]['industry'] = 'other-writer'
        self.assertEqual(self.work.compensate(self.req, attempt_id='synthetic-attempt:23'), 'compensation_conflict')
        self.assertEqual(self.work.records[self.req['source_record_id']]['industry'], 'other-writer')

    def test_24_unknown_compensation_fails(self):
        with self.assertRaises(SimulationError):
            self.work.compensate(self.req, attempt_id='synthetic-attempt:missing')

    def test_25_unapproved_compensation_fails(self):
        self.work.run(self.req, {'garbage':'decision'}, attempt_id='synthetic-attempt:25', now=self.now)
        with self.assertRaises(SimulationError):
            self.work.compensate(self.req, attempt_id='synthetic-attempt:25')

    def test_26_injected_postcheck_drift_never_blindly_restored(self):
        result = self.work.run(self.req, self.decision, attempt_id='synthetic-attempt:26',
                               now=self.now, inject_verify_failure=True)
        self.assertEqual(result['status'], 'manual_reconciliation_required')
        self.assertNotEqual(self.work.records[self.req['source_record_id']]['industry'], 'Research')

    def test_27_association_drift_fails_closed(self):
        self.work.associations.append(dict(contact_id='C9999', company_id='O0001', association_type='x'))
        result = self.work.run(self.req, self.decision, attempt_id='synthetic-attempt:27', now=self.now)
        self.assertEqual(result['status'], 'blocked_preflight')

    def test_28_policy_drift_fails_closed(self):
        self.work.policy['writes_enabled'] = True
        result = self.work.run(self.req, self.decision, attempt_id='synthetic-attempt:28', now=self.now)
        self.assertEqual(result['status'], 'blocked_preflight')

    def test_29_all_demo_scenarios(self):
        s = run_demo_scenarios(self.ctx)
        self.assertEqual(s['scenarios']['partial_changes_compensated'], 2)
        self.assertEqual(s['scenarios']['rollback_conflict_detected'], 1)
        self.assertEqual(s['crm_writes'], 0)

    def test_30_report_is_local_and_path_guarded(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch('m4c_simulate_execution.ROOT', Path(tmp)):
                safe = Path(tmp) / 'private_exports' / 'm4c' / 'execution_simulation.json'
                write_report({'source_type':'synthetic_fixture_only'}, safe)
                self.assertTrue(safe.exists())
                with self.assertRaises(SimulationError):
                    write_report({}, Path(tmp) / 'evidence' / 'unsafe.json')

    def test_31_check_cli_no_untested_authorization(self):
        with patch('m4c_simulate_execution.build_context', return_value=self.ctx):
            self.assertEqual(main(['--check']), 0)

    def test_32_demo_cli(self):
        with patch('m4c_simulate_execution.build_context', return_value=self.ctx):
            self.assertEqual(main(['--demo']), 0)

    def test_33_request_hash_tamper_fails(self):
        tampered = dict(self.req, source_record_id='O0119')
        with self.assertRaises(SimulationError):
            self.work.run(tampered, self.decision, attempt_id='synthetic-attempt:33', now=self.now)

    def test_34_no_network_database_credential_imports(self):
        path = ROOT / 'src' / 'crm_quality' / 'execution_simulation.py'
        source = path.read_text(encoding='utf-8')
        for disallowed in ('import requests', 'import psycopg', 'urlopen', 'HUBSPOT_SERVICE_KEY', 'AIRTABLE_REVIEW_PAT', 'PATCH ', 'DELETE '):
            self.assertNotIn(disallowed, source)

    def test_35_replay_compensated_attempt_must_not_reapply(self):
        attempt='synthetic-attempt:35'
        self.work.run(self.req,self.decision,attempt_id=attempt,now=self.now)
        self.work.compensate(self.req,attempt_id=attempt)
        again=self.work.run(self.req,self.decision,attempt_id=attempt,now=self.now)
        self.assertEqual(again['status'],'idempotent_replay')
        self.assertTrue(self.work.unchanged_source())

    def test_36_batch_fully_simulated_in_memory(self):
        result=execute_demo_batch(self.ctx,self.ctx['approval_plan']['requests'][:3],now=self.now)
        self.assertEqual(result['status'],'fully_simulated')
        self.assertEqual(result['simulated_changes'],3)
        self.assertEqual(result['external_writes'],0)

    def test_37_partial_failure_compensates_all(self):
        r=execute_demo_batch(self.ctx,self.ctx['approval_plan']['requests'][:3],now=self.now,inject_failure_after=2)
        self.assertEqual((r['status'],r['compensated'],r['manual_attention']),('compensated_after_failure',2,0))

    def test_38_partial_failure_compensation_conflict(self):
        r=execute_demo_batch(self.ctx,self.ctx['approval_plan']['requests'][:3],now=self.now,
                             inject_failure_after=2,inject_compensation_conflict=True)
        self.assertEqual((r['status'],r['compensated'],r['manual_attention']),('manual_reconciliation_required',1,1))

    def test_39_duplicate_in_batch_fails_closed(self):
        with self.assertRaises(SimulationError):
            execute_demo_batch(self.ctx,[self.req,self.req],now=self.now)

    def test_40_held_in_batch_fails_before_mutation(self):
        with self.assertRaises(SimulationError):
            execute_demo_batch(self.ctx,[self.req,self.held],now=self.now)

    def test_41_bad_batch_injection_fails(self):
        with self.assertRaises(SimulationError):
            execute_demo_batch(self.ctx,[self.req],now=self.now,inject_failure_after=2)

    def test_42_journal_is_ordered_and_contains_no_personal_data(self):
        r=execute_demo_batch(self.ctx,self.ctx['approval_plan']['requests'][:3],now=self.now,inject_failure_after=2)
        self.assertEqual([x['sequence'] for x in r['journal']],list(range(1,len(r['journal'])+1)))
        self.assertTrue(all('email' not in json.dumps(x).lower() for x in r['journal']))


if __name__ == '__main__':
    unittest.main()
