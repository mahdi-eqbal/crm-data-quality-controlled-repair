"""M4a offline synthetic-only and no-write contract tests."""
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from crm_quality.repair_planning import (  # noqa: E402
    FROM_COUNTRY, TO_COUNTRY, RepairPlanError, canonical_sha256,
    propose_country_repairs, simulate_reviewable, build_country_plan,
)
from crm_quality.review_queue import build_plan, validate_fixture, synthetic_fingerprint  # noqa: E402


class TestM4aCountryNormalization(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = ROOT / 'fixtures' / 'synthetic'
        _, cls.companies, cls.associations = validate_fixture(cls.folder)
        cls.review_plan = build_plan(cls.folder)
        cls.policy = json.loads((ROOT / 'config' / 'quality_policy.json').read_text(encoding='utf-8'))
        cls.report = propose_country_repairs(cls.companies, cls.associations, cls.review_plan, cls.policy)

    def test_expected_fixture_counts(self):
        self.assertEqual(self.report['counts']['companies_scanned'], 120)
        self.assertEqual(self.report['counts']['candidate_pairs_checked'], 57)

    def test_country_opportunities(self):
        self.assertEqual(self.report['counts']['country_normalization_opportunities'], 31)
        self.assertEqual(self.report['counts']['not_applicable'], 89)

    def test_duplicate_dependency_holds(self):
        self.assertEqual(self.report['counts']['held_duplicate_dependency'], 9)
        self.assertEqual(self.report['counts']['reviewable_dry_run'], 22)
        for p in self.report['proposals']:
            if p['dependency_candidate_keys']:
                self.assertEqual(p['status'], 'held_duplicate_dependency')
            else:
                self.assertEqual(p['status'], 'reviewable_dry_run')

    def test_all_proposals_reversible_country_only(self):
        for p in self.report['proposals']:
            self.assertEqual((p['object_type'], p['field'], p['old_value'], p['proposed_value']),
                             ('company', 'country', FROM_COUNTRY, TO_COUNTRY))
            self.assertEqual(p['rollback_value'], FROM_COUNTRY)
            self.assertEqual(p['source_type'], 'synthetic_fixture_only')

    def test_no_crm_write_or_merge_authorized(self):
        self.assertTrue(all(p['write_authorized'] is False and p['merge_authorized'] is False
                            for p in self.report['proposals']))
        self.assertTrue(all(v == 0 for v in self.report['guarantees'].values()))

    def test_ids_are_unique_and_stable(self):
        values = [p['proposal_id'] for p in self.report['proposals']]
        self.assertEqual(len(values), len(set(values)))
        second = propose_country_repairs(self.companies, self.associations, self.review_plan, self.policy)
        self.assertEqual(self.report, second)

    def test_no_customer_personal_info_in_proposals(self):
        dump = json.dumps(self.report['proposals']).lower()
        for forbidden in ['@', 'phone', 'email', 'first_name', 'last_name', 'amber consulting', '.example']:
            self.assertNotIn(forbidden, dump)

    def test_source_rows_not_changed_by_simulation(self):
        before = copy.deepcopy(self.companies)
        rels = copy.deepcopy(self.associations)
        simulation = simulate_reviewable(self.companies, self.associations, self.report)
        self.assertEqual(self.companies, before)
        self.assertEqual(self.associations, rels)
        self.assertEqual(simulation['simulated_country_changes'], 22)
        self.assertTrue(simulation['simulated_rollback_exact'])
        self.assertTrue(simulation['associations_unchanged'])

    def test_country_remapping_does_not_modify_held_rows(self):
        copy_rows = copy.deepcopy(self.companies)
        for p in self.report['proposals']:
            if p['status'] == 'held_duplicate_dependency':
                original = next(r for r in copy_rows if r['record_id'] == p['source_record_id'])
                self.assertEqual(original['country'], FROM_COUNTRY)

    def test_policy_writes_true_fail_closed(self):
        changed = copy.deepcopy(self.policy)
        changed['writes_enabled'] = True
        with self.assertRaises(RepairPlanError):
            propose_country_repairs(self.companies, self.associations, self.review_plan, changed)

    def test_policy_merge_true_fail_closed(self):
        changed = copy.deepcopy(self.policy)
        changed['automatic_merges_enabled'] = True
        with self.assertRaises(RepairPlanError):
            propose_country_repairs(self.companies, self.associations, self.review_plan, changed)

    def test_policy_country_not_allowlisted_fail_closed(self):
        changed = copy.deepcopy(self.policy)
        changed['allowlisted_patch_fields_future_only']['company'].remove('country')
        with self.assertRaises(RepairPlanError):
            propose_country_repairs(self.companies, self.associations, self.review_plan, changed)

    def test_protected_country_fail_closed(self):
        changed = copy.deepcopy(self.policy)
        changed['protected_fields'].append('country')
        with self.assertRaises(RepairPlanError):
            propose_country_repairs(self.companies, self.associations, self.review_plan, changed)

    def test_unexpected_country_value_fail_closed(self):
        changed = copy.deepcopy(self.companies)
        changed[0]['country'] = 'USA'
        with self.assertRaises(RepairPlanError):
            propose_country_repairs(changed, self.associations, self.review_plan, self.policy)

    def test_duplicate_company_id_fail_closed(self):
        changed = copy.deepcopy(self.companies)
        changed[0]['record_id'] = changed[1]['record_id']
        with self.assertRaises(RepairPlanError):
            propose_country_repairs(changed, self.associations, self.review_plan, self.policy)

    def test_stale_record_hash_fail_closed(self):
        changed = copy.deepcopy(self.companies)
        index = next(i for i, row in enumerate(changed)
                     if row['record_id'] == self.report['proposals'][0]['source_record_id'])
        changed[index]['industry'] = 'Changed offline'
        with self.assertRaises(RepairPlanError):
            simulate_reviewable(changed, self.associations, self.report)

    def test_malicious_non_country_field_fail_closed(self):
        changed = copy.deepcopy(self.report)
        changed['proposals'][0]['field'] = 'email'
        with self.assertRaises(RepairPlanError):
            simulate_reviewable(self.companies, self.associations, changed)

    def test_blocked_candidate_cannot_be_falsely_reviewable(self):
        changed = copy.deepcopy(self.report)
        row = next(p for p in changed['proposals'] if p['status'] == 'held_duplicate_dependency')
        row['status'] = 'reviewable_dry_run'
        with self.assertRaises(RepairPlanError):
            simulate_reviewable(self.companies, self.associations, changed)

    def test_write_authorization_tampering_rejected(self):
        changed = copy.deepcopy(self.report)
        changed['proposals'][0]['write_authorized'] = True
        with self.assertRaises(RepairPlanError):
            simulate_reviewable(self.companies, self.associations, changed)

    def test_duplicate_proposal_rejected(self):
        changed = copy.deepcopy(self.report)
        changed['proposals'].append(changed['proposals'][0])
        with self.assertRaises(RepairPlanError):
            simulate_reviewable(self.companies, self.associations, changed)

    def test_fixture_source_hash_unchanged(self):
        before = synthetic_fingerprint(self.folder)
        report = build_country_plan(self.folder, ROOT / 'config' / 'quality_policy.json')
        self.assertEqual(before, synthetic_fingerprint(self.folder))
        self.assertEqual(report['source_fingerprint'], before)
        self.assertEqual(report['simulation']['simulated_country_changes'], 22)

    def test_final_report_stable_hash(self):
        report = build_country_plan(self.folder, ROOT / 'config' / 'quality_policy.json')
        actual = report.pop('plan_sha256')
        self.assertEqual(actual, canonical_sha256(report))

    def test_script_no_network_or_credential_imports(self):
        files = [ROOT/'src/crm_quality/repair_planning.py', ROOT/'scripts/m4a_plan_repairs.py']
        code = '\n'.join(f.read_text(encoding='utf-8') for f in files)
        for forbidden in ('import requests', 'import psycopg', 'urlopen(', 'hubspot_client', 'airtable_token', 'HTTP PATCH', 'PATCH /'):
            self.assertNotIn(forbidden, code)


if __name__ == '__main__':
    unittest.main()
