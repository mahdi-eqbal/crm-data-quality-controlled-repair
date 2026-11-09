"""M3a local review queue. No HubSpot/Airtable/Make/API network calls.

--init-db: creates local PostgreSQL queue tables.
--stage-synthetic: stages only M0 fixture IDs/evidence; no PII.
--status: shows aggregate queue counts (not names/emails).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'scripts'))
from crm_quality.review_queue import build_plan, local_pg_settings, summarize_plan  # noqa: E402
from m1_snapshot_hubspot import local_env  # noqa: E402


def get_conn():
    import psycopg
    settings = local_pg_settings(local_env())
    return psycopg.connect(**settings)


def init_db() -> None:
    sql = (ROOT / 'sql' / '003_m3a_review_queue.sql').read_text(encoding='utf-8')
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
    print('PASS: local M3a review tables initialized (HubSpot calls=0)')


def stage() -> None:
    import psycopg
    plan = build_plan(ROOT / 'fixtures' / 'synthetic')
    with get_conn() as conn:
        with conn.cursor() as cur:
            # Read and write happen in one transaction; no partial batch on failure.
            cur.execute("SELECT batch_id, source_fingerprint FROM crm_review_batches WHERE source_type='synthetic_fixture_only'")
            batches = cur.fetchall()
            if any(f != plan['source_fingerprint'] for _id, f in batches):
                raise ValueError('Another synthetic batch already exists; review/supersede manually before re-staging')
            cur.execute('''INSERT INTO crm_review_batches
                (batch_id, source_fingerprint, source_type, rule_version, expected_candidates)
                VALUES (%s,%s,'synthetic_fixture_only',%s,%s)
                ON CONFLICT (source_fingerprint) DO NOTHING''',
                (plan['batch_id'], plan['source_fingerprint'], plan['rule_version'], len(plan['rows'])))
            for r in plan['rows']:
                cur.execute('''INSERT INTO crm_review_candidates
                    (candidate_id, batch_id, object_type, record_id_1, record_id_2,
                     tier, route, queue_status, rule_code, route_reason,
                     evidence_codes, name_similarity)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (candidate_id) DO NOTHING''',
                    (r['candidate_id'], plan['batch_id'], r['object_type'], r['record_id_1'],
                     r['record_id_2'], r['tier'], r['route'], r['queue_status'],
                     r['rule_code'], r['route_reason'], psycopg.types.json.Jsonb(r['evidence_codes']),
                     r['name_similarity']))
                cur.execute('''INSERT INTO crm_review_events (event_id, candidate_id, event_type, event_context)
                               VALUES (%s,%s,'candidate_staged',%s)
                               ON CONFLICT (candidate_id, event_type) DO NOTHING''',
                            (r['event_id'], r['candidate_id'], psycopg.types.json.Jsonb({'source': 'synthetic_m0'})))
            cur.execute('SELECT expected_candidates FROM crm_review_batches WHERE batch_id=%s', (plan['batch_id'],))
            original = cur.fetchone()
            cur.execute('SELECT COUNT(*) FROM crm_review_candidates WHERE batch_id=%s', (plan['batch_id'],))
            stored = cur.fetchone()[0]
            cur.execute('''SELECT COUNT(*) FROM crm_review_events e
                INNER JOIN crm_review_candidates c ON c.candidate_id=e.candidate_id
                WHERE c.batch_id=%s''', (plan['batch_id'],))
            events = cur.fetchone()[0]
            if not original or original[0] != len(plan['rows']) or stored != len(plan['rows']) or events != stored:
                raise ValueError('Incomplete or inconsistent queue state: transaction rolled back')
    print(f'PASS: idempotent local review queue | batch_id={plan["batch_id"]}')
    print(f'candidates={len(plan["rows"])} | statuses={summarize_plan(plan)}')
    print(f'exploratory_hints_excluded={plan["excluded_exploratory_hints"]} | crm_writes=0 | merges=0')


def status() -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute('''SELECT b.batch_id, b.expected_candidates,
                COUNT(c.candidate_id),
                COUNT(c.candidate_id) FILTER (WHERE c.queue_status='pending_review'),
                COUNT(c.candidate_id) FILTER (WHERE c.queue_status='needs_evidence')
                FROM crm_review_batches b LEFT JOIN crm_review_candidates c ON c.batch_id=b.batch_id
                GROUP BY b.batch_id ORDER BY b.created_at DESC LIMIT 5''')
            rows = cur.fetchall()
    if not rows:
        print('No review batches found')
    for batch_id, expected, found, pending, evidence in rows:
        verdict = 'PASS' if expected == found and pending + evidence == found else 'FAIL'
        print(f'{verdict}: batch={batch_id} | candidates={found}/{expected} | '
              f'pending_review={pending} | needs_evidence={evidence}')


def main() -> int:
    parser = argparse.ArgumentParser(description='M3a local synthetic-only review queue')
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--init-db', action='store_true')
    action.add_argument('--stage-synthetic', action='store_true')
    action.add_argument('--status', action='store_true')
    args = parser.parse_args()
    try:
        if args.init_db:
            init_db()
        elif args.stage_synthetic:
            stage()
        else:
            status()
        return 0
    except Exception as exc:
        # Never print DB exceptions; they can contain credential or record details.
        print(f'FAIL: {type(exc).__name__} (no HubSpot writes; check local setup)')
        return 1


if __name__ == '__main__':
    sys.exit(main())
