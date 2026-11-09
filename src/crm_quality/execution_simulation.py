"""M4c — synthetic-only, in-memory execution / verification / compensation simulator.

Explicit non-goals: NO HubSpot/HTTP, Airtable, PostgreSQL, Make, external
approvals, persisted execution, CRM PATCH/MERGE or permission escalation.
A mock demo gate is not an authenticated approval or an execution authority.
"""
from __future__ import annotations

import copy
import json
import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from crm_quality.approval_preflight import (
    DEMO_KIND, GateError, _check_digest, build_approval_plan, preflight_request,
    validate_fresh_source_gate,
)
from crm_quality.repair_planning import (
    FROM_COUNTRY, TO_COUNTRY, canonical_sha256, validate_policy,
)
from crm_quality.review_queue import validate_fixture

VERSION = 'm4c-synthetic-inmemory-execution-v1'
SCOPE = 'synthetic_fixture_only'
DEMO_TIME = datetime(2026, 11, 9, 12, 0, tzinfo=timezone.utc)
ALLOWED_FIELDS = {'country'}


class SimulationError(GateError):
    """Fail-closed simulation error, never a CRM action."""


def _digest(value):
    return canonical_sha256(value)


def demo_decision(request: dict, *, reviewed_at: datetime = DEMO_TIME) -> dict:
    """Self-asserted identities for in-memory testing only."""
    return {
        'kind': DEMO_KIND,
        'request_id': request['request_id'],
        'request_sha256': request['request_sha256'],
        'decision': 'approve_demo_preflight',
        'proposed_by': 'synthetic.proposer',
        'reviewed_by': 'synthetic.second.reviewer',
        'reason': 'Offline synthetic simulation only; no real approval or CRM access.',
        'reviewed_at': reviewed_at.isoformat(),
        'expires_at': (reviewed_at + timedelta(hours=1)).isoformat(),
    }


def _associated(associations: list[dict], record_id: str) -> list[dict]:
    return sorted((dict(a) for a in associations if a['company_id'] == record_id),
                  key=lambda a: (a['contact_id'], a['company_id'], a['association_type']))


def build_context(fixtures_dir: Path, policy_path: Path) -> dict:
    """Regenerate M4b requests and validate original synthetic fixture + policy."""
    folder, policy_file = Path(fixtures_dir), Path(policy_path)
    approval_plan = build_approval_plan(folder, policy_file)
    validate_fresh_source_gate(approval_plan, folder, policy_file)
    _, companies, associations = validate_fixture(folder)
    policy = json.loads(policy_file.read_text(encoding='utf-8'))
    validate_policy(policy)
    if (len(companies) != 120 or len(associations) != 268 or
            len(approval_plan['requests']) != 31 or
            approval_plan['counts']['awaiting_independent_approval'] != 22 or
            approval_plan['counts']['held_duplicate_dependency'] != 9 or
            approval_plan['counts']['actual_approvals'] != 0 or
            approval_plan['counts']['crm_write_eligible'] != 0):
        raise SimulationError('Unexpected M4b synthetic plan')
    if any(r.get('approval_recorded') is not False or
           r.get('write_authorized') is not False or
           r.get('merge_authorized') is not False for r in approval_plan['requests']):
        raise SimulationError('M4b plan claims an unsafe authorization')
    if len({c['record_id'] for c in companies}) != 120:
        raise SimulationError('Unexpected company IDs')
    return {'approval_plan': approval_plan, 'companies': companies,
            'associations': associations, 'policy': policy,
            'fixtures_dir': folder, 'policy_path': policy_file}


def execution_plan(context: dict) -> dict:
    """Only a plan for *mock execution*, not approval or CRM authorization."""
    plan = context['approval_plan']
    _check_digest(plan, 'gate_plan_sha256')
    rows = []
    for r in sorted(plan['requests'], key=lambda x: x['source_record_id']):
        _check_digest(r, 'request_sha256')
        if (r['source_type'] != SCOPE or r['object_type'] != 'company' or
                r['field'] not in ALLOWED_FIELDS or r['field'] != 'country' or
                r['old_value'] != FROM_COUNTRY or r['proposed_value'] != TO_COUNTRY or
                r['rollback_value'] != FROM_COUNTRY or
                r['write_authorized'] is not False or r['merge_authorized'] is not False or
                r['approval_recorded'] is not False):
            raise SimulationError('Unexpected mock execution scope')
        status = r['status']
        if status not in ('awaiting_independent_approval', 'held_duplicate_dependency'):
            raise SimulationError('Unexpected request status')
        if (status == 'held_duplicate_dependency') != bool(r['dependency_candidate_keys']):
            raise SimulationError('Duplicate dependency gate inconsistent')
        rows.append({
            'request_id': r['request_id'], 'request_sha256': r['request_sha256'],
            'source_record_id': r['source_record_id'], 'field': 'country',
            'old_value': FROM_COUNTRY, 'proposed_value': TO_COUNTRY,
            'status': 'held_duplicate_dependency' if status == 'held_duplicate_dependency' else 'mock_gate_required',
            'source_record_sha256': r['source_record_sha256'],
            'associations_sha256': r['associations_sha256'],
            'write_authorized': False, 'merge_authorized': False,
        })
    states = Counter(row['status'] for row in rows)
    if states != {'mock_gate_required': 22, 'held_duplicate_dependency': 9}:
        raise SimulationError('Unexpected mock execution counts')
    result = {'schema_version': 'm4c-1', 'version': VERSION, 'source_type': SCOPE,
              'm4b_gate_plan_sha256': plan['gate_plan_sha256'],
              'counts': {'requests': 31, 'mock_gate_required': 22,
                         'held_duplicate_dependency': 9, 'actual_approvals': 0},
              'operations': rows,
              'guarantees': {'crm_writes': 0, 'postgres_writes': 0,
                             'airtable_writes': 0, 'merges': 0,
                             'real_approvals': 0, 'source_files_written': 0}}
    result['execution_plan_sha256'] = _digest(result)
    return result


class MemoryExecutor:
    """Stateful in-memory demonstration. Journal and changes die with this object.

    Each attempt has an explicit immutable attempt ID; an exact replay cannot
    reapply. A compensated attempt cannot be retried under the same attempt ID.
    """

    def __init__(self, context: dict):
        plan = context['approval_plan']
        _check_digest(plan, 'gate_plan_sha256')
        self.plan = plan
        self.policy = copy.deepcopy(context['policy'])
        self.associations = copy.deepcopy(context['associations'])
        self.initial = copy.deepcopy(context['companies'])
        self.records = {x['record_id']: copy.deepcopy(x) for x in self.initial}
        self.requests = {x['request_id']: copy.deepcopy(x) for x in plan['requests']}
        if len(self.records) != 120 or len(self.requests) != 31:
            raise SimulationError('Invalid simulation source dimensions')
        self._original_association_hash = _digest(self.associations)
        self.journal: list[dict] = []
        self.completed: dict[str, dict] = {}
        self._event_index = 0

    def _event(self, attempt: str, request: dict, action: str, *, reason: str = '') -> None:
        self._event_index += 1
        self.journal.append({'sequence': self._event_index, 'attempt_id': attempt,
                             'request_id': request['request_id'],
                             'record_id': request['source_record_id'],
                             'action': action, 'reason': reason})

    def _assert_unchanged_associations(self):
        if _digest(self.associations) != self._original_association_hash:
            raise SimulationError('Association drift in simulated workspace')

    def _assert_plan_binding(self, request: dict):
        original = self.requests.get(request.get('request_id')) if isinstance(request, dict) else None
        if original is None or original != request:
            raise SimulationError('Unknown/modified mock request')
        _check_digest(request, 'request_sha256')
        if (request['status'] != 'awaiting_independent_approval' or
                request['dependency_candidate_keys'] or request['write_authorized'] is not False or
                request['merge_authorized'] is not False or request['approval_recorded'] is not False):
            raise SimulationError('Mock execution denied: held or authorized request')
        if (request['source_type'] != SCOPE or request['field'] != 'country' or
                request['old_value'] != FROM_COUNTRY or request['proposed_value'] != TO_COUNTRY or
                request['rollback_value'] != FROM_COUNTRY):
            raise SimulationError('Unsupported mock operation')

    def _gate(self, request: dict, decision: dict, now: datetime):
        self._assert_plan_binding(request)
        row = self.records[request['source_record_id']]
        self._assert_unchanged_associations()
        out = preflight_request(request, row, self.associations, self.policy,
                                self.plan['source_plan_sha256'],
                                demo_decision=decision, now=now)
        if out['status'] != 'demo_only_preflight_eligible':
            raise SimulationError('Mock preflight blocked: ' + out['status'])
        if out.get('crm_write_authorized') is not False or out.get('merge_authorized') is not False:
            raise SimulationError('Unexpected mock authorization result')

    def run(self, request: dict, decision: dict, *, attempt_id: str, now: datetime,
            before_write=None, inject_verify_failure: bool = False) -> dict:
        """A single attempt, with second TOCTOU guard right before in-memory mutation.

        `before_write` is exclusively a test fault hook, never called by CLI in normal mode.
        """
        if not isinstance(attempt_id, str) or not attempt_id.startswith('synthetic-attempt:') or len(attempt_id) > 120:
            raise SimulationError('Invalid synthetic attempt ID')
        self._assert_plan_binding(request)
        operation_fingerprint = _digest({'request': request['request_sha256'],
                                         'decision': decision, 'attempt_id': attempt_id})
        if attempt_id in self.completed:
            prev = self.completed[attempt_id]
            if prev['fingerprint'] != operation_fingerprint:
                raise SimulationError('Conflicting replay using the same attempt ID')
            self._event(attempt_id, request, 'idempotent_replay')
            return {'status': 'idempotent_replay', 'changed': False, 'original_outcome': prev['status']}
        if any(e['attempt_id'] == attempt_id for e in self.journal):
            raise SimulationError('Attempt ID already used in incomplete operation')
        self._event(attempt_id, request, 'attempt_started')
        try:
            self._gate(request, decision, now)
            self._event(attempt_id, request, 'mock_preflight_passed')
            row = self.records[request['source_record_id']]
            if before_write is not None:
                before_write(row)
            self._assert_unchanged_associations()
            # The second guard, independent of the earlier preflight, prevents
            # a simulated read-before-write race / stale data mutation.
            if (row['country'] != FROM_COUNTRY or
                    _digest(row) != request['source_record_sha256'] or
                    _digest(_associated(self.associations, request['source_record_id'])) != request['associations_sha256']):
                self._event(attempt_id, request, 'blocked_stale_before_write')
                self.completed[attempt_id] = {'fingerprint': operation_fingerprint, 'status': 'blocked_stale'}
                return {'status': 'blocked_stale', 'changed': False}
            before = copy.deepcopy(row)
            after = copy.deepcopy(before)
            after['country'] = TO_COUNTRY
            self.records[request['source_record_id']] = after
            self._event(attempt_id, request, 'simulated_country_change')
            if inject_verify_failure:
                after['industry'] = 'injected-postwrite-drift'
            allowed = (after['country'] == TO_COUNTRY and
                       {k for k in before if before[k] != after.get(k)} == {'country'} and
                       _digest(self.associations) == self._original_association_hash)
            if not allowed:
                self._event(attempt_id, request, 'postcheck_failed')
                # Restore only if the current record is still the precise
                # expected simulated poststate. Otherwise require manual review.
                expected_post = dict(before, country=TO_COUNTRY)
                if after == expected_post:
                    self.records[request['source_record_id']] = before
                    self._event(attempt_id, request, 'compensated')
                    final = 'compensated'
                else:
                    self._event(attempt_id, request, 'manual_reconciliation_required')
                    final = 'manual_reconciliation_required'
                self.completed[attempt_id] = {'fingerprint': operation_fingerprint, 'status': final}
                return {'status': final, 'changed': False if final == 'compensated' else True}
            self._event(attempt_id, request, 'postcheck_verified')
            self.completed[attempt_id] = {'fingerprint': operation_fingerprint, 'status': 'simulated_verified'}
            return {'status': 'simulated_verified', 'changed': True}
        except (GateError, ValueError, KeyError, TypeError) as exc:
            self._event(attempt_id, request, 'preflight_rejected', reason=type(exc).__name__)
            self.completed[attempt_id] = {'fingerprint': operation_fingerprint, 'status': 'blocked_preflight'}
            return {'status': 'blocked_preflight', 'changed': False}

    def compensate(self, request: dict, *, attempt_id: str) -> str:
        """Never blindly overwrite a record if post-state has drifted."""
        self._assert_plan_binding(request)
        prior = self.completed.get(attempt_id)
        if prior is None:
            raise SimulationError('No such attempt to compensate')
        if prior['status'] == 'compensated':
            self._event(attempt_id, request, 'idempotent_compensation_replay')
            return 'compensated'
        if prior['status'] != 'simulated_verified':
            raise SimulationError('Attempt is not eligible for compensation')
        row = self.records[request['source_record_id']]
        source = next(x for x in self.initial if x['record_id'] == request['source_record_id'])
        expected = dict(source, country=TO_COUNTRY)
        if row != expected or _digest(self.associations) != self._original_association_hash:
            self._event(attempt_id, request, 'compensation_conflict')
            prior['status'] = 'compensation_conflict'
            return 'compensation_conflict'
        self.records[request['source_record_id']] = copy.deepcopy(source)
        prior['status'] = 'compensated'
        self._event(attempt_id, request, 'compensated')
        return 'compensated'

    def unchanged_source(self) -> bool:
        return self.initial == [self.records[x['record_id']] for x in self.initial]


def execute_demo_batch(context: dict, requests: list[dict], *, now: datetime,
                       attempt_prefix: str = 'synthetic-attempt:batch',
                       inject_failure_after: int | None = None,
                       inject_compensation_conflict: bool = False) -> dict:
    """Bounded in-memory batch with compensating actions after an injected failure.

    No external side effects or durable transaction guarantees are implied.
    `inject_failure_after` simulates losing execution control after N mock changes.
    """
    if not isinstance(requests, list) or not 1 <= len(requests) <= 22:
        raise SimulationError('Invalid bounded synthetic batch')
    if len({r.get('request_id') for r in requests}) != len(requests):
        raise SimulationError('Duplicate request in synthetic batch')
    if (not isinstance(attempt_prefix, str) or
            not attempt_prefix.startswith('synthetic-attempt:') or len(attempt_prefix) > 90):
        raise SimulationError('Invalid synthetic attempt prefix')
    if inject_failure_after is not None and (isinstance(inject_failure_after, bool) or
            not isinstance(inject_failure_after, int) or not 1 <= inject_failure_after <= len(requests)):
        raise SimulationError('Invalid failure injection point')
    work = MemoryExecutor(context)
    # Check the complete operation set before starting; held requests are
    # refused even if their mock approval packet appears to pass.
    for req in requests:
        work._assert_plan_binding(req)
    succeeded = []
    failure_reason = None
    for index, req in enumerate(requests):
        attempt = f'{attempt_prefix}:{index}'
        result = work.run(req, demo_decision(req), attempt_id=attempt, now=now)
        if result['status'] != 'simulated_verified':
            failure_reason = result['status']
            break
        succeeded.append((req, attempt))
        if inject_failure_after is not None and len(succeeded) == inject_failure_after:
            failure_reason = 'injected_partial_failure'
            break
    if failure_reason is None:
        return {'status': 'fully_simulated', 'simulated_changes': len(succeeded),
                'compensated': 0, 'manual_attention': 0,
                'source_original_unchanged': context['companies'] == work.initial,
                'external_writes': 0, 'journal': work.journal}
    if inject_compensation_conflict and succeeded:
        # Deliberately model an external change to the last modified in-memory
        # row, so exact compensation is impossible and must be escalated.
        req, _ = succeeded[-1]
        work.records[req['source_record_id']]['industry'] = 'injected-postwrite-conflict'
    compensated = 0
    conflicts = 0
    for req, attempt in reversed(succeeded):
        action = work.compensate(req, attempt_id=attempt)
        compensated += int(action == 'compensated')
        conflicts += int(action == 'compensation_conflict')
    if conflicts == 0 and not work.unchanged_source():
        raise SimulationError('Batch failed exact compensation invariant')
    return {'status': 'manual_reconciliation_required' if conflicts else 'compensated_after_failure',
            'failure_reason': failure_reason, 'simulated_changes': len(succeeded),
            'compensated': compensated, 'manual_attention': conflicts,
            'source_original_unchanged': context['companies'] == work.initial,
            'external_writes': 0, 'journal': work.journal}


def run_demo_scenarios(context: dict) -> dict:
    """Deterministic representative demonstration; ALL effects in memory."""
    original_source_digest = _digest(context['companies'])
    original_association_digest = _digest(context['associations'])
    plan = execution_plan(context)
    eligible = sorted((r for r in context['approval_plan']['requests']
                       if r['status'] == 'awaiting_independent_approval'),
                      key=lambda x: x['source_record_id'])
    if len(eligible) != 22:
        raise SimulationError('Expected 22 synthetic demo-eligible requests')
    now = DEMO_TIME + timedelta(minutes=1)
    a, b, c = eligible[:3]
    # Valid simulated state transition and idempotent replay (no double patch).
    happy = MemoryExecutor(context)
    one_decision = demo_decision(a)
    first = happy.run(a, one_decision, attempt_id='synthetic-attempt:happy', now=now)
    replay = happy.run(a, one_decision, attempt_id='synthetic-attempt:happy', now=now)
    if first['status'] != 'simulated_verified' or replay['status'] != 'idempotent_replay':
        raise SimulationError('Happy-path / replay simulation mismatch')
    if happy.compensate(a, attempt_id='synthetic-attempt:happy') != 'compensated' or not happy.unchanged_source():
        raise SimulationError('Happy-path compensation mismatch')
    # A record changing after preflight but before the simulated write is blocked.
    stale = MemoryExecutor(context)
    stale_out = stale.run(a, one_decision, attempt_id='synthetic-attempt:stale', now=now,
                          before_write=lambda row: row.__setitem__('industry', 'injected-concurrent-change'))
    if stale_out['status'] != 'blocked_stale' or stale.records[a['source_record_id']]['country'] != FROM_COUNTRY:
        raise SimulationError('TOCTOU gate did not stop an unsafe operation')
    # Inject partial-batch failure and verify reverse-order compensations.
    batch = execute_demo_batch(context, [a, b, c], now=now, inject_failure_after=2)
    if (batch['status'] != 'compensated_after_failure' or
            batch['simulated_changes'] != 2 or batch['compensated'] != 2 or
            batch['external_writes'] != 0):
        raise SimulationError('Partial failure compensation was not exact')
    # A separate post-write drift must prevent naive rollback and signal manual review.
    drift = MemoryExecutor(context)
    attempt = 'synthetic-attempt:rollback-drift'
    result = drift.run(c, demo_decision(c), attempt_id=attempt, now=now)
    if result['status'] != 'simulated_verified':
        raise SimulationError('Rollback conflict scenario could not start')
    drift.records[c['source_record_id']]['industry'] = 'injected-third-party-edit'
    rollback = drift.compensate(c, attempt_id=attempt)
    if rollback != 'compensation_conflict':
        raise SimulationError('Rollback conflict not detected')
    if not all(x.get('write_authorized') is False and x.get('merge_authorized') is False for x in plan['operations']):
        raise SimulationError('Unexpected authorization in simulation plan')
    if (_digest(context['companies']) != original_source_digest or
            _digest(context['associations']) != original_association_digest):
        raise SimulationError('Original source or associations were altered by simulation')
    summary = {
        'schema_version': 'm4c-demo-1', 'source_type': SCOPE,
        'execution_plan_sha256': plan['execution_plan_sha256'],
        'request_counts': plan['counts'],
        'scenarios': {
            'happy_path_verified': 1, 'idempotent_replay': 1,
            'happy_path_compensated': 1, 'stale_before_write_blocked': 1,
            'partial_failure_injected': 1,
            'partial_changes_compensated': batch['compensated'],
            'rollback_conflict_detected': 1,
        },
        'source_fixture_unchanged': True,
        'associations_unchanged': True,
        'actual_approvals': 0, 'crm_writes': 0,
        'postgres_writes': 0, 'airtable_writes': 0, 'merges': 0,
    }
    return summary
