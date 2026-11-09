"""M3c review-decision ingest (read-only Airtable GET; append-only local PG).

Usage:
  py scripts/m3c_sync_review_decisions.py --init-db
  py scripts/m3c_sync_review_decisions.py --preview
  py scripts/m3c_sync_review_decisions.py --apply --expected-digest SHA256_FROM_PREVIEW
  py scripts/m3c_sync_review_decisions.py --status

The API token requires only data.records:read for the one review base.
Neither this script nor the SQL imports HubSpot or supports CRM writes/merge.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'scripts'))
from crm_quality.review_queue import build_plan, local_pg_settings  # noqa: E402
from crm_quality.decision_sync import (IntakeError, apply_snapshot, prepare_snapshot,
                                       request_records, ensure_db_plan)  # noqa: E402
from m1_snapshot_hubspot import local_env  # noqa: E402


def local_pg(env):
    import psycopg
    return psycopg.connect(**local_pg_settings(env))


def init_db(env) -> None:
    sql = (ROOT / 'sql' / '004_m3c_decision_events.sql').read_text(encoding='utf-8')
    with local_pg(env) as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
    print('PASS: local append-only decision journal schema ready; Airtable/CRM calls=0')


def read_and_validate(env):
    token = env.get('AIRTABLE_REVIEW_PAT', '')
    plan = build_plan(ROOT / 'fixtures' / 'synthetic')
    raw = request_records(token)
    snapshot = prepare_snapshot(raw, plan)
    return plan, snapshot


def print_preview(snapshot):
    print('M3c VALIDATED AIRTABLE SNAPSHOT (synthetic-only; Airtable GET; no changes)')
    print(f'candidate_count={snapshot["total"]} | unreviewed={snapshot["not_reviewed"]} | '
          f'available_decisions={len(snapshot["decisions"])} | ignored_blank_template_rows={snapshot["blanks"]}')
    from collections import Counter
    counts = Counter(e['decision'] for e in snapshot['decisions'])
    for key in ('Same Entity','Different Entity','Needs More Evidence'):
        print(f'{key}: {counts.get(key, 0)}')
    print('SNAPSHOT_SHA256=' + snapshot['sha256'])
    print('NOTE: decision classification alone NEVER authorizes CRM write/merge.')


def apply(env, expected_digest):
    if not re.fullmatch(r'[0-9a-f]{64}', expected_digest or ''):
        raise IntakeError('Provide a full SHA256 from --preview via --expected-digest')
    plan, snap = read_and_validate(env)
    if snap['sha256'] != expected_digest:
        raise IntakeError('Review snapshot changed since preview; run --preview again')
    with local_pg(env) as conn:
        result = apply_snapshot(conn, snap, plan)
    print('PASS: verified decision snapshot recorded in local PostgreSQL')
    print(f'observed={result["observed_decisions"]} | inserted={result["inserted"]} | '
          f'idempotent_replays={result["replayed_without_change"]} | crm_writes=0 | merges=0')


def status(env):
    with local_pg(env) as conn:
        with conn.cursor() as cur:
            cur.execute('''SELECT COUNT(*), COUNT(DISTINCT candidate_id)
                           FROM crm_reviewer_decision_events''')
            events, candidates = cur.fetchone()
            cur.execute('''SELECT decision,COUNT(*) FROM crm_reviewer_latest_decision
                           GROUP BY decision ORDER BY decision''')
            summary = cur.fetchall()
    print(f'M3c local events={events} | classified_candidates={candidates} | crm_writes=0')
    for decision, num in summary:
        print(f'{decision}: {num}')


def main():
    parser = argparse.ArgumentParser(description='M3c Airtable READ-only -> local PostgreSQL event journal')
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--init-db', action='store_true')
    action.add_argument('--preview', action='store_true')
    action.add_argument('--apply', action='store_true')
    action.add_argument('--status', action='store_true')
    parser.add_argument('--expected-digest', default='')
    args = parser.parse_args()
    if args.expected_digest and not args.apply:
        parser.error('--expected-digest is only valid with --apply')
    if args.apply and not args.expected_digest:
        parser.error('--apply requires --expected-digest from a prior --preview')
    try:
        env = local_env()
        if args.init_db:
            init_db(env)
        elif args.status:
            status(env)
        elif args.preview:
            _plan, snap = read_and_validate(env)
            print_preview(snap)
        elif args.apply:
            apply(env, args.expected_digest)
        return 0
    except Exception as exc:
        # Do not log secrets, PII, untrusted records or raw API/DB exception bodies.
        if isinstance(exc, IntakeError):
            print(f'FAIL CLOSED: {exc}; no CRM changes')
        else:
            print(f'FAIL CLOSED: {type(exc).__name__}; see M3c docs, no CRM changes')
        return 1


if __name__ == '__main__':
    sys.exit(main())
