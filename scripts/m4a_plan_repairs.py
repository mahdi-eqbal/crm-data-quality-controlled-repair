"""M4a offline synthetic-only proposal and rollback dry run. No CRM/DB/Airtable calls.

Run:
  py scripts/m4a_plan_repairs.py --preview
  py scripts/m4a_plan_repairs.py --report
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
from crm_quality.repair_planning import RepairPlanError, build_country_plan  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description='M4a read-only synthetic company country repair dry run')
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--preview', action='store_true', help='Print summary. No file writes.')
    mode.add_argument('--report', action='store_true', help='Export local ignored JSON report. No source/DB/CRM writes.')
    args = parser.parse_args()
    try:
        plan = build_country_plan(ROOT / 'fixtures' / 'synthetic', ROOT / 'config' / 'quality_policy.json')
        c = plan['counts']
        print('M4a SYNTHETIC-ONLY COUNTRY NORMALIZATION DRY RUN')
        print('companies_scanned={companies_scanned} | opportunities={country_normalization_opportunities} | '
              'reviewable_dry_run={reviewable_dry_run} | held_duplicate_dependency={held_duplicate_dependency} | '
              'not_applicable={not_applicable}'.format(**c))
        print(f'simulated_changes={plan["simulation"]["simulated_country_changes"]} | '
              f'rollback_exact={plan["simulation"]["simulated_rollback_exact"]} | '
              f'associations_unchanged={plan["simulation"]["associations_unchanged"]}')
        print('PLAN_SHA256=' + plan['plan_sha256'])
        print('CRM_WRITES=0 | POSTGRES_WRITES=0 | AIRTABLE_WRITES=0 | MERGES=0 | APPROVALS=0')
        if args.report:
            target = ROOT / 'private_exports' / 'm4a' / 'company_country_dry_run.json'
            target.parent.mkdir(parents=True, exist_ok=True)
            payload = json.dumps(plan, indent=2, ensure_ascii=True, sort_keys=True) + '\n'
            # No user-defined output path, no secrets, deterministic JSON; atomic replace.
            temp_path = None
            try:
                with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=target.parent,
                                                 prefix='.m4a-', suffix='.tmp', delete=False) as f:
                    temp_path = Path(f.name)
                    f.write(payload)
                os.replace(temp_path, target)
            finally:
                if temp_path is not None and temp_path.exists():
                    temp_path.unlink()
            print('Local ignored report: private_exports/m4a/company_country_dry_run.json')
        return 0
    except (RepairPlanError, OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        # Do not print sensitive fixture content, tokens, or raw exception bodies.
        print(f'FAIL CLOSED: M4a {type(exc).__name__}; no CRM/DB changes')
        return 1


if __name__ == '__main__':
    sys.exit(main())
