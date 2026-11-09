"""M4b synthetic-only approval request + preflight simulation; NO external access.

py scripts/m4b_approval_preflight.py --check
py scripts/m4b_approval_preflight.py --report
py scripts/m4b_approval_preflight.py --demo  # only in-memory mock actor claims
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from crm_quality.approval_preflight import (  # noqa: E402
    DEMO_KIND, GateError, build_approval_plan, evaluate_current_plan,
    preflight_request, validate_fresh_source_gate,
)
from crm_quality.repair_planning import RepairPlanError  # noqa: E402
from crm_quality.review_queue import validate_fixture  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description='M4b synthetic-only, read-only approval / preflight design')
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--check', action='store_true')
    mode.add_argument('--report', action='store_true')
    mode.add_argument('--demo', action='store_true', help='Demonstrate mock in-memory reviewer, NOT authorization')
    args = parser.parse_args()
    try:
        folder = ROOT / 'fixtures' / 'synthetic'
        policy_path = ROOT / 'config' / 'quality_policy.json'
        plan = build_approval_plan(folder, policy_path)
        status = evaluate_current_plan(folder, policy_path, report=plan)
        print('M4b SYNTHETIC APPROVAL REQUEST / PREFLIGHT DESIGN (OFFLINE; NO ACTUAL APPROVALS)')
        print(f'requests={plan["counts"]["requests"]} | '
              f'awaiting_independent_approval={status["counts"]["awaiting_independent_approval"]} | '
              f'held_duplicate_dependency={status["counts"]["held_duplicate_dependency"]}')
        print('GATE_PLAN_SHA256=' + plan['gate_plan_sha256'])
        print('ACTUAL_APPROVALS=0 | CRM_WRITES=0 | POSTGRES_WRITES=0 | AIRTABLE_WRITES=0 | MERGES=0')
        if args.report:
            out = ROOT / 'private_exports' / 'm4b' / 'approval_preflight_plan.json'
            out.parent.mkdir(parents=True, exist_ok=True)
            payload = json.dumps({'approval_plan': plan, 'preflight_summary': {
                'counts': status['counts'], 'scope': 'synthetic_fixture_only',
                'actual_approvals': 0, 'crm_write_authorized': False,
            }}, sort_keys=True, ensure_ascii=True, indent=2) + '\n'
            tmp = None
            try:
                with tempfile.NamedTemporaryFile('w', dir=out.parent, suffix='.tmp',
                                                 prefix='.m4b-', encoding='utf-8', delete=False) as f:
                    tmp = Path(f.name)
                    f.write(payload)
                os.replace(tmp, out)
            finally:
                if tmp is not None and tmp.exists():
                    tmp.unlink()
            print('Local ignored report: private_exports/m4b/approval_preflight_plan.json')
        elif args.demo:
            # Fixed synthetic decision for one eligible request; never saved or shared.
            request = next(x for x in plan['requests'] if x['status'] == 'awaiting_independent_approval')
            _, companies, associations = validate_fixture(folder)
            row = next(x for x in companies if x['record_id'] == request['source_record_id'])
            when = datetime(2026, 11, 9, 12, 0, tzinfo=timezone.utc)
            decision = {
                'kind': DEMO_KIND, 'request_id': request['request_id'],
                'request_sha256': request['request_sha256'], 'decision': 'approve_demo_preflight',
                'proposed_by': 'fixture.proposer', 'reviewed_by': 'fixture.separate.reviewer',
                'reason': 'Synthetic fixture demonstration; no real approval granted.',
                'reviewed_at': when.isoformat(), 'expires_at': (when + timedelta(hours=1)).isoformat(),
            }
            import json as _json
            policy = _json.loads(policy_path.read_text(encoding='utf-8'))
            result = preflight_request(request, row, associations, policy, plan['source_plan_sha256'],
                                       demo_decision=decision, now=when + timedelta(minutes=1))
            modified = dict(row, industry='Synthetic change after snapshot')
            stale = preflight_request(request, modified, associations, policy, plan['source_plan_sha256'],
                                      demo_decision=decision, now=when + timedelta(minutes=1))
            if result['status'] != 'demo_only_preflight_eligible' or stale['status'] != 'stale_source_record':
                raise GateError('Unexpected demo outcome')
            print('DEMO_ONLY_VALIDATED=1 | DEMO_STALE_BLOCKED=1 | ACTUAL_APPROVALS=0 | CRM_WRITES=0')
            print('NOTE: mock actor IDs are NOT authenticated independent approvals.')
        return 0
    except (GateError, RepairPlanError, KeyError, TypeError, ValueError, OSError) as exc:
        print(f'FAIL CLOSED: M4b {type(exc).__name__}; no external writes')
        return 1


if __name__ == '__main__':
    sys.exit(main())
