"""Evaluate M2c routing on constructed, labeled synthetic data ONLY.

Labels are loaded after inference. A routing decision is not an identity claim.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from crm_quality.matching_triage import triage_matches  # noqa: E402
from crm_quality.profiling import load_csv  # noqa: E402
from m2b_diagnose_and_benchmark import evaluate_complete_groups  # noqa: E402


def pair(r: dict) -> tuple[str, str]:
    return (r['record_id_1'], r['record_id_2'])


def metrics_for_routes(records: list[dict], routed: list[dict], truth: dict) -> dict:
    ids = {x['record_id'] for x in records}
    if ids != set(truth):
        raise ValueError('Missing identity labels')
    output = {}
    for route in sorted(set(r['route'] for r in routed)):
        items = [r for r in routed if r['route'] == route]
        tp = sum(1 for r in items if truth[r['record_id_1']] == truth[r['record_id_2']])
        fp = len(items) - tp
        output[route] = {'count': len(items), 'labeled_same_entity': tp,
                         'labeled_distinct': fp}
    return output


def main() -> int:
    original = ROOT / 'fixtures' / 'synthetic'
    original_rows = [load_csv(original / (kind + '.csv')) for kind in ('contacts', 'companies', 'associations')]
    m0_plan = triage_matches(*original_rows)  # inference happens BEFORE original labels
    original_labels = json.loads((original / 'ground_truth.json').read_text(encoding='utf-8'))
    original_positives = {tuple(sorted(x)) for x in original_labels['contact_same_person_pairs']}
    baseline = {pair(x) for x in m0_plan['candidates'] if x['object_type'] == 'contacts'}
    hints = {pair(x) for x in m0_plan['exploratory_hints']}

    challenge = ROOT / 'fixtures' / 'm2b_challenge'
    challenge_rows = [load_csv(challenge / (kind + '.csv')) for kind in ('contacts', 'companies', 'associations')]
    result = triage_matches(*challenge_rows)  # inference happens BEFORE labels
    labels = json.loads((challenge / 'identity_groups.json').read_text(encoding='utf-8'))
    if labels.get('status') != 'fully_adjudicated_by_construction':
        raise ValueError('Challenge label contract not met')

    rows = {}
    for kind, group_key in (('contacts', 'contact_identity_groups'), ('companies', 'company_identity_groups')):
        selected = [r for r in result['candidates'] if r['object_type'] == kind]
        entity_rows = challenge_rows[0 if kind == 'contacts' else 1]
        rows[kind] = {
            'baseline_candidate_metrics_unchanged': evaluate_complete_groups(
                entity_rows, selected, kind, labels[group_key]),
            'routed_candidates': metrics_for_routes(entity_rows, selected, labels[group_key]),
        }
    rows['contacts']['exploratory_hints'] = metrics_for_routes(
        challenge_rows[0], result['exploratory_hints'], labels['contact_identity_groups'])
    # Existing pairs vs hints MUST be disjoint.
    if ({pair(x) for x in result['candidates'] if x['object_type'] == 'contacts'} &
            {pair(x) for x in result['exploratory_hints']}):
        raise ValueError('Existing candidates and weak hints unexpectedly overlap')
    report = {
        'scope': 'M2c synthetic-only, offline diagnostic',
        'engine': 'M2a detection unchanged; new routing/weak-hint layer only',
        'm0': {
            'intentional_contact_positives': len(original_positives),
            'baseline_detected': len(original_positives & baseline),
            'name_only_exploratory_positive_hints': len((original_positives - baseline) & hints),
            'name_only_hints_total': len(hints),
            'note': 'Unlabeled M0 name collisions prevent valid hint precision estimates.',
        },
        'challenge': rows,
        'limitations': [
            'M2b challenge authored with knowledge of M2a; not independent held-out validation.',
            'M2c routes were designed after inspecting M2b errors: selection bias applies.',
            'Exploratory hints are not validated duplicates or eligible for CRM actions.',
            'Strong evidence still needs human review; no merges or patches occur.',
            'No CRM, Make, Airtable, AI or PostgreSQL access.',
        ],
    }
    p = ROOT / 'evidence' / 'matching' / 'M2C_TRIAGE_EVALUATION.json'
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print('M2c synthetic evaluation — no API/DB calls; no writes or merge')
    print(f"M0 baseline positives {report['m0']['baseline_detected']}/{report['m0']['intentional_contact_positives']}; "
          f"weak-only hints {report['m0']['name_only_exploratory_positive_hints']}; "
          f"total hint burden {report['m0']['name_only_hints_total']}")
    for kind in ('contacts', 'companies'):
        a = rows[kind]['baseline_candidate_metrics_unchanged']
        print(f'{kind}: baseline TP={a["true_positive"]} FP={a["false_positive"]} '
              f'FN={a["false_negative"]}; routes={rows[kind]["routed_candidates"]}')
    print(f"contact weak hints: {rows['contacts']['exploratory_hints']}")
    print('Evidence: evidence/matching/M2C_TRIAGE_EVALUATION.json')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (ValueError, OSError, KeyError) as exc:
        print(f'FAIL: {type(exc).__name__} (safe failure, no CRM calls)')
        raise SystemExit(1) from None
