"""Run the synthetic matching, repair and delivery-hold walkthrough offline."""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from crm_quality.a11_delivery_reconciliation import reconcile
from crm_quality.execution_simulation import build_context, run_demo_scenarios
from crm_quality.make_orchestration import construct, digest
from crm_quality.matching import match_records
from crm_quality.profiling import load_csv


def main() -> None:
    fixtures = ROOT / 'fixtures' / 'synthetic'
    context = build_context(fixtures, ROOT / 'config' / 'quality_policy.json')
    candidates = match_records(load_csv(fixtures / 'contacts.csv'),
                               context['companies'], context['associations'])
    if not candidates or any(
        row['requires_human_review'] is not True or row['merge_allowed'] is not False
        for row in candidates
    ):
        raise ValueError('Synthetic candidates must require review and prohibit merges')
    repair = run_demo_scenarios(context)

    source_id = '11111111-1111-4111-8111-111111111111'
    source_hash = 'a' * 64
    occurred = '2026-11-10T10:00:00Z'
    payload = construct('a8', source_id, '22222222-2222-4222-8222-222222222222',
                        'postwrite_verified', source_hash, occurred)
    event_id = payload['event_id']
    outbox = [{
        'event_id': event_id, 'source_layer': 'a8', 'source_event_id': source_id,
        'source_sha256': source_hash, 'case_ref': payload['case_ref'],
        'payload_sha256': digest(payload), 'payload': payload, 'occurred_at': occurred,
    }]
    journal = [{'event_id': event_id, 'event_kind': kind}
               for kind in ('dispatch_reserved', 'outcome_uncertain')]
    delivery = reconcile(outbox, journal)['events'][0]
    if delivery['action'] != 'HOLD_VERIFY_REMOTE_THEN_MANUAL_DECISION':
        raise ValueError('Uncertain delivery must remain on hold')

    print(json.dumps({
        'mode': 'offline_synthetic',
        'matching': {'candidates': len(candidates),
                     'by_tier': dict(Counter(row['tier'] for row in candidates)),
                     'requires_human_review': True, 'merge_allowed': False},
        'repair': {'approval_mode': 'mock', 'counts': repair['request_counts'],
                   'scenarios': repair['scenarios']},
        'delivery': {key: delivery[key] for key in ('local_state', 'remote_evidence', 'action')},
        'external_writes': 0,
    }, indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
