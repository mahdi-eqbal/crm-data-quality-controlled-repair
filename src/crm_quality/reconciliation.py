"""M3d: read-only reconciliation of synthetic Airtable decisions and local PostgreSQL.

Pure comparison and forensic consistency checks. No database writes, CRM calls,
Airtable writes, or automated resolution of conflicts.
"""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections import Counter
from datetime import datetime, timezone

# Must equal the deterministic event namespace of M3c decision_sync.py.
EVENT_NAMESPACE = uuid.UUID('54165211-83db-4c8c-a6b4-990c50da2461')
ALLOWED = {'Same Entity', 'Different Entity', 'Needs More Evidence'}
MAX_EVENTS = 500  # bounded synthetic milestone only
STATUS = (
    'in_sync', 'not_reviewed', 'pending_import', 'cleared_in_airtable',
    'stale_airtable', 'same_timestamp_conflict',
)


class ReconcileError(ValueError):
    """Fail closed on untrusted, invalid, or incomplete input."""


def utc_timestamp(v):
    if isinstance(v, datetime):
        dt = v
    elif isinstance(v, str):
        try:
            dt = datetime.fromisoformat(v.replace('Z', '+00:00'))
        except ValueError:
            raise ReconcileError('Invalid event timestamp') from None
    else:
        raise ReconcileError('Missing event timestamp')
    if dt.tzinfo is None:
        raise ReconcileError('Timezone required for event timestamp')
    return dt.astimezone(timezone.utc).isoformat(timespec='microseconds')


def event_fingerprint(event):
    """Recreate exactly the payload hash / UUID used by the M3c writer."""
    payload = {
        'candidate_id': str(event['candidate_id']),
        'airtable_record_id': event['airtable_record_id'],
        'decision': event['decision'],
        'notes': event['notes'],
        'edited_at': utc_timestamp(event['edited_at']),
        'reviewer_id': event['reviewer_id'],
    }
    if not re.fullmatch(r'rec[A-Za-z0-9]{14}', payload['airtable_record_id']):
        raise ReconcileError('Invalid Airtable record ID in journal')
    if not re.fullmatch(r'usr[A-Za-z0-9]{8,50}', payload['reviewer_id']):
        raise ReconcileError('Invalid reviewer provenance in journal')
    if payload['decision'] not in ALLOWED or not isinstance(payload['notes'], str):
        raise ReconcileError('Invalid decision payload in journal')
    if not 8 <= len(payload['notes'].strip()) <= 500:
        raise ReconcileError('Invalid reviewer note length in journal')
    serial = json.dumps(payload, sort_keys=True, ensure_ascii=True, separators=(',', ':'))
    sha = hashlib.sha256(serial.encode('utf-8')).hexdigest()
    event_id = str(uuid.uuid5(EVENT_NAMESPACE, payload['candidate_id'] + ':' + payload['edited_at'] + ':' + sha))
    return sha, event_id


def validate_history(db_events, expected_ids):
    """Validate all stored event hashes, event IDs, timestamps, and ordering."""
    if len(db_events) > MAX_EVENTS:
        raise ReconcileError('Review journal exceeds synthetic test safety cap')
    latest, last_time, last_record_id, seen_events = {}, {}, {}, set()
    counts = Counter()
    for event in db_events:
        cid = str(event['candidate_id'])
        if cid not in expected_ids:
            raise ReconcileError('Decision journal refers to unknown or wrong-batch candidate')
        ts = utc_timestamp(event['edited_at'])
        sha, event_id = event_fingerprint(event)
        if event['payload_sha256'] != sha or str(event['event_id']) != event_id:
            raise ReconcileError('Decision journal contains mismatched event hash or UUID')
        if event_id in seen_events or (cid in last_time and ts <= last_time[cid]):
            raise ReconcileError('Duplicate or out-of-order decision event history')
        if cid in last_record_id and event['airtable_record_id'] != last_record_id[cid]:
            raise ReconcileError('Airtable record provenance changed across decision revisions')
        last_record_id[cid] = event['airtable_record_id']
        seen_events.add(event_id)
        last_time[cid] = ts
        latest[cid] = {
            'edited_at': ts, 'payload_sha256': sha,
            'decision': event['decision'], 'airtable_record_id': event['airtable_record_id'],
        }
        counts[cid] += 1
    return {'latest': latest, 'events': len(db_events), 'classified': len(latest),
            'revisions': sum(n - 1 for n in counts.values())}


def reconcile(snapshot, db_events, plan):
    """Snapshot from M3c prepare_snapshot; journal events already read from local PG."""
    expected = {str(r['candidate_id']): r for r in plan['rows']}
    if (len(expected) != 57 or snapshot.get('total') != 57 or
            snapshot.get('batch_id') != str(plan['batch_id']) or
            not re.fullmatch(r'[a-f0-9]{64}', str(snapshot.get('sha256', '')))):
        raise ReconcileError('Source plan / Airtable snapshot mismatch')
    incoming = {}
    for e in snapshot['decisions']:
        cid = str(e['candidate_id'])
        if cid not in expected or cid in incoming:
            raise ReconcileError('Duplicate or unknown Airtable decision')
        if e['decision'] not in ALLOWED:
            raise ReconcileError('Airtable decision outside accepted statuses')
        sha, eid = event_fingerprint(e)
        if sha != e['payload_sha256'] or eid != str(e['event_id']):
            raise ReconcileError('Invalid validated Airtable event fingerprint')
        if expected[cid]['queue_status'] == 'needs_evidence' and e['decision'] != 'Needs More Evidence':
            raise ReconcileError('Insufficient-evidence candidate has invalid decision')
        incoming[cid] = e
    if len(incoming) + snapshot['not_reviewed'] != 57:
        raise ReconcileError('Incomplete Airtable decision coverage')
    journal = validate_history(db_events, set(expected))
    counts = Counter()
    discrepancies = []
    for cid in sorted(expected):
        a = incoming.get(cid)
        db = journal['latest'].get(cid)
        if a is None and db is None:
            code = 'not_reviewed'
        elif a is None:
            code = 'cleared_in_airtable'
        elif db is None:
            code = 'pending_import'
        else:
            ts_a, ts_db = utc_timestamp(a['edited_at']), db['edited_at']
            if ts_a > ts_db:
                code = 'pending_import'
            elif ts_a < ts_db:
                code = 'stale_airtable'
            elif a['payload_sha256'] != db['payload_sha256']:
                code = 'same_timestamp_conflict'
            else:
                code = 'in_sync'
        counts[code] += 1
        if code not in ('not_reviewed', 'in_sync'):
            row = expected[cid]
            discrepancies.append({
                'candidate_key': f'{row["object_type"]}:{row["record_id_1"]}:{row["record_id_2"]}',
                'status': code,
                'action': 'manual_preview_and_digest_gated_apply' if code == 'pending_import' else 'manual_investigation_required',
            })
    summary = {code: counts[code] for code in STATUS}
    return {
        'schema_version': 'm3d-1',
        'source': 'synthetic_fixture_only',
        'batch_id': str(plan['batch_id']),
        'source_fingerprint': plan['source_fingerprint'],
        'airtable_snapshot_sha256': snapshot['sha256'],
        'candidates': 57,
        'airtable_decisions': len(incoming),
        'postgres_events': journal['events'],
        'postgres_classified_candidates': journal['classified'],
        'postgres_revisions': journal['revisions'],
        'summary': summary,
        'discrepancies': discrepancies,
        'reconciled': not discrepancies,
        'policy': 'read_only_no_crm_writes_no_automatic_resolution',
    }
