"""M5c, at most 14 HubSpot GETs; local PostgreSQL READ ONLY.

--check  : return counts and privacy-safe metadata only; no file writes
--report : same probe, atomically write a Git-ignored local JSON report

Status 0=no contact timestamp drift, 3=drift observed, 1=fail closed.
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

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'scripts'))

from crm_quality.history_attribution import correlate, fetch_selected_history  # noqa: E402
from crm_quality.live_preflight import (LivePreflightError, PORTAL_ID, fetch_live, read_baseline)  # noqa: E402
from crm_quality.review_queue import local_pg_settings  # noqa: E402
from m1_snapshot_hubspot import local_env  # noqa: E402
from m5a_live_readonly_preflight import get_json_once  # noqa: E402


def perform(env: dict, fetcher=get_json_once) -> dict:
    if env.get('HUBSPOT_ACCOUNT_ID') != PORTAL_ID:
        raise LivePreflightError('Wrong configured developer test portal')
    token = env.get('HUBSPOT_SERVICE_KEY', '')
    live = fetch_live(token, PORTAL_ID, fetcher)
    import psycopg
    config = local_pg_settings(env)
    with psycopg.connect(**config, options='-c default_transaction_read_only=on') as conn:
        with conn.cursor() as cur:
            baseline = read_baseline(cur)
    changed = [rid for rid, row in live['records']['contacts'].items()
               if rid in baseline['records']['contacts']
               and row['updated_at'] != baseline['records']['contacts'][rid]['updated_at']]
    history = fetch_selected_history(live, token, fetcher) if changed else None
    return correlate(live, baseline, history, datetime.now(timezone.utc).isoformat())


def save_report(data: dict) -> str:
    dest = ROOT / 'private_exports' / 'm5c' / 'property_history_diagnostics.json'
    dest.parent.mkdir(parents=True, exist_ok=True)
    scratch = None
    try:
        with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=dest.parent,
                                         prefix='.m5c-', suffix='.tmp', delete=False) as stream:
            scratch = Path(stream.name)
            json.dump(data, stream, indent=2, sort_keys=True, ensure_ascii=True)
            stream.write('\n')
        os.replace(scratch, dest)
    finally:
        if scratch and scratch.exists():
            scratch.unlink()
    return 'private_exports/m5c/property_history_diagnostics.json'


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--check', action='store_true')
    mode.add_argument('--report', action='store_true')
    args = parser.parse_args()
    try:
        report = perform(local_env())
        print('M5c PROPERTY HISTORY DIAGNOSTICS (HubSpot GET / PostgreSQL READ ONLY)')
        print(f'STATUS={report["status"]} | M5A={report["m5a_status"]} | M5B={report["m5b_status"]}')
        print('contact_timestamps_changed=' + str(report['changed_contacts'])
              + ' | history_available=' + str(report['contacts_with_selected_history'])
              + ' | near_update_history=' + str(report['contacts_with_near_update_history'])
              + ' | GETs=' + str(report['hubspot_get_count']))
        for row in report['history_details']:
            print(row['alias'] + ': selected_versions=' + str(row['history_versions_returned'])
                  + ' | near_update_events=' + str(row['near_update_event_count'])
                  + ' | source_classes=' + ','.join(row['near_update_source_classes']))
        print('NO CAUSE CONFIRMED | M5A DRIFT PRESERVED | NO BASELINE RESET')
        print('CRM_WRITES=0 | POSTGRES_WRITES=0 | AIRTABLE_WRITES=0 | MERGES=0')
        if args.report:
            print('Local ignored report: ' + save_report(report))
        return 3 if report['m5a_status'] == 'DRIFT_REQUIRES_REVIEW' else 0
    except (LivePreflightError, HTTPError, URLError, OSError, ValueError, RuntimeError, TypeError, KeyError) as exc:
        # Do not echo upstream errors or URLs; they could contain sensitive data.
        print('FAIL CLOSED: M5c ' + type(exc).__name__ + '; no CRM/DB writes or baseline reset')
        return 1


if __name__ == '__main__':
    sys.exit(main())
