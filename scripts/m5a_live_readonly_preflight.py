"""M5a live HubSpot developer test GET-only read, PostgreSQL READ ONLY compare.

Run `py scripts/m5a_live_readonly_preflight.py --check` or `--report`.
No CRM write operations exist. Exits 0=in sync, 3=drift, 1=blocked.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'scripts'))
from crm_quality.live_preflight import (LivePreflightError, PORTAL_ID,
                                         compare, fetch_live, read_baseline)  # noqa: E402
from crm_quality.review_queue import local_pg_settings  # noqa: E402
from m1_snapshot_hubspot import local_env  # noqa: E402


def get_json_once(url, token):
    """One GET per endpoint, no retries and no write methods."""
    req = Request(url, method='GET', headers={'Authorization': 'Bearer ' + token,
                                              'Accept': 'application/json',
                                              'User-Agent': 'crm-quality-m5a-readonly/0.1'})
    with urlopen(req, timeout=20) as response:
        return json.load(response)



def perform(env, fetcher=get_json_once):
    if env.get('HUBSPOT_ACCOUNT_ID') != PORTAL_ID:
        raise LivePreflightError('Dedicated developer test portal not configured')
    key = env.get('HUBSPOT_SERVICE_KEY', '')
    # This call is deliberately bounded to <=13 GET requests, with no CRM writes.
    live = fetch_live(key, env['HUBSPOT_ACCOUNT_ID'], fetcher)
    import psycopg
    config = local_pg_settings(env)  # forces localhost, database and user allowlist
    # PostgreSQL session cannot INSERT/UPDATE/DELETE, even if future code changes.
    with psycopg.connect(**config, options='-c default_transaction_read_only=on') as conn:
        with conn.cursor() as cur:
            baseline = read_baseline(cur)
    return compare(live, baseline, datetime.now(timezone.utc).isoformat())


def save_report(report):
    dest = ROOT / 'private_exports' / 'm5a' / 'live_readonly_preflight.json'
    dest.parent.mkdir(parents=True, exist_ok=True)
    scratch = None
    try:
        with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=dest.parent, prefix='.m5a-', suffix='.tmp', delete=False) as stream:
            scratch = Path(stream.name)
            json.dump(report, stream, indent=2, sort_keys=True)
            stream.write('\n')
        os.replace(scratch, dest)
    finally:
        if scratch and scratch.exists():
            scratch.unlink()
    return 'private_exports/m5a/live_readonly_preflight.json'


def main():
    parser = argparse.ArgumentParser(description='M5a bounded HubSpot GET / local PostgreSQL read-only drift check')
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--check', action='store_true')
    mode.add_argument('--report', action='store_true')
    args = parser.parse_args()
    try:
        report = perform(local_env())
        print('M5a LIVE READ-ONLY PREFLIGHT — VERIFIED DEVELOPER TEST ACCOUNT')
        print(f'STATUS={report["status"]} | HubSpot_GET={report["http_get_count"]} | baseline_run_id={report["baseline_run_id"]}')
        for kind, v in report['metrics'].items():
            print(f'{kind}: live={v["live"]} | baseline={v["baseline"]} | '
                  + ' | '.join(f'{k}={value}' for k, value in v.items() if k not in ('live','baseline')))
        print('CRM_WRITES=0 | POSTGRES_WRITES=0 | AIRTABLE_WRITES=0 | MERGES=0 | APPROVALS=0')
        print('NOTE: observational drift check; NOT approval for any HubSpot write.')
        if args.report:
            print('Local ignored report: ' + save_report(report))
        return 3 if report['status'] == 'DRIFT_REQUIRES_REVIEW' else 0
    except (LivePreflightError, HTTPError, URLError, OSError, ValueError, RuntimeError, TypeError, KeyError) as e:
        # Never print exception text: upstream errors may include credentials/PII.
        print(f'FAIL CLOSED: M5a {type(e).__name__}; no CRM or database writes')
        return 1


if __name__ == '__main__':
    sys.exit(main())
