"""M4a synthetic-only controlled repair planning. Absolutely no CRM/DB/API writes.

Only propose reversible country normalization on *synthetic company fixtures*.
Company IDs involved in any duplicate-review pair are placed on hold, even
when a reviewer has classified the pair. A review decision is NOT authorization.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from collections import Counter, defaultdict
from copy import deepcopy
from pathlib import Path

from crm_quality.profiling import load_csv
from crm_quality.review_queue import build_plan, synthetic_fingerprint, validate_fixture

VERSION = 'm4a-company-country-us-v1'
SOURCE = 'synthetic_fixture_only'
NAMESPACE = uuid.UUID('1f53e671-c8d4-4c34-a5b5-9130fb63c9a1')
EXPECTED_COMPANIES = 120
EXPECTED_ASSOCIATIONS = 268
CANDIDATE_TOTAL = 57
FROM_COUNTRY = 'United States'
TO_COUNTRY = 'US'
COMPANY_FIELDS = ('record_id', 'name', 'domain', 'country', 'industry', 'updated_at')


class RepairPlanError(ValueError):
    """Invalid policy, source, or attempted repair. Fail closed."""


def canonical_sha256(value: object) -> str:
    data = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(data.encode('utf-8')).hexdigest()


def validate_policy(policy: dict) -> str:
    """Read the existing project policy, never silently enable an unsafe mode."""
    if not isinstance(policy, dict) or policy.get('writes_enabled') is not False:
        raise RepairPlanError('CRM writes must remain disabled')
    if policy.get('automatic_merges_enabled') is not False:
        raise RepairPlanError('Automatic merges must remain disabled')
    if policy.get('human_approval_required_for_all_writes') is not True:
        raise RepairPlanError('Human approval policy missing')
    if 'country' not in policy.get('allowlisted_patch_fields_future_only', {}).get('company', []):
        raise RepairPlanError('Country is not on the FUTURE-only policy allowlist')
    if 'country' in policy.get('protected_fields', []):
        raise RepairPlanError('Country is a protected field')
    if not isinstance(policy.get('policy_version'), str) or not policy['policy_version']:
        raise RepairPlanError('Policy version missing')
    return policy['policy_version']


def _validate_inputs(companies: list[dict], associations: list[dict], plan: dict) -> None:
    if len(companies) != EXPECTED_COMPANIES or len(associations) != EXPECTED_ASSOCIATIONS:
        raise RepairPlanError('Unexpected synthetic source count')
    if len(plan.get('rows', [])) != CANDIDATE_TOTAL or len({str(x['candidate_id']) for x in plan['rows']}) != CANDIDATE_TOTAL:
        raise RepairPlanError('Review queue does not match expected synthetic batch')
    ids = [x.get('record_id') for x in companies]
    if len(set(ids)) != EXPECTED_COMPANIES or not all(isinstance(i, str) and i.startswith('O') and len(i) == 5 and i[1:].isdigit() for i in ids):
        raise RepairPlanError('Duplicate or invalid company IDs')
    for row in companies:
        if set(row) != set(COMPANY_FIELDS) or row['country'] not in ('US', FROM_COUNTRY):
            raise RepairPlanError('Unexpected field or country value in synthetic company fixture')
    for a in associations:
        if set(a) != {'contact_id', 'company_id', 'association_type'}:
            raise RepairPlanError('Unexpected association schema')
    if not isinstance(plan.get('source_fingerprint'), str) or len(plan['source_fingerprint']) != 64:
        raise RepairPlanError('Source fingerprint missing')


def propose_country_repairs(companies: list[dict], associations: list[dict],
                            review_plan: dict, policy: dict) -> dict:
    """Pure deterministic proposal generation. No access to CRM, PG, Airtable, or network.

    Status `reviewable_dry_run` is *not* approval to write. Every candidate is
    explicitly denied write/merge rights, including reviewable ones.
    """
    policy_version = validate_policy(policy)
    _validate_inputs(companies, associations, review_plan)
    by_company: dict[str, set[str]] = defaultdict(set)
    for r in review_plan['rows']:
        if r['object_type'] == 'companies':
            if (r['record_id_1'] not in {c['record_id'] for c in companies} or
                    r['record_id_2'] not in {c['record_id'] for c in companies}):
                raise RepairPlanError('Matching candidate references unknown company')
            key = f'companies:{r["record_id_1"]}:{r["record_id_2"]}'
            by_company[r['record_id_1']].add(key)
            by_company[r['record_id_2']].add(key)
    association_counts = Counter(a['company_id'] for a in associations)
    proposals = []
    for company in sorted(companies, key=lambda x: x['record_id']):
        if company['country'] != FROM_COUNTRY:
            continue
        record_id = company['record_id']
        conflicts = sorted(by_company.get(record_id, set()))
        held = bool(conflicts)
        proposal_id = str(uuid.uuid5(NAMESPACE, ':'.join((review_plan['source_fingerprint'], VERSION, record_id, 'country', FROM_COUNTRY, TO_COUNTRY))))
        proposals.append({
            'proposal_id': proposal_id,
            'source_type': SOURCE,
            'source_record_id': record_id,
            'object_type': 'company',
            'field': 'country',
            'old_value': FROM_COUNTRY,
            'proposed_value': TO_COUNTRY,
            'reason_code': 'normalize_country_name_to_iso_alpha2',
            'risk': 'medium' if held else 'low',
            'status': 'held_duplicate_dependency' if held else 'reviewable_dry_run',
            'hold_reason': 'duplicate_review_dependency' if held else None,
            'dependency_candidate_keys': conflicts,
            'association_count': association_counts[record_id],
            'source_record_sha256': canonical_sha256(company),
            'rollback_value': FROM_COUNTRY,
            'write_authorized': False,
            'merge_authorized': False,
        })
    proposal_ids = [x['proposal_id'] for x in proposals]
    if len(set(proposal_ids)) != len(proposal_ids):
        raise RepairPlanError('Duplicate repair proposal ID')
    statuses = Counter(x['status'] for x in proposals)
    counts = {
        'companies_scanned': len(companies),
        'candidate_pairs_checked': len(review_plan['rows']),
        'country_normalization_opportunities': len(proposals),
        'reviewable_dry_run': statuses['reviewable_dry_run'],
        'held_duplicate_dependency': statuses['held_duplicate_dependency'],
        'not_applicable': len(companies) - len(proposals),
    }
    result = {
        'schema_version': 'm4a-1',
        'source_type': SOURCE,
        'rule_version': VERSION,
        'policy_version': policy_version,
        'source_fingerprint': review_plan['source_fingerprint'],
        'review_batch_id': str(review_plan['batch_id']),
        'counts': counts,
        'proposals': proposals,
        'guarantees': {
            'crm_writes': 0, 'postgres_writes': 0, 'airtable_writes': 0,
            'merges': 0, 'approvals_granted': 0,
            'protected_fields_changed': 0, 'associations_changed': 0,
        },
    }
    result['plan_sha256'] = canonical_sha256(result)
    return result


def simulate_reviewable(companies: list[dict], associations: list[dict], report: dict) -> dict:
    """Run reversible dry-run edits on IN-MEMORY copies only. Never write source CSVs.

    Independent validation: reject a modified proposal list, stale record hash,
    unexpected foreign IDs, unknown statuses, or requests to change other fields.
    """
    before = deepcopy(companies)
    after = deepcopy(companies)
    assoc_before = deepcopy(associations)
    lookup = {x['record_id']: x for x in after}
    seen = set()
    eligible = set()
    for item in report['proposals']:
        record_id = item['source_record_id']
        if record_id in seen or record_id not in lookup:
            raise RepairPlanError('Duplicate or unknown proposal source record')
        seen.add(record_id)
        row = lookup[record_id]
        if item.get('field') != 'country' or item.get('old_value') != FROM_COUNTRY or item.get('proposed_value') != TO_COUNTRY:
            raise RepairPlanError('Unexpected repair field or value')
        if item.get('write_authorized') is not False or item.get('merge_authorized') is not False:
            raise RepairPlanError('Unauthorized repair permissions')
        if canonical_sha256(row) != item['source_record_sha256'] or row['country'] != FROM_COUNTRY:
            raise RepairPlanError('Stale source record or modified proposal')
        if item['status'] == 'reviewable_dry_run':
            if item['dependency_candidate_keys'] or item['hold_reason'] is not None:
                raise RepairPlanError('Candidate with duplicate dependencies cannot be simulated as reviewable')
            eligible.add(record_id)
            row['country'] = TO_COUNTRY
        elif item['status'] == 'held_duplicate_dependency':
            if not item['dependency_candidate_keys'] or item['hold_reason'] != 'duplicate_review_dependency':
                raise RepairPlanError('Held candidate is missing duplicate dependency')
        else:
            raise RepairPlanError('Unexpected proposal status')
    # Simulate only the country field for eligible, and verify nothing else was touched.
    differences = 0
    for old, new in zip(before, after):
        if old['record_id'] != new['record_id']:
            raise RepairPlanError('Record identity changed')
        if old != new:
            if old['record_id'] not in eligible or {k for k in old if old[k] != new[k]} != {'country'}:
                raise RepairPlanError('Unexpected mutation during dry run')
            differences += 1
    if associations != assoc_before or differences != len(eligible):
        raise RepairPlanError('Simulation changed relationships or lost updates')
    for row in after:
        if row['record_id'] in eligible:
            row['country'] = FROM_COUNTRY
    if before != after:
        raise RepairPlanError('Rollback did not exactly restore pre-simulation record state')
    return {
        'simulated_country_changes': differences,
        'simulated_rollback_exact': True,
        'associations_unchanged': True,
        'original_company_rows_unchanged': companies == before,
        'source_files_written': 0,
    }


def build_country_plan(fixtures_dir: Path, policy_path: Path) -> dict:
    """Validate fixture + old policy; generate and simulate; return deterministic JSON."""
    folder = Path(fixtures_dir)
    policy = json.loads(Path(policy_path).read_text(encoding='utf-8'))
    # This validation requires original wholly-synthetic fixture contract.
    _, companies, associations = validate_fixture(folder)
    review_plan = build_plan(folder)
    original_hash = synthetic_fingerprint(folder)
    if review_plan['source_fingerprint'] != original_hash:
        raise RepairPlanError('Source fingerprint mismatch during planning')
    result = propose_country_repairs(companies, associations, review_plan, policy)
    result['simulation'] = simulate_reviewable(companies, associations, result)
    if synthetic_fingerprint(folder) != original_hash:
        raise RepairPlanError('Fixture was modified during dry run')
    # Include simulation verification in final immutable report digest.
    result.pop('plan_sha256')
    result['plan_sha256'] = canonical_sha256(result)
    return result
