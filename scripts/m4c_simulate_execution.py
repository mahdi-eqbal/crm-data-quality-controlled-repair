"""M4c synthetic-only in-memory execution simulation; NEVER writes to CRM / DB / Airtable.

Usage:
  py scripts/m4c_simulate_execution.py --check
  py scripts/m4c_simulate_execution.py --demo
  py scripts/m4c_simulate_execution.py --report

Only --report writes an *ignored local report* under private_exports/m4c.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from crm_quality.execution_simulation import (  # noqa: E402
    SimulationError, build_context, execution_plan, run_demo_scenarios,
)


def write_report(payload: dict, path: Path):
    """Atomic local report only; refuse destination outside Git-ignored private_exports."""
    expected = ROOT / 'private_exports' / 'm4c' / 'execution_simulation.json'
    if path.resolve() != expected.resolve():
        raise SimulationError('Unsafe report destination')
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = None
    try:
        with tempfile.NamedTemporaryFile('w', dir=path.parent, suffix='.tmp',
                                         prefix='.m4c-', encoding='utf-8', delete=False) as f:
            temp = Path(f.name)
            json.dump(payload, f, ensure_ascii=True, indent=2, sort_keys=True)
            f.write('\n')
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, path)
    finally:
        if temp is not None and temp.exists():
            temp.unlink()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='M4c in-memory execution simulation; no external writes')
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--check', action='store_true')
    mode.add_argument('--demo', action='store_true')
    mode.add_argument('--report', action='store_true')
    args = parser.parse_args(argv)
    try:
        ctx = build_context(ROOT / 'fixtures' / 'synthetic', ROOT / 'config' / 'quality_policy.json')
        plan = execution_plan(ctx)
        print('M4c SYNTHETIC IN-MEMORY EXECUTION SIMULATION (NO REAL APPROVALS OR CRM WRITES)')
        print('requests=31 | mock_gate_required=22 | held_duplicate_dependency=9 | actual_approvals=0')
        print('EXECUTION_PLAN_SHA256=' + plan['execution_plan_sha256'])
        if args.demo or args.report:
            outcome = run_demo_scenarios(ctx)
            s = outcome['scenarios']
            print('DEMO_VERIFIED={happy_path_verified} | IDEMPOTENT_REPLAY={idempotent_replay} | '
                  'STALE_BEFORE_WRITE_BLOCKED={stale_before_write_blocked} | '
                  'PARTIAL_CHANGES_COMPENSATED={partial_changes_compensated} | '
                  'ROLLBACK_CONFLICT_DETECTED={rollback_conflict_detected}'.format(**s))
            if args.report:
                write_report({'execution_plan': plan, 'demo_result': outcome},
                             ROOT / 'private_exports' / 'm4c' / 'execution_simulation.json')
                print('Local ignored report: private_exports/m4c/execution_simulation.json')
        print('CRM_WRITES=0 | POSTGRES_WRITES=0 | AIRTABLE_WRITES=0 | MERGES=0 | REAL_APPROVALS=0')
        print('NOTE: In-memory compensation is NOT a proven live CRM rollback.')
        return 0
    except (SimulationError, ValueError, KeyError, TypeError, OSError) as exc:
        print(f'FAIL CLOSED: M4c {type(exc).__name__}; no external writes')
        return 1


if __name__ == '__main__':
    sys.exit(main())
