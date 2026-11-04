"""HubSpot test account -> local PostgreSQL snapshots. GET-only CRM access.

No CRM writes, no merge, no association updates. No PII printed to stdout.
Requires a dedicated test account and local PostgreSQL; not production ready.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
API_BASE = 'https://api.hubapi.com/crm/objects/2026-03'
VERSION = '2026-03'
PROPERTIES = {
    'contacts': ['firstname', 'lastname', 'email', 'phone'],
    'companies': ['name', 'domain', 'country', 'phone'],
}
PAGE_LIMIT = 100
MAX_RECORDS_PER_OBJECT = 1000  # Safety cap for the initial test-account milestone.
MAX_PAGES = 20


def local_env() -> dict[str, str]:
    values: dict[str, str] = {}
    env_file = ROOT / '.env'
    if env_file.is_file():
        for raw in env_file.read_text(encoding='utf-8-sig').splitlines():
            line = raw.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            name, val = line.split('=', 1)
            values[name.strip()] = val.strip().strip('"').strip("'")
    # Environment variables override local file.
    values.update(os.environ)
    return values


def pg_config(env: dict[str, str]) -> dict:
    missing = [k for k in ('PGPASSWORD',) if not env.get(k)]
    if missing:
        raise ValueError('Missing PGPASSWORD in local .env')
    return {
        'host': env.get('PGHOST', '127.0.0.1'),
        'port': int(env.get('PGPORT', '5433')),
        'dbname': env.get('PGDATABASE', 'crm_data_quality'),
        'user': env.get('PGUSER', 'crm_quality'),
        'password': env['PGPASSWORD'],
        'connect_timeout': 8,
    }


def safe_properties(item: dict, kind: str) -> dict:
    props = item.get('properties') or {}
    if not isinstance(props, dict):
        raise ValueError('Invalid properties response')
    return {name: props.get(name) for name in PROPERTIES[kind]}


def digest(record: dict) -> str:
    payload = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


def request_page(kind: str, token: str, after: str | None) -> dict:
    query: dict[str, str | int] = {'limit': PAGE_LIMIT, 'properties': ','.join(PROPERTIES[kind])}
    if after:
        query['after'] = after
    url = f'{API_BASE}/{kind}?{urlencode(query)}'
    req = Request(url, headers={'Authorization': 'Bearer ' + token,
                                'Accept': 'application/json'}, method='GET')
    for attempt in range(3):
        try:
            with urlopen(req, timeout=25) as response:
                payload = json.load(response)
            if not isinstance(payload, dict) or not isinstance(payload.get('results'), list):
                raise ValueError('Unexpected HubSpot API response shape')
            return payload
        except HTTPError as exc:
            if exc.code in (429, 500, 502, 503, 504) and attempt < 2:
                time.sleep(2 ** attempt)
                continue
            raise RuntimeError(f'HubSpot {kind} GET failed (HTTP {exc.code}); no data saved') from None
        except (URLError, TimeoutError, OSError):
            if attempt < 2:
                time.sleep(2 ** attempt)
                continue
            raise RuntimeError(f'HubSpot {kind} GET network error; no data saved') from None
    raise RuntimeError('Unreachable retry state')


def collect(kind: str, token: str) -> list[dict]:
    records: list[dict] = []
    record_ids: set[str] = set()
    seen_cursors: set[str] = set()
    cursor = None
    for _ in range(MAX_PAGES):
        response = request_page(kind, token, cursor)
        for raw in response['results']:
            if not isinstance(raw, dict) or not raw.get('id'):
                raise ValueError('Record missing ID: refusing to snapshot')
            record_id = str(raw['id'])
            if record_id in record_ids:
                raise ValueError('Duplicate record ID across pages: refusing to snapshot')
            record_ids.add(record_id)
            records.append({
                'id': record_id,
                'updated_at': raw.get('updatedAt'),
                'observed_at': datetime.now(timezone.utc),
                'properties': safe_properties(raw, kind),
            })
        if len(records) > MAX_RECORDS_PER_OBJECT:
            raise ValueError('Safety cap exceeded (>1000 rows); no snapshots committed')
        next_obj = (response.get('paging') or {}).get('next') or {}
        cursor = next_obj.get('after')
        if not cursor:
            return records
        if cursor in seen_cursors:
            raise ValueError('Repeated pagination cursor; no snapshots committed')
        seen_cursors.add(cursor)
        time.sleep(0.15)
    raise ValueError('Maximum page limit exceeded; no snapshots committed')


def init_db(env: dict[str, str]) -> None:
    import psycopg
    sql = (ROOT / 'sql' / '001_m1_snapshots.sql').read_text(encoding='utf-8')
    with psycopg.connect(**pg_config(env)) as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
    print('PASS: PostgreSQL schema initialized (no HubSpot calls)')


def snapshot(env: dict[str, str]) -> None:
    import psycopg
    token = env.get('HUBSPOT_SERVICE_KEY', '')
    account_id = env.get('HUBSPOT_ACCOUNT_ID', '')
    if not token or token == 'PASTE_YOUR_KEY_HERE':
        raise ValueError('Missing HUBSPOT_SERVICE_KEY in local .env')
    if account_id != '149703596':
        raise ValueError('Expected dedicated test account HUBSPOT_ACCOUNT_ID=149703596')

    print('Fetching CRM records via GET only (no CRM changes)...')
    # Do not write any partial snapshots if either full extraction fails.
    started_at = datetime.now(timezone.utc)
    data = {kind: collect(kind, token) for kind in PROPERTIES}
    run_id = uuid.uuid4()
    with psycopg.connect(**pg_config(env)) as conn:
        with conn.cursor() as cur:
            cur.execute('''INSERT INTO crm_snapshot_runs
                (run_id, source_system, configured_account_id, started_at, contact_count,
                 company_count, api_version)
                VALUES (%s,'hubspot_test',%s,%s,%s,%s,%s)''',
                (run_id, int(account_id), started_at,
                 len(data['contacts']), len(data['companies']), VERSION))
            for kind, items in data.items():
                for item in items:
                    cur.execute('''INSERT INTO crm_record_snapshots
                        (run_id,object_type,hubspot_record_id,source_updated_at,observed_at,
                         properties,record_hash) VALUES (%s,%s,%s,%s,%s,%s,%s)''',
                        (run_id, kind, item['id'], item['updated_at'], item['observed_at'],
                         psycopg.types.json.Jsonb(item['properties']), digest(item['properties'])))
    print('PASS: complete read-only snapshot committed to local PostgreSQL')
    print(f'run_id={run_id} | contacts={len(data["contacts"])} | companies={len(data["companies"])}')
    print('Configured account ID is locally supplied, not independently verified by this script.')


def status(env: dict[str, str]) -> None:
    import psycopg
    with psycopg.connect(**pg_config(env)) as conn:
        with conn.cursor() as cur:
            cur.execute('''SELECT r.run_id, r.completed_at, r.contact_count, r.company_count,
                               COUNT(s.*)
                        FROM crm_snapshot_runs r
                        LEFT JOIN crm_record_snapshots s ON s.run_id=r.run_id
                        GROUP BY r.run_id
                        ORDER BY r.completed_at DESC LIMIT 3''')
            rows = cur.fetchall()
    if not rows:
        print('No completed snapshots found')
    for run_id, time_at, contact_count, company_count, stored in rows:
        expected = contact_count + company_count
        state = 'PASS' if stored == expected else 'MISMATCH'
        print(f'{state}: {run_id} | contacts={contact_count} | companies={company_count} '
              f'| stored={stored}/{expected} | at={time_at.isoformat()}')


def main() -> int:
    parser = argparse.ArgumentParser(description='HubSpot test account M1 read-only snapshot')
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--init-db', action='store_true')
    action.add_argument('--snapshot', action='store_true')
    action.add_argument('--status', action='store_true')
    args = parser.parse_args()
    try:
        env = local_env()
        if args.init_db:
            init_db(env)
        elif args.snapshot:
            snapshot(env)
        else:
            status(env)
        return 0
    except Exception as exc:
        # Avoid leaking database credentials, authorization headers or CRM properties.
        print(f'FAIL: {type(exc).__name__}; see local documentation and check configuration.')
        return 1


if __name__ == '__main__':
    sys.exit(main())
