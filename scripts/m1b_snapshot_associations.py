"""M1b: strict-account-verified, GET-only HubSpot relationship snapshot.

HubSpot is never modified. Writes only append snapshots to local PostgreSQL.
Requires the M1a and M1b read-only probe modules in scripts/.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urlencode

from m1_snapshot_hubspot import collect, digest, local_env, pg_config
from m1b_probe_associations import (
    ASSOCIATION_BASE, EXPECTED_PORTAL_ID, MAX_ASSOC_PAGES,
    get_json, verify_account,
)

ROOT = Path(__file__).resolve().parents[1]
MAX_TOTAL_LINKS = 5000


def normalize_types(rows: object) -> list[dict]:
    """Retain labels and category/typeId without trusting human-readable labels."""
    if rows is None:
        rows = []
    if not isinstance(rows, list):
        raise ValueError('Unexpected associationTypes field')
    types = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError('Unexpected association type')
        category, type_id = row.get('category'), row.get('typeId')
        label = row.get('label')
        if not isinstance(category, str) or not isinstance(type_id, int):
            raise ValueError('Association type missing category/typeId')
        if label is not None and not isinstance(label, str):
            raise ValueError('Invalid association label')
        types[(category, type_id)] = {
            'category': category, 'typeId': type_id, 'label': label
        }
    return sorted(types.values(), key=lambda x: (x['category'], x['typeId']))


def get_links(contact_id: str, token: str) -> dict[str, list[dict]]:
    """Read all pages; dedupe each company and retain its association labels."""
    links: dict[str, dict[tuple[str, int], dict]] = {}
    seen_cursors: set[str] = set()
    cursor = None
    for _ in range(MAX_ASSOC_PAGES):
        params = {'limit': 500}
        if cursor:
            params['after'] = cursor
        url = (f'{ASSOCIATION_BASE}/{quote(contact_id, safe="")}'
               f'/associations/companies?{urlencode(params)}')
        payload = get_json(url, token)
        results = payload.get('results')
        if not isinstance(results, list):
            raise ValueError('Association response missing results list')
        for entry in results:
            if not isinstance(entry, dict) or entry.get('toObjectId') is None:
                raise ValueError('Association result missing company ID')
            company_id = str(entry['toObjectId'])
            if not company_id:
                raise ValueError('Empty company ID')
            known = links.setdefault(company_id, {})
            for typ in normalize_types(entry.get('associationTypes')):
                known[(typ['category'], typ['typeId'])] = typ
        if len(links) > MAX_TOTAL_LINKS:
            raise ValueError('Association link safety cap exceeded')
        cursor = ((payload.get('paging') or {}).get('next') or {}).get('after')
        if not cursor:
            return {cid: sorted(items.values(), key=lambda t: (t['category'], t['typeId']))
                    for cid, items in links.items()}
        if cursor in seen_cursors:
            raise ValueError('Repeated association cursor')
        seen_cursors.add(cursor)
        time.sleep(0.15)
    raise ValueError('Association pagination cap reached; nothing committed')


def make_relationships(contacts: list[dict], companies: list[dict], token: str) -> list[dict]:
    """Reject associations that point outside this same extracted company snapshot."""
    company_ids = {item['id'] for item in companies}
    links = []
    for item in contacts:
        for company_id, labels in get_links(item['id'], token).items():
            if company_id not in company_ids:
                raise ValueError('Association references a company missing from this snapshot; retry later')
            links.append({'contact_id': item['id'], 'company_id': company_id,
                          'association_types': labels, 'observed_at': datetime.now(timezone.utc)})
            if len(links) > MAX_TOTAL_LINKS:
                raise ValueError('Too many association links; no snapshots committed')
    return links


def assert_safe_env(env: dict[str, str]) -> str:
    if env.get('HUBSPOT_ACCOUNT_ID') != EXPECTED_PORTAL_ID:
        raise ValueError('Wrong local HubSpot account ID')
    if not env.get('HUBSPOT_SERVICE_KEY') or env['HUBSPOT_SERVICE_KEY'] == 'PASTE_YOUR_KEY_HERE':
        raise ValueError('Missing HubSpot service key')
    if not env.get('PGPASSWORD'):
        raise ValueError('Missing local database password')
    return env['HUBSPOT_SERVICE_KEY']


def init_db(env: dict[str, str]) -> None:
    import psycopg
    sql = (ROOT / 'sql' / '002_m1b_association_snapshots.sql').read_text(encoding='utf-8')
    with psycopg.connect(**pg_config(env)) as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
    print('PASS: association snapshot table initialized locally; no HubSpot calls')


def snapshot(env: dict[str, str]) -> None:
    token = assert_safe_env(env)
    print('Verifying source portal and reading CRM via GET only...')
    # Fail-closed. No snapshots are made when independent account verification fails.
    if verify_account(token) != 'VERIFIED':
        raise ValueError('Account identity not independently verified; refusing DB snapshot')
    # Fetch every required object and association before opening DB transaction.
    started = datetime.now(timezone.utc)
    records = {kind: collect(kind, token) for kind in ('contacts', 'companies')}
    relationships = make_relationships(records['contacts'], records['companies'], token)
    run_id = uuid.uuid4()
    import psycopg
    from psycopg.types.json import Jsonb
    with psycopg.connect(**pg_config(env)) as conn:
        with conn.cursor() as cur:
            cur.execute('''INSERT INTO crm_snapshot_runs
                (run_id, source_system, configured_account_id, started_at,
                 contact_count, company_count, api_version)
                VALUES (%s,'hubspot_test',%s,%s,%s,%s,%s)''',
                (run_id, int(EXPECTED_PORTAL_ID), started,
                 len(records['contacts']), len(records['companies']), '2026-03'))
            for kind, items in records.items():
                for item in items:
                    cur.execute('''INSERT INTO crm_record_snapshots
                        (run_id, object_type, hubspot_record_id, source_updated_at,
                         observed_at, properties, record_hash)
                        VALUES (%s,%s,%s,%s,%s,%s,%s)''',
                        (run_id, kind, item['id'], item['updated_at'], item['observed_at'],
                         Jsonb(item['properties']), digest(item['properties'])))
            cur.execute('''INSERT INTO crm_association_run_stats
                (run_id, verified_portal_id, checked_contact_count, link_count, contacts_without_company)
                VALUES (%s,%s,%s,%s,%s)''',
                (run_id, int(EXPECTED_PORTAL_ID), len(records['contacts']),
                 len(relationships), len(records['contacts']) - len({r['contact_id'] for r in relationships})))
            for link in relationships:
                cur.execute('''INSERT INTO crm_association_snapshots
                    (run_id, contact_id, company_id, association_types, observed_at)
                    VALUES (%s,%s,%s,%s,%s)''',
                    (run_id, link['contact_id'], link['company_id'],
                     Jsonb(link['association_types']), link['observed_at']))
    with_links = len({r['contact_id'] for r in relationships})
    print(f'PASS: complete record + association snapshot committed | run_id={run_id}')
    print(f'contacts={len(records["contacts"])} | companies={len(records["companies"])} '
          f'| links={len(relationships)} | contacts_without_company={len(records["contacts"])-with_links}')
    print('HubSpot writes=0; only local PostgreSQL was modified')


def status(env: dict[str, str]) -> None:
    import psycopg
    with psycopg.connect(**pg_config(env)) as conn:
        with conn.cursor() as cur:
            cur.execute('''SELECT r.run_id, r.contact_count, r.company_count,
                                 st.checked_contact_count, st.link_count, st.contacts_without_company,
                                 (SELECT COUNT(*) FROM crm_record_snapshots s WHERE s.run_id = r.run_id),
                                 (SELECT COUNT(*) FROM crm_association_snapshots a WHERE a.run_id = r.run_id)
                          FROM crm_snapshot_runs r
                          JOIN crm_association_run_stats st ON st.run_id = r.run_id
                          ORDER BY r.completed_at DESC LIMIT 3''')
            rows = cur.fetchall()
    if not rows:
        print('No M1b association snapshots found')
    for run_id, contacts, companies, checked, expected_links, unlinked, stored, actual_links in rows:
        result = 'PASS' if (stored == contacts + companies
                            and actual_links == expected_links and checked == contacts) else 'MISMATCH'
        print(f'{result}: run_id={run_id} | contacts={contacts} | companies={companies} '
              f'| stored_records={stored}/{contacts+companies} | links={actual_links}/{expected_links} '
              f'| contacts_without_company={unlinked}')


def main() -> int:
    parser = argparse.ArgumentParser(description='M1b HubSpot association snapshots (GET only)')
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument('--init-db', action='store_true')
    actions.add_argument('--snapshot', action='store_true')
    actions.add_argument('--status', action='store_true')
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
        # Never print database connection errors (may embed DSNs/secrets), URLs or PII.
        print(f'FAIL: {type(exc).__name__}; no HubSpot writes attempted')
        return 1


if __name__ == '__main__':
    sys.exit(main())
