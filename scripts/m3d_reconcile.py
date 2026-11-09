"""M3d: reconcile the synthetic-only Airtable review with local PostgreSQL.

    py scripts/m3d_reconcile.py --check
    py scripts/m3d_reconcile.py --report

Airtable: GET-only (one page for 60 rows). PostgreSQL: SELECT-only with an
explicit read-only transaction. No HubSpot requests, no reconciliation writes.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'scripts'))
from crm_quality.review_queue import build_plan, local_pg_settings  # noqa: E402
from crm_quality.decision_sync import IntakeError, request_records, prepare_snapshot, _score  # noqa: E402
from crm_quality.reconciliation import ReconcileError, reconcile  # noqa: E402
from m1_snapshot_hubspot import local_env  # noqa: E402


DB_CANDIDATES_SQL = '''
SELECT candidate_id, object_type, record_id_1, record_id_2, tier,
       route, queue_status, rule_code, route_reason, evidence_codes,
       name_similarity, merge_allowed, approved_for_crm_write
FROM crm_review_candidates WHERE batch_id=%s ORDER BY candidate_id
'''
DB_EVENTS_SQL = '''
SELECT e.candidate_id, e.event_id, e.airtable_record_id, e.source_modified_at,
       e.reviewer_airtable_user_id, e.decision, e.reviewer_notes,
       e.payload_sha256
FROM crm_reviewer_decision_events e
JOIN crm_review_candidates c ON c.candidate_id=e.candidate_id
WHERE c.batch_id=%s
ORDER BY e.candidate_id, e.source_modified_at ASC
'''


def db_history(cur, plan):
    """Validate all 57 queue candidates in a read-only transaction."""
    cur.execute('''SELECT batch_id, source_fingerprint, source_type, rule_version, expected_candidates
                   FROM crm_review_batches WHERE batch_id=%s''', (plan['batch_id'],))
    row = cur.fetchone()
    if (not row or str(row[0]) != str(plan['batch_id']) or row[1].strip() != plan['source_fingerprint']
            or row[2] != 'synthetic_fixture_only' or row[3] != plan['rule_version'] or row[4] != 57):
        raise ReconcileError('Local PostgreSQL synthetic batch does not match expected source')
    cur.execute(DB_CANDIDATES_SQL, (plan['batch_id'],))
    rows = cur.fetchall()
    by_id = {str(r['candidate_id']): r for r in plan['rows']}
    if len(rows) != 57 or {str(x[0]) for x in rows} != set(by_id):
        raise ReconcileError('Local PostgreSQL queue incomplete / unexpected candidates')
    for r in rows:
        original = by_id[str(r[0])]
        columns = ('object_type','record_id_1','record_id_2','tier','route','queue_status','rule_code','route_reason')
        if ([r[i] for i in range(1,9)] != [original[k] for k in columns]
                or list(r[9]) != original['evidence_codes']
                or _score(r[10]) != _score(original['name_similarity'])
                or r[11] is not False or r[12] is not False):
            raise ReconcileError('PostgreSQL candidate metadata mismatch or write flag enabled')
    cur.execute(DB_EVENTS_SQL, (plan['batch_id'],))
    events = []
    for r in cur.fetchall():
        events.append({
            'candidate_id': str(r[0]), 'event_id': str(r[1]),
            'airtable_record_id': r[2], 'edited_at': r[3], 'reviewer_id': r[4],
            'decision': r[5], 'notes': r[6], 'payload_sha256': r[7],
        })
    return events


def run(report=False):
    import psycopg
    env = local_env()
    plan = build_plan(ROOT / 'fixtures' / 'synthetic')
    snapshot = prepare_snapshot(request_records(env.get('AIRTABLE_REVIEW_PAT', '')), plan)
    with psycopg.connect(**local_pg_settings(env)) as conn:
        # Psycopg 3 sets default transaction characteristics before first SELECT.
        conn.read_only = True
        conn.isolation_level = psycopg.IsolationLevel.REPEATABLE_READ
        with conn.cursor() as cur:
            events = db_history(cur, plan)
    result = reconcile(snapshot, events, plan)
    print('M3d READ-ONLY RECONCILIATION (synthetic-only)')
    print(f'candidates={result["candidates"]} | airtable_decisions={result["airtable_decisions"]} | '
          f'postgres_events={result["postgres_events"]} | revisions={result["postgres_revisions"]}')
    for key, n in result['summary'].items():
        print(f'{key}={n}')
    print('RECONCILED=' + ('YES' if result['reconciled'] else 'NO'))
    print('Airtable=GET only | PostgreSQL=READ ONLY | crm_writes=0 | merges=0')
    if result['discrepancies']:
        for item in result['discrepancies'][:15]:
            print(f'CHECK: {item["candidate_key"]} | {item["status"]}')
    if report:
        out = ROOT / 'private_exports' / 'm3d' / 'reconciliation_report.json'
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, indent=2, ensure_ascii=True) + '\n', encoding='utf-8')
        print('Local untracked report: private_exports/m3d/reconciliation_report.json')
    return 0 if result['reconciled'] else 2


def main():
    parser = argparse.ArgumentParser(description='Read-only synthetic Airtable/PostgreSQL reconciliation')
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument('--check', action='store_true', help='Read-only summary, no files created')
    actions.add_argument('--report', action='store_true', help='Also write local gitignored JSON report')
    args = parser.parse_args()
    try:
        return run(report=args.report)
    except (IntakeError, ReconcileError) as e:
        print(f'FAIL CLOSED: {e} | crm_writes=0')
        return 1
    except Exception as e:
        # Do not include raw exceptions which may contain credentials or source data.
        print(f'FAIL CLOSED: {type(e).__name__} | no CRM changes')
        return 1


if __name__ == '__main__':
    sys.exit(main())
