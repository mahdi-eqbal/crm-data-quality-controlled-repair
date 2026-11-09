"""M5b timestamp drift diagnosis. GET-only HubSpot and READ-ONLY PostgreSQL.

Usage:
  py scripts/m5b_timestamp_diagnostics.py --check
  py scripts/m5b_timestamp_diagnostics.py --report

Uses the existing M5a exact bounded GET and baseline readers. No HubSpot writes.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'scripts'))

from crm_quality.timestamp_diagnostics import diagnose  # noqa: E402
from crm_quality.live_preflight import PORTAL_ID, LivePreflightError, fetch_live, read_baseline  # noqa: E402
from crm_quality.review_queue import local_pg_settings  # noqa: E402
from m1_snapshot_hubspot import local_env  # noqa: E402
from m5a_live_readonly_preflight import get_json_once  # noqa: E402


def perform(env, fetcher=get_json_once):
    if env.get('HUBSPOT_ACCOUNT_ID') != PORTAL_ID:
        raise LivePreflightError('Wrong developer test portal')
    live = fetch_live(env.get('HUBSPOT_SERVICE_KEY', ''), env['HUBSPOT_ACCOUNT_ID'], fetcher)
    import psycopg
    with psycopg.connect(**local_pg_settings(env), options='-c default_transaction_read_only=on') as conn:
        with conn.cursor() as cur:
            baseline = read_baseline(cur)
    return diagnose(live, baseline, observed_at=datetime.now(timezone.utc).isoformat())


def save_report(data):
    dest = ROOT / 'private_exports' / 'm5b' / 'timestamp_diagnostics.json'
    dest.parent.mkdir(parents=True, exist_ok=True)
    scratch = None
    try:
        with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=dest.parent,
                                         prefix='.m5b-', suffix='.tmp', delete=False) as stream:
            scratch = Path(stream.name)
            json.dump(data, stream, indent=2, sort_keys=True)
            stream.write('\n')
        os.replace(scratch, dest)
    finally:
        if scratch is not None and scratch.exists():
            scratch.unlink()
    return 'private_exports/m5b/timestamp_diagnostics.json'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument('--check', action='store_true')
    selection.add_argument('--report', action='store_true')
    args = parser.parse_args()
    try:
        result = perform(local_env())
        print('M5b TIMESTAMP DRIFT DIAGNOSTICS (HUBSPOT GET ONLY / POSTGRES READ ONLY)')
        print('STATUS=' + result['status'] + ' | M5A=' + result['m5a_status'])
        print('contacts_changed=' + str(result['contact_count']['timestamps_changed'])
              + ' | other_drift=' + str(result['other_drift_count'])
              + ' | GETs=' + str(result['http_get_count']))
        for row in result['changed_contact_timestamps']:
            print(row['alias'] + ': baseline_utc=' + row['baseline_updated_at_utc']
                  + ' | live_utc=' + row['live_updated_at_utc']
                  + ' | delta_seconds=' + str(round(row['delta_ms'] / 1000, 3))
                  + ' | ' + row['direction'])
        print('changed_live_span_seconds=' + str(result['changed_live_update_span_seconds'])
              + ' | clustered_within_5_minutes=' + str(result['live_updates_within_5_minutes']))
        print('NO CAUSE INFERRED | NO BASELINE RESET | CRM_WRITES=0 | POSTGRES_WRITES=0 | MERGES=0')
        if args.report:
            print('Private ignored report: ' + save_report(result))
        # A drift is an observed condition, not an execution error.
        return 3 if result['m5a_status'] == 'DRIFT_REQUIRES_REVIEW' else 0
    except (LivePreflightError, HTTPError, URLError, OSError, ValueError, RuntimeError, TypeError, KeyError) as exc:
        print('FAIL CLOSED: M5b ' + type(exc).__name__ + '; no CRM or database writes')
        return 1


if __name__ == '__main__':
    sys.exit(main())
