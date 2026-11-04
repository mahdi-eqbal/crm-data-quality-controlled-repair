"""Offline M2c review routing and limited, non-actionable name-only hints.

No HubSpot, PostgreSQL, Airtable, Make, AI or network activity.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from crm_quality.matching_triage import triage_matches  # noqa: E402
from crm_quality.profiling import load_csv  # noqa: E402


def main() -> int:
    fixture = ROOT / 'fixtures' / 'synthetic'
    manifest = json.loads((fixture / 'manifest.json').read_text(encoding='utf-8'))
    if manifest.get('dataset') != 'wholly_synthetic':
        raise ValueError('Only synthetic fixtures permitted')
    rows = [load_csv(fixture / (kind + '.csv'))
            for kind in ('contacts', 'companies', 'associations')]
    plan = triage_matches(*rows)
    count = Counter((r['object_type'], r['route']) for r in plan['candidates'])
    print('M2c offline triage | CRM/DB/network calls=0 | writes=0 | merges=0')
    for (kind, route), size in sorted(count.items()):
        print(f'{kind} / {route}: {size}')
    print(f"Exploratory name-only hints (NOT review queue): {len(plan['exploratory_hints'])}")
    print(f"Skipped oversized name groups: {plan['capacity']['oversized_name_groups_skipped']}")
    print('No identity decision, no AI, and no permission to repair or merge.')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (ValueError, OSError, KeyError) as exc:
        print(f'FAIL: {type(exc).__name__} (safe failure, no CRM calls)')
        raise SystemExit(1) from None
