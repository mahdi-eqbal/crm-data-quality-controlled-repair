"""M4b synthetic-only approval-request planning and read-only preflight simulation.

This is NOT an approval authority, CRM preflight, or execution engine. All
actor identifiers in demo decisions are self-asserted. No external I/O here.
"""
from __future__ import annotations

import json
import re
import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from crm_quality.repair_planning import (
    FROM_COUNTRY, TO_COUNTRY, RepairPlanError, build_country_plan,
    canonical_sha256, validate_policy,
)
from crm_quality.review_queue import validate_fixture

VERSION = 'm4b-approval-preflight-design-v1'
NAMESPACE = uuid.UUID('70e5b29a-32f2-47b6-b870-48960856c3b8')
SOURCE = 'synthetic_fixture_only'
REQUEST_STATES = {'awaiting_independent_approval', 'held_duplicate_dependency'}
DEMO_KIND = 'synthetic_in_memory_demo_only'
MAX_DEMO_HOURS = 48
ALLOWED_DEMO_DECISIONS = {'approve_demo_preflight', 'reject_demo', 'request_changes_demo'}


class GateError(ValueError):
    """Refuse unsafe or untrusted requests without doing any writes."""


def _sha(value):
    return canonical_sha256(value)


def _assoc_payload(associations: list[dict], company_id: str) -> list[dict]:
    return sorted(
        (dict(contact_id=a['contact_id'], company_id=a['company_id'], association_type=a['association_type'])
         for a in associations if a['company_id'] == company_id),
        key=lambda a: (a['contact_id'], a['company_id'], a['association_type']),
    )


def _check_digest(obj: dict, key: str):
    if not isinstance(obj, dict) or not isinstance(obj.get(key), str):
        raise GateError('Missing plan/request digest')
    digest = obj[key]
    if not re.fullmatch(r'[a-f0-9]{64}', digest):
        raise GateError('Invalid digest format')
    material = {k: v for k, v in obj.items() if k != key}
    if digest != _sha(material):
        raise GateError('Plan/request content modified')


def build_approval_plan(fixtures_dir: Path, policy_path: Path) -> dict:
    """Derive requests from the complete M4a synthetic plan; grant NO approvals."""
    base = build_country_plan(fixtures_dir, policy_path)
    policy = json.loads(Path(policy_path).read_text(encoding='utf-8'))
    validate_policy(policy)
    policy_sha256 = _sha(policy)
    _check_digest(base, 'plan_sha256')
    _, companies, associations = validate_fixture(Path(fixtures_dir))
    lookup = {c['record_id']: c for c in companies}
    if len(lookup) != 120 or len(associations) != 268 or len(base['proposals']) != 31:
        raise GateError('Unexpected synthetic fixture or proposal counts')
    requests = []
    for p in sorted(base['proposals'], key=lambda x: x['source_record_id']):
        row = lookup.get(p['source_record_id'])
        if not row or _sha(row) != p['source_record_sha256']:
            raise GateError('M4a proposal/source mismatch')
        links = _assoc_payload(associations, p['source_record_id'])
        if len(links) != p['association_count']:
            raise GateError('Association count mismatch')
        status = 'held_duplicate_dependency' if p['status'] == 'held_duplicate_dependency' else 'awaiting_independent_approval'
        if status not in REQUEST_STATES:
            raise GateError('Unknown approval state')
        if status == 'held_duplicate_dependency' and not p['dependency_candidate_keys']:
            raise GateError('Missing duplicate hold evidence')
        if status == 'awaiting_independent_approval' and (p['dependency_candidate_keys'] or p['hold_reason']):
            raise GateError('Reviewable proposal retains duplicate dependencies')
        if (p['source_type'] != SOURCE or p['object_type'] != 'company' or p['field'] != 'country'
                or p['old_value'] != FROM_COUNTRY or p['proposed_value'] != TO_COUNTRY
                or p['write_authorized'] is not False or p['merge_authorized'] is not False):
            raise GateError('Unsafe scope/authorization in M4a proposal')
        request = {
            'request_id': str(uuid.uuid5(NAMESPACE, base['plan_sha256'] + ':' + p['proposal_id'])),
            'proposal_id': p['proposal_id'],
            'source_type': SOURCE,
            'source_record_id': p['source_record_id'],
            'object_type': 'company', 'field': 'country',
            'old_value': FROM_COUNTRY, 'proposed_value': TO_COUNTRY,
            'risk': p['risk'], 'status': status,
            'source_record_sha256': p['source_record_sha256'],
            'source_modified_at': row['updated_at'],
            'associations_sha256': _sha(links), 'association_count': len(links),
            'dependency_candidate_keys': p['dependency_candidate_keys'],
            'rollback_value': p['rollback_value'],
            'source_plan_sha256': base['plan_sha256'],
            'source_fingerprint': base['source_fingerprint'],
            'policy_version': base['policy_version'], 'policy_sha256': policy_sha256,
            'requires_separate_authorized_reviewer': True,
            'requires_fresh_hubspot_read_before_any_future_write': True,
            'approval_recorded': False, 'write_authorized': False, 'merge_authorized': False,
        }
        request['request_sha256'] = _sha(request)
        requests.append(request)
    states = Counter(x['status'] for x in requests)
    if len(requests) != 31 or len({x['request_id'] for x in requests}) != 31 or states != {
        'awaiting_independent_approval': 22, 'held_duplicate_dependency': 9
    }:
        raise GateError('Approval request counts do not match M4a contract')
    result = {
        'schema_version': 'm4b-1', 'version': VERSION, 'source_type': SOURCE,
        'source_plan_sha256': base['plan_sha256'],
        'source_fingerprint': base['source_fingerprint'],
        'policy_version': base['policy_version'], 'policy_sha256': policy_sha256,
        'counts': {'requests': len(requests), 'awaiting_independent_approval': states['awaiting_independent_approval'],
                   'held_duplicate_dependency': states['held_duplicate_dependency'],
                   'actual_approvals': 0, 'crm_write_eligible': 0},
        'requests': requests,
        'non_goals': ['no_authenticated_approvals', 'no_live_hubspot_preflight',
                      'no_write_permission', 'no_automatic_merge', 'no_external_api_calls'],
        'guarantees': {'crm_writes': 0, 'airtable_writes': 0, 'postgres_writes': 0,
                       'merges': 0, 'approvals_granted': 0},
    }
    result['gate_plan_sha256'] = _sha(result)
    return result


def _instant(value: str) -> datetime:
    if not isinstance(value, str):
        raise GateError('Invalid demo timestamp')
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError as exc:
        raise GateError('Malformed demo timestamp') from exc
    if result.tzinfo is None:
        raise GateError('Demo timestamp has no time zone')
    return result.astimezone(timezone.utc)


def validate_demo_decision(payload: dict, request: dict, now: datetime) -> str:
    """Validate a SELF-ASSERTED demo decision; never authenticate or authorize writes."""
    required = {'kind', 'request_id', 'request_sha256', 'decision', 'proposed_by',
                'reviewed_by', 'reason', 'reviewed_at', 'expires_at'}
    if not isinstance(payload, dict) or set(payload) != required:
        raise GateError('Unexpected demo approval fields')
    if payload['kind'] != DEMO_KIND or payload['request_id'] != request['request_id'] or payload['request_sha256'] != request['request_sha256']:
        raise GateError('Demo decision is bound to a different request')
    if payload['decision'] not in ALLOWED_DEMO_DECISIONS:
        raise GateError('Unknown demo decision')
    p, r = payload['proposed_by'], payload['reviewed_by']
    if (not all(isinstance(x, str) and re.fullmatch(r'[a-zA-Z0-9_.:-]{4,64}', x) for x in (p, r))
            or p == r):
        raise GateError('Nonindependent or invalid claimed reviewer identity')
    note = payload['reason']
    if (not isinstance(note, str) or not 12 <= len(note.strip()) <= 300
            or '@' in note or re.search(r'(?i)https?://|[\r\n\t\x00-\x1f]', note)):
        raise GateError('Unsafe/missing demo rationale')
    start, expires = _instant(payload['reviewed_at']), _instant(payload['expires_at'])
    if not (timedelta(0) < expires - start <= timedelta(hours=MAX_DEMO_HOURS)):
        raise GateError('Invalid demo validity window')
    if now.tzinfo is None:
        raise GateError('Evaluation time must be timezone-aware')
    when = now.astimezone(timezone.utc)
    if when < start:
        raise GateError('Demo decision from the future')
    if when >= expires:
        return 'expired_demo_decision'
    if payload['decision'] == 'reject_demo':
        return 'rejected_demo'
    if payload['decision'] == 'request_changes_demo':
        return 'changes_requested_demo'
    return 'demo_only_preflight_eligible'


def preflight_request(request: dict, source_row: dict, associations: list[dict],
                      policy: dict, source_plan_sha256: str, *, demo_decision: dict | None = None,
                      now: datetime | None = None) -> dict:
    """Read-only synthetic preflight for a *trusted generated* M4b request.

    This cannot validate real HubSpot freshness or real reviewer authority.
    """
    _check_digest(request, 'request_sha256')
    validate_policy(policy)
    if request.get('source_type') != SOURCE or request.get('object_type') != 'company' or request.get('field') != 'country':
        raise GateError('Scope mismatch')
    if (request.get('write_authorized') is not False or request.get('merge_authorized') is not False
            or request.get('approval_recorded') is not False or request.get('requires_separate_authorized_reviewer') is not True
            or request.get('requires_fresh_hubspot_read_before_any_future_write') is not True):
        raise GateError('Unsafe authorization flags')
    if (request.get('old_value') != FROM_COUNTRY or request.get('proposed_value') != TO_COUNTRY
            or request.get('rollback_value') != FROM_COUNTRY):
        raise GateError('Unexpected field normalization')
    if request.get('source_plan_sha256') != source_plan_sha256:
        return _result(request, 'stale_plan')
    if (request.get('policy_version') != policy['policy_version'] or
            request.get('policy_sha256') != _sha(policy)):
        return _result(request, 'policy_changed')
    if source_row is None or source_row.get('record_id') != request['source_record_id']:
        return _result(request, 'missing_source_record')
    if _sha(source_row) != request['source_record_sha256'] or source_row['country'] != FROM_COUNTRY or source_row['updated_at'] != request['source_modified_at']:
        return _result(request, 'stale_source_record')
    links = _assoc_payload(associations, request['source_record_id'])
    if len(links) != request['association_count'] or _sha(links) != request['associations_sha256']:
        return _result(request, 'association_changed')
    if request['status'] == 'held_duplicate_dependency':
        if not request['dependency_candidate_keys']:
            raise GateError('Duplicate dependency hold was tampered')
        return _result(request, 'held_duplicate_dependency')
    if request['status'] != 'awaiting_independent_approval' or request['dependency_candidate_keys']:
        raise GateError('Unexpected approval-routing status')
    if demo_decision is None:
        return _result(request, 'awaiting_independent_approval')
    decision_state = validate_demo_decision(demo_decision, request, now or datetime.now(timezone.utc))
    return _result(request, decision_state)


def _result(request: dict, status: str) -> dict:
    # The success status is deliberately not a CRM authorization.
    return {
        'request_id': request['request_id'], 'proposal_id': request['proposal_id'],
        'status': status, 'crm_write_authorized': False, 'merge_authorized': False,
        'real_hubspot_preflight_performed': False, 'authenticated_approval_verified': False,
    }


def validate_fresh_source_gate(plan: dict, fixtures_dir: Path, policy_path: Path) -> dict:
    """Whole-batch verification before any per-record check; immutable M4a anchor."""
    _check_digest(plan, 'gate_plan_sha256')
    current = build_approval_plan(fixtures_dir, policy_path)
    if current != plan:
        raise GateError('M4b plan differs from freshly rebuilt M4a source')
    return current


def evaluate_current_plan(fixtures_dir: Path, policy_path: Path, *, report: dict | None = None) -> dict:
    """Read fixture/policy, validate plan, evaluate all requests with NO demo approvals."""
    current = build_approval_plan(fixtures_dir, policy_path)
    if report is not None:
        validate_fresh_source_gate(report, fixtures_dir, policy_path)
    _, companies, associations = validate_fixture(Path(fixtures_dir))
    policy = json.loads(Path(policy_path).read_text(encoding='utf-8'))
    lookup = {x['record_id']: x for x in companies}
    results = [preflight_request(req, lookup.get(req['source_record_id']), associations, policy,
                                 current['source_plan_sha256']) for req in current['requests']]
    counts = dict(sorted(Counter(x['status'] for x in results).items()))
    if counts != {'awaiting_independent_approval': 22, 'held_duplicate_dependency': 9}:
        raise GateError('Unexpected preflight statuses')
    return {
        'gate_plan_sha256': current['gate_plan_sha256'],
        'source_plan_sha256': current['source_plan_sha256'],
        'counts': counts, 'results': results,
        'crm_writes': 0, 'approvals_granted': 0, 'postgres_writes': 0,
        'airtable_writes': 0, 'merges': 0,
    }
