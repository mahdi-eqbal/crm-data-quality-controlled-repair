"""M5a: bounded GET-only developer-test HubSpot observation vs stored M1b baseline.

NO CRM changes, NO database writes, NO approvals or mapping from synthetic IDs.
Report contains counts and digests only, never contact fields or record IDs.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from urllib.parse import urlencode, quote

PORTAL_ID = '149703596'
ACCOUNT_URL = 'https://api.hubapi.com/account-info/2026-03/details'
OBJECTS_URL = 'https://api.hubapi.com/crm/objects/2026-03'
ASSOCIATION_URL = 'https://api.hubapi.com/crm/v4/objects/contacts'
FIELDS = {'contacts': ('firstname', 'lastname', 'email', 'phone'),
          'companies': ('name', 'domain', 'country', 'phone')}
MAX_RECORDS = 10  # Deliberately limited to the existing small developer test account.
MAX_ASSOCIATIONS_PER_CONTACT = 500
MAX_HTTP_GET = 3 + MAX_RECORDS  # account + 2 object lists + <=10 associations
HEX_SHA = re.compile(r'^[0-9a-f]{64}$')
ID_RE = re.compile(r'^[1-9][0-9]{0,18}$')


class LivePreflightError(ValueError):
    """Fail closed; caller must not print upstream error bodies or tokens."""


def _instant(value):
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
        except ValueError:
            raise LivePreflightError('Invalid source timestamp') from None
    else:
        raise LivePreflightError('Source timestamp missing')
    if dt.tzinfo is None:
        raise LivePreflightError('Naive timestamp is not accepted')
    return dt.astimezone(timezone.utc).isoformat(timespec='microseconds')


def _sha(payload):
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',', ':'),
                                     ensure_ascii=False).encode('utf-8')).hexdigest()


def _id(value):
    value = str(value) if isinstance(value, (int, str)) and not isinstance(value, bool) else ''
    if not ID_RE.fullmatch(value):
        raise LivePreflightError('Unexpected HubSpot record ID')
    return value


def _types(rows):
    if rows is None:
        rows = []
    if not isinstance(rows, list):
        raise LivePreflightError('Invalid association types')
    unique = {}
    for t in rows:
        if not isinstance(t, dict) or not isinstance(t.get('category'), str) or not isinstance(t.get('typeId'), int) or isinstance(t['typeId'], bool) or not (0 <= t['typeId'] < 10000000) or (t.get('label') is not None and not isinstance(t.get('label'), str)):
            raise LivePreflightError('Invalid association type entry')
        key = (t['category'], t['typeId'])
        item = {'category': t['category'], 'typeId': t['typeId'], 'label': t.get('label')}
        if key in unique and unique[key] != item:
            raise LivePreflightError('Conflicting association labels')
        unique[key] = item
    return sorted(unique.values(), key=lambda x: (x['category'], x['typeId']))


def _page_complete(payload, name):
    if not isinstance(payload, dict) or not isinstance(payload.get('results'), list):
        raise LivePreflightError('Invalid '+name+' response shape')
    paging = payload.get('paging')
    if paging is not None:
        if not isinstance(paging, dict):
            raise LivePreflightError('Invalid pagination metadata')
        if paging.get('next') is not None:
            raise LivePreflightError('Pagination would exceed bounded preflight: no partial read')
    return payload['results']


def fetch_live(token: str, configured_portal: str, get_json) -> dict:
    """Fetch <=13 GETs. Any failed/missing/partial response refuses comparison.

    `get_json(url, token)` is injected so tests can guarantee zero network calls.
    """
    if configured_portal != PORTAL_ID or not isinstance(token, str) or len(token) < 15:
        raise LivePreflightError('Wrong test account configuration or missing key')
    details = get_json(ACCOUNT_URL, token)
    if not isinstance(details, dict) or str(details.get('portalId')) != PORTAL_ID:
        raise LivePreflightError('Account identity not independently verified')
    records = {}
    for kind, props in FIELDS.items():
        url = f'{OBJECTS_URL}/{kind}?{urlencode({"limit": MAX_RECORDS, "properties": ",".join(props)})}'
        result = {}
        for raw in _page_complete(get_json(url, token), kind):
            if not isinstance(raw, dict):
                raise LivePreflightError('Unexpected object row')
            key = _id(raw.get('id'))
            if key in result:
                raise LivePreflightError('Repeated object ID')
            src = raw.get('properties')
            if not isinstance(src, dict) or raw.get('archived') is True:
                raise LivePreflightError('Invalid or archived object row')
            properties = {f: src.get(f) for f in props}
            if any(val is not None and not isinstance(val, str) for val in properties.values()):
                raise LivePreflightError('Invalid CRM property type')
            result[key] = {'updated_at': _instant(raw.get('updatedAt')),
                           'properties': properties}
        if len(result) > MAX_RECORDS:
            raise LivePreflightError('Object safety cap exceeded')
        records[kind] = result
    links = {}
    for cid in sorted(records['contacts']):
        url = f'{ASSOCIATION_URL}/{quote(cid, safe="")}/associations/companies?limit={MAX_ASSOCIATIONS_PER_CONTACT}'
        response = _page_complete(get_json(url, token), 'associations')
        if len(response) > MAX_ASSOCIATIONS_PER_CONTACT:
            raise LivePreflightError('Association safety cap exceeded')
        for item in response:
            if not isinstance(item, dict):
                raise LivePreflightError('Invalid association row')
            company_id = _id(item.get('toObjectId'))
            if company_id not in records['companies']:
                raise LivePreflightError('Association target outside complete company set')
            key = (cid, company_id)
            types = _types(item.get('associationTypes'))
            if key in links:
                # Never silently replace labels from a repeated relationship.
                raise LivePreflightError('Repeated association pair')
            links[key] = types
    return {'verified_portal': PORTAL_ID, 'records': records, 'links': links,
            'http_get_count': 3 + len(records['contacts'])}


def read_baseline(cur) -> dict:
    """Read latest independently verified COMPLETE M1b snapshot; no SQL mutations."""
    cur.execute('''SELECT r.run_id,r.contact_count,r.company_count,st.checked_contact_count,
                          st.link_count,st.contacts_without_company
                   FROM crm_snapshot_runs r JOIN crm_association_run_stats st ON st.run_id=r.run_id
                   WHERE r.source_system='hubspot_test' AND r.configured_account_id=%s
                         AND st.verified_portal_id=%s
                   ORDER BY r.completed_at DESC,r.run_id DESC LIMIT 1''', (int(PORTAL_ID), int(PORTAL_ID)))
    run = cur.fetchone()
    if not run:
        raise LivePreflightError('No verified M1b baseline found in local PostgreSQL')
    run_id, nc, np, checked, nlinks, unlinked = run
    if checked != nc or nc < 0 or np < 0 or nlinks < 0 or unlinked < 0 or unlinked > nc or nc > MAX_RECORDS or np > MAX_RECORDS:
        raise LivePreflightError('Inconsistent stored baseline manifest')
    cur.execute('''SELECT object_type,hubspot_record_id,source_updated_at,properties,record_hash
                   FROM crm_record_snapshots WHERE run_id=%s''', (run_id,))
    records = {'contacts': {}, 'companies': {}}
    for kind, rid, updated, properties, record_hash in cur.fetchall():
        if kind not in records or not isinstance(properties, dict):
            raise LivePreflightError('Invalid stored object row')
        rid = _id(rid)
        if rid in records[kind] or set(properties) != set(FIELDS[kind]) or any(v is not None and not isinstance(v, str) for v in properties.values()) or not isinstance(record_hash, str) or not HEX_SHA.fullmatch(record_hash) or record_hash != _sha(properties):
            raise LivePreflightError('Stored record duplicate, property mismatch or corrupt digest')
        records[kind][rid] = {'updated_at': _instant(updated), 'properties': properties}
    if len(records['contacts']) != nc or len(records['companies']) != np:
        raise LivePreflightError('Incomplete stored object baseline')
    cur.execute('''SELECT contact_id,company_id,association_types
                   FROM crm_association_snapshots WHERE run_id=%s''', (run_id,))
    links = {}
    for cid, pid, assoc_types in cur.fetchall():
        cid, pid = _id(cid), _id(pid)
        if cid not in records['contacts'] or pid not in records['companies'] or (cid, pid) in links:
            raise LivePreflightError('Stored association references unknown or repeated object')
        links[(cid, pid)] = _types(assoc_types)
    if len(links) != nlinks or (nc - len({x[0] for x in links})) != unlinked:
        raise LivePreflightError('Incomplete stored association baseline')
    return {'baseline_run_id': str(run_id), 'records': records, 'links': links}


def compare(live: dict, baseline: dict, observed_at: str) -> dict:
    """Aggregate-only comparison; never return raw properties or CRM record IDs."""
    if live.get('verified_portal') != PORTAL_ID or not isinstance(baseline.get('baseline_run_id'), str):
        raise LivePreflightError('Cannot compare unverified source or baseline')
    metrics = {}
    for kind in FIELDS:
        current = live['records'][kind]
        old = baseline['records'][kind]
        added, missing = set(current) - set(old), set(old) - set(current)
        common = set(current) & set(old)
        changed_props = sum(_sha(current[i]['properties']) != _sha(old[i]['properties']) for i in common)
        changed_timestamps = sum(current[i]['updated_at'] != old[i]['updated_at'] for i in common)
        metrics[kind] = {'live': len(current), 'baseline': len(old),
                         'added': len(added), 'removed': len(missing),
                         'changed_properties': changed_props,
                         'changed_updated_at': changed_timestamps}
    live_links, old_links = live['links'], baseline['links']
    assoc_common = set(live_links) & set(old_links)
    metrics['associations'] = {
        'live': len(live_links), 'baseline': len(old_links),
        'added': len(set(live_links) - set(old_links)),
        'removed': len(set(old_links) - set(live_links)),
        'changed_types': sum(live_links[k] != old_links[k] for k in assoc_common),
    }
    drift = sum(v for group in metrics.values() for key, v in group.items()
                if key in ('added', 'removed', 'changed_properties', 'changed_updated_at', 'changed_types')) > 0
    report = {
        'schema_version': 'm5a-1', 'scope': 'hubspot_developer_test_read_only',
        'verified_portal_id': int(PORTAL_ID),
        'baseline_run_id': baseline['baseline_run_id'],
        'observed_at': _instant(observed_at),
        'status': 'DRIFT_REQUIRES_REVIEW' if drift else 'READ_ONLY_IN_SYNC',
        'metrics': metrics, 'http_get_count': live['http_get_count'],
        'actual_approvals': 0, 'crm_writes': 0, 'postgres_writes': 0,
        'airtable_writes': 0, 'merges': 0, 'write_authorized': False,
        'notes': 'Observational comparison only; not an atomic CRM snapshot, execution preflight, approval, or permission to repair.'
    }
    report['report_sha256'] = _sha(report)
    return report
