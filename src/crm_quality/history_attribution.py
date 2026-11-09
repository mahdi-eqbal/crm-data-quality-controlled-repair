"""M5c: bounded, privacy-minimizing contact property-history correlation.

This is an observational diagnostic, NOT an attribution proof, approval or
permission to change CRM. No network or database access in this pure module.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone, timedelta
from urllib.parse import urlencode

from crm_quality.live_preflight import (
    LivePreflightError, OBJECTS_URL, PORTAL_ID, MAX_RECORDS,
    _id, _instant, _page_complete, _sha,
)
from crm_quality.timestamp_diagnostics import diagnose

SCHEMA = 'm5c-1'
# Small, intentionally non-contact-value selection. History of these fields
# cannot explain all possible causes of HubSpot record.updatedAt changes.
HISTORY_FIELDS = ('hs_lastmodifieddate', 'lifecyclestage', 'hs_lead_status')
MAX_VERSIONS_PER_FIELD = 100
MAX_EXTRA_GETS = 1
MATCH_TOLERANCE_SECONDS = 5
CATEGORIES = frozenset({'CRM_UI', 'INTEGRATION', 'WORKFLOWS', 'AUTOMATION', 'API', 'CONTACTS', 'IMPORT', 'FORM'})


def _time(value):
    return datetime.fromisoformat(_instant(value))


def _category(value):
    """Allowlist the category; NEVER include raw sourceType/sourceId/user IDs."""
    if not isinstance(value, str):
        return 'OTHER_OR_UNKNOWN'
    return value if value in CATEGORIES else 'OTHER_OR_UNKNOWN'


def _validated_versions(value):
    if not isinstance(value, list) or len(value) > MAX_VERSIONS_PER_FIELD:
        raise LivePreflightError('Invalid or oversized property history')
    results = []
    for item in value:
        if not isinstance(item, dict) or 'timestamp' not in item:
            raise LivePreflightError('Malformed history version')
        timestamp = _time(item['timestamp'])
        if 'sourceType' in item and item['sourceType'] is not None and not isinstance(item['sourceType'], str):
            raise LivePreflightError('Malformed source category')
        # NEVER preserve item['value'], item['sourceId'] or item['updatedByUserId'].
        results.append((timestamp, _category(item.get('sourceType'))))
    return results


def fetch_selected_history(live: dict, token: str, get_json) -> dict:
    """A SINGLE extra GET for all contacts; validate snapshot consistency.

    Unchanged timestamps/IDs are mandatory; concurrent modifications abort.
    History may be missing or incomplete; this MUST NOT be treated as proof.
    """
    if not isinstance(live, dict) or live.get('verified_portal') != PORTAL_ID:
        raise LivePreflightError('Unverified live source')
    contacts = live.get('records', {}).get('contacts')
    if not isinstance(contacts, dict) or len(contacts) > MAX_RECORDS or not contacts:
        raise LivePreflightError('Unexpected live contact set')
    if not isinstance(token, str) or len(token) < 15:
        raise LivePreflightError('Missing service key')
    params = urlencode({'limit': MAX_RECORDS, 'properties': ','.join(HISTORY_FIELDS),
                        'propertiesWithHistory': ','.join(HISTORY_FIELDS)})
    url = f'{OBJECTS_URL}/contacts?{params}'
    payload = get_json(url, token)
    results = _page_complete(payload, 'contact property histories')
    if len(results) > MAX_RECORDS:
        raise LivePreflightError('History request exceeded max contacts')
    parsed = {}
    for item in results:
        if not isinstance(item, dict) or item.get('archived') is True:
            raise LivePreflightError('Malformed or archived history contact')
        rid = _id(item.get('id'))
        if rid in parsed or rid not in contacts:
            raise LivePreflightError('Unexpected or repeated history contact')
        if _instant(item.get('updatedAt')) != _instant(contacts[rid]['updated_at']):
            raise LivePreflightError('Concurrent record update between observations')
        props = item.get('propertiesWithHistory')
        if props is None:
            props = {}
        if not isinstance(props, dict) or set(props) - set(HISTORY_FIELDS):
            raise LivePreflightError('Unexpected property history structure')
        parsed[rid] = {name: _validated_versions(props[name]) for name in HISTORY_FIELDS if name in props}
    if set(parsed) != set(contacts):
        raise LivePreflightError('Contact set changed between observations')
    return parsed


def correlate(live: dict, baseline: dict, history: dict | None, observed_at: str) -> dict:
    """Only summarize time correlation, never identify the actor or cause."""
    diag = diagnose(live, baseline, observed_at=observed_at)
    shared = sorted(set(live['records']['contacts']) & set(baseline['records']['contacts']), key=int)
    changed = [key for key in shared if _instant(live['records']['contacts'][key]['updated_at'])
               != _instant(baseline['records']['contacts'][key]['updated_at'])]
    if diag['contact_count']['timestamps_changed'] != len(changed):
        raise LivePreflightError('M5b timestamp diagnostic mismatch')
    if changed and (not isinstance(history, dict) or set(history) != set(live['records']['contacts'])):
        raise LivePreflightError('Incomplete contact history observation')
    if not changed and history is not None:
        raise LivePreflightError('Unnecessary history observation for unchanged contacts')
    rows = []
    correlated = 0
    available = 0
    tol = timedelta(seconds=MATCH_TOLERANCE_SECONDS)
    for idx, rid in enumerate(changed, 1):
        earlier = _time(baseline['records']['contacts'][rid]['updated_at'])
        later = _time(live['records']['contacts'][rid]['updated_at'])
        props = history[rid]
        versions = [x for k in HISTORY_FIELDS for x in props.get(k, [])]
        if versions:
            available += 1
        # Correlation means event inside baseline->observed interval near the
        # observed updatedAt; earlier timestamps are excluded.
        near = [(t, c) for (t, c) in versions if earlier < t <= later + tol
                and abs((t - later).total_seconds()) <= MATCH_TOLERANCE_SECONDS]
        if near:
            correlated += 1
        rows.append({
            'alias': f'changed_contact_{idx:02d}',
            'history_versions_returned': len(versions),
            'selected_properties_with_versions': sum(bool(props.get(k)) for k in HISTORY_FIELDS),
            'near_update_event_count': len(near),
            'near_update_source_classes': sorted({c for _, c in near}),
            'temporal_correlation_only': bool(near),
        })
    if not changed:
        status = 'NO_CONTACT_TIMESTAMP_DRIFT'
    elif correlated:
        status = 'HISTORY_CORRELATION_OBSERVED_NO_CAUSAL_PROOF'
    elif not available:
        status = 'HISTORY_UNAVAILABLE_FOR_SELECTED_PROPERTIES'
    else:
        status = 'NO_NEAR_HISTORY_IN_SELECTED_PROPERTIES'
    result = {
        'schema_version': SCHEMA,
        'scope': 'verified_developer_test_contact_history_read_only',
        'status': status,
        'm5a_status': diag['m5a_status'],
        'm5b_status': diag['status'],
        'baseline_run_id': diag['baseline_run_id'],
        'observed_at_utc': _instant(observed_at),
        'changed_contacts': len(changed),
        'selected_property_names': list(HISTORY_FIELDS),
        'contacts_with_selected_history': available,
        'contacts_with_near_update_history': correlated,
        'history_details': rows,
        'other_drift_count': diag['other_drift_count'],
        'hubspot_get_count': live['http_get_count'] + int(bool(changed)),
        'extra_history_get_count': int(bool(changed)),
        'crm_writes': 0, 'postgres_writes': 0, 'airtable_writes': 0,
        'merges': 0, 'approvals': 0, 'write_authorized': False,
        'cause_confirmed': False, 'baseline_reset': False,
        'limitations': [
            'Selected property histories are a narrow, potentially incomplete subset of CRM change history.',
            'Temporal proximity and sourceType categories do not prove who or what caused record.updatedAt to change.',
            'No raw history values, user IDs, record IDs, source IDs, contact fields, or bearer tokens are reported.',
            'No new baseline is created and the M5a drift flag remains unchanged.',
        ],
    }
    result['report_sha256'] = _sha(result)
    return result
