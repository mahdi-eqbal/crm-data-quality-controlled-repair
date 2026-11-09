"""M5b: aggregate/aliased timestamp investigation of M5a live GET vs M1b PG baseline.

Pure transformations only. This module cannot authenticate, fetch, query, or mutate CRM.
The diagnostic does not establish cause or an absence of unrequested property changes.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json

from crm_quality.live_preflight import PORTAL_ID, LivePreflightError, compare, _instant

SCHEMA = 'm5b-1'


def _dt(value):
    return datetime.fromisoformat(_instant(value))


def _hash(obj):
    return sha256(json.dumps(obj, ensure_ascii=True, sort_keys=True,
                             separators=(',', ':')).encode('utf-8')).hexdigest()


def diagnose(live: dict, baseline: dict, *, observed_at: str) -> dict:
    """Produce aliased per-contact timestamp pairs and high-level drift classification.

    DO NOT use outcome as a source mutation gate or as evidence of a safe repair.
    Input values remain in memory. No record IDs, names or properties in output.
    """
    # Reuse M5a's complete validation / normalizing comparison, not an alternate
    # partial baseline or fresh API call. Identical input gives identical classification.
    base_report = compare(live, baseline, observed_at)
    if live.get('verified_portal') != PORTAL_ID:
        raise LivePreflightError('Unverified source')
    current = live['records']['contacts']
    old = baseline['records']['contacts']
    shared = sorted(set(current) & set(old), key=lambda x: int(x))
    pairs = []
    # Alias numbering is deliberately only for CHANGED rows, not a stable CRM key.
    for key in shared:
        previous = _dt(old[key]['updated_at'])
        latest = _dt(current[key]['updated_at'])
        if previous == latest:
            continue
        delta = int((latest - previous).total_seconds() * 1000)
        pairs.append({
            'alias': f'changed_contact_{len(pairs) + 1:02d}',
            'baseline_updated_at_utc': previous.isoformat(timespec='microseconds'),
            'live_updated_at_utc': latest.isoformat(timespec='microseconds'),
            'delta_ms': delta,
            'direction': 'later' if delta > 0 else 'earlier',
        })
    if len(pairs) != base_report['metrics']['contacts']['changed_updated_at']:
        raise LivePreflightError('Timestamp comparison was inconsistent')
    other_drift = sum(v for name, group in base_report['metrics'].items()
                      for key, v in group.items()
                      if key in {'added', 'removed', 'changed_properties', 'changed_types'}
                      or (key == 'changed_updated_at' and name != 'contacts'))
    if other_drift:
        classification = 'OTHER_DRIFT_ALSO_PRESENT'
    elif pairs:
        classification = 'TIMESTAMP_ONLY_IN_OBSERVED_SCOPE'
    else:
        classification = 'NO_DETECTED_DRIFT'
    times = [_dt(p['live_updated_at_utc']) for p in pairs]
    span_s = round((max(times) - min(times)).total_seconds(), 3) if len(times) >= 2 else None
    directions = sorted({p['direction'] for p in pairs})
    result = {
        'schema_version': SCHEMA,
        'scope': 'verified_hubspot_developer_test_only',
        'status': classification,
        'm5a_status': base_report['status'],
        'observed_at_utc': _instant(observed_at),
        'baseline_run_id': baseline['baseline_run_id'],
        'contact_count': {'live': len(current), 'baseline': len(old), 'shared': len(shared),
                          'timestamps_changed': len(pairs)},
        'changed_contact_timestamps': pairs,
        'all_changed_timestamps_direction': directions[0] if len(directions) == 1 else ('mixed' if directions else 'none'),
        'changed_live_update_span_seconds': span_s,
        'live_updates_within_5_minutes': len(times) >= 2 and span_s <= 300,
        'other_drift_count': other_drift,
        'm5a_report_sha256': base_report['report_sha256'],
        'http_get_count': base_report['http_get_count'],
        'crm_writes': 0, 'postgres_writes': 0, 'airtable_writes': 0,
        'merges': 0, 'approvals': 0, 'write_authorized': False,
        'limitations': [
            'Only four selected properties per object and the currently returned associations were compared.',
            'A changed updatedAt with identical observed properties does not prove why HubSpot updated the record.',
            'Even clustered timestamps do not establish a common cause or atomic observation.',
            'No new baseline is created and no CRM repair or approval is authorized.',
        ],
    }
    result['diagnostic_sha256'] = _hash(result)
    return result
