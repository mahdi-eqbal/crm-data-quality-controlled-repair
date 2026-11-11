"""A11 evidence-gated, READ-ONLY local/remote delivery reconciliation.

Never equate HTTP 200 Accepted with end-to-end delivery; do not acknowledge,
re-send, clear reservations, modify PostgreSQL, or write to HubSpot/Airtable.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
import re
import uuid

from crm_quality.make_orchestration import (
    NAMESPACE, MakeSafetyError, MAX_SOURCES, digest, utc_time, validate_payload,
)

SCHEMA = 'crm_quality_a11_remote_evidence_v1'
ALLOWED_KINDS = frozenset({'dispatch_reserved', 'processing_acknowledged', 'outcome_uncertain'})
REC_RE = re.compile(r'rec[A-Za-z0-9]{14}\Z')
SHA_RE = re.compile(r'[a-f0-9]{64}\Z')
CASE_RE = re.compile(r'[a-f0-9]{24}\Z')


class ReconciliationError(ValueError):
    """Malformed local evidence; fail closed, never issue a delivery ack."""


def _uuid(value):
    try:
        val = str(uuid.UUID(str(value)))
    except (TypeError, ValueError, AttributeError):
        raise ReconciliationError('Invalid event UUID in evidence') from None
    if val != str(value):
        raise ReconciliationError('Noncanonical event UUID')
    return val


def _sha(value):
    if not isinstance(value, str) or not SHA_RE.fullmatch(value):
        raise ReconciliationError('Invalid SHA256 in evidence')
    return value


def _utc(value):
    try:
        return utc_time(value)
    except (MakeSafetyError, ValueError, TypeError) as exc:
        raise ReconciliationError('Invalid timestamp in evidence') from exc


def _record(row):
    """Verify local authoritative row without exposing the raw payload."""
    required = ('event_id', 'source_layer', 'source_event_id', 'source_sha256',
                'case_ref', 'payload_sha256', 'payload', 'occurred_at')
    if not isinstance(row, dict) or any(k not in row for k in required):
        raise ReconciliationError('Missing outbox columns')
    event_id = _uuid(row['event_id'])
    source_id = _uuid(row['source_event_id'])
    p = row['payload']
    try:
        validate_payload(p)
    except MakeSafetyError as exc:
        raise ReconciliationError('Outbox payload contract invalid') from exc
    expected_id = str(uuid.uuid5(NAMESPACE, f"{row['source_layer']}:{source_id}"))
    if event_id != expected_id or p['event_id'] != event_id:
        raise ReconciliationError('Outbox deterministic event ID mismatch')
    if (row['source_layer'] != p['source_layer'] or
        _sha(row['source_sha256'].strip()) != p['source_evidence_sha256'] or
        _sha(row['payload_sha256'].strip()) != digest(p) or
        row['case_ref'].strip() != p['case_ref'] or
        not CASE_RE.fullmatch(row['case_ref'].strip()) or
        _utc(row['occurred_at']) != p['occurred_at']):
        raise ReconciliationError('Outbox source/digest/provenance mismatch')
    return {'event_id':event_id, 'event_type':p['event_type'],
            'source_layer':p['source_layer'], 'source_evidence_sha256':p['source_evidence_sha256'],
            'case_ref':p['case_ref'], 'occurred_at':p['occurred_at']}


def local_state(kinds):
    if len(kinds) != len(set(kinds)) or not set(kinds) <= ALLOWED_KINDS:
        return 'journal_conflict'
    s = set(kinds)
    if not s:
        return 'pending'
    if s == {'dispatch_reserved'}:
        return 'reserved'
    if s == {'dispatch_reserved', 'outcome_uncertain'}:
        return 'uncertain'
    if s == {'dispatch_reserved', 'processing_acknowledged'}:
        return 'processed_ack'
    return 'journal_conflict'


def check_remote(snapshot):
    if snapshot is None:
        return None
    if not isinstance(snapshot, dict) or snapshot.get('schema_version') != SCHEMA:
        raise ReconciliationError('Remote evidence schema invalid')
    if snapshot.get('snapshot_scope') not in ('observed_make_airtable_test_records_only', 'observed_make_airtable_event_inventory'):
        raise ReconciliationError('Remote evidence scope is not recognized')
    _utc(snapshot.get('collected_at_utc'))
    ds = snapshot.get('make_data_store')
    at = snapshot.get('airtable')
    if not isinstance(ds, list) or not isinstance(at, list) or len(ds)>1000 or len(at)>1000:
        raise ReconciliationError('Remote evidence arrays missing or oversized')
    dmap, amap = defaultdict(list), defaultdict(list)
    seen_remote_record_ids = set()
    for x in ds:
        if not isinstance(x,dict) or not all(k in x for k in ('key','status','airtable_record_id','evidence_sha256')):
            raise ReconciliationError('Incomplete Make Data Store evidence')
        id_ = _uuid(x['key'])
        if x['status'] not in ('reserved','mirrored'):
            raise ReconciliationError('Unknown remote Data Store delivery state')
        _sha(x['evidence_sha256'])
        aid = x['airtable_record_id']
        if aid not in (None, '') and (not isinstance(aid, str) or not REC_RE.fullmatch(aid)):
            raise ReconciliationError('Invalid Make Airtable record ID')
        if x['status'] == 'mirrored' and aid in (None, ''):
            raise ReconciliationError('Mirrored Make entry is missing its Airtable record ID')
        if 'event_id' in x and _uuid(x['event_id']) != id_:
            raise ReconciliationError('Make record key and event ID disagree')
        dmap[id_].append(x)
    for x in at:
        if not isinstance(x,dict) or not all(k in x for k in ('id','event_id','case_ref','event_type','source_layer','evidence_sha256','occurred_at')):
            raise ReconciliationError('Incomplete Airtable evidence')
        id_=_uuid(x['event_id'])
        if not isinstance(x['id'],str) or not REC_RE.fullmatch(x['id']) or x['id'] in seen_remote_record_ids:
            raise ReconciliationError('Invalid/reused Airtable record ID')
        seen_remote_record_ids.add(x['id'])
        if not isinstance(x['case_ref'],str) or not CASE_RE.fullmatch(x['case_ref']):
            raise ReconciliationError('Invalid remote case reference')
        if not isinstance(x['source_layer'],str) or not isinstance(x['event_type'],str):
            raise ReconciliationError('Invalid remote event label')
        _sha(x['evidence_sha256'])
        _utc(x['occurred_at'])
        amap[id_].append(x)
    return dmap,amap


def _remote_class(event, d, a):
    if len(d)>1 or len(a)>1:
        return 'remote_duplicate'
    if not d and not a:
        return 'not_observed'
    if not d:
        return 'airtable_without_store'
    entry=d[0]
    if entry['evidence_sha256']!=event['source_evidence_sha256']:
        return 'digest_mismatch'
    if not a:
        return 'reserved_without_airtable' if entry['status']=='reserved' else 'store_mirrored_without_airtable'
    airtable=a[0]
    if (entry['status']!='mirrored' or entry['airtable_record_id']!=airtable['id'] or
        airtable['case_ref']!=event['case_ref'] or
        airtable['event_type']!=event['event_type'] or
        airtable['source_layer']!=event['source_layer'] or
        airtable['evidence_sha256']!=event['source_evidence_sha256'] or
        _utc(airtable['occurred_at'])!=event['occurred_at']):
        return 'remote_mismatch'
    return 'mirrored_fields_match_snapshot'


def reconcile(outbox, delivery_events, snapshot=None):
    """Compare on verified event ID/digests. No writes or acknowledgments."""
    if not isinstance(outbox,list) or len(outbox)>MAX_SOURCES:
        raise ReconciliationError('Outbox size exceeds configured safety cap')
    if not isinstance(delivery_events,list) or len(delivery_events)>3*MAX_SOURCES:
        raise ReconciliationError('Delivery journal size exceeds safety cap')
    authoritative={}
    for row in outbox:
        safe=_record(row)
        if safe['event_id'] in authoritative:
            raise ReconciliationError('Duplicate authoritative outbox event ID')
        authoritative[safe['event_id']]=safe
    deliveries=defaultdict(list)
    for row in delivery_events:
        if not isinstance(row,dict) or not all(k in row for k in ('event_id','event_kind')):
            raise ReconciliationError('Malformed local delivery event')
        eid=_uuid(row['event_id'])
        if eid not in authoritative:
            raise ReconciliationError('Delivery event without authoritative Outbox event')
        deliveries[eid].append(row['event_kind'])
    checked=check_remote(snapshot)
    dmap, amap=checked if checked is not None else ({},{})
    rows=[]
    for eid,event in sorted(authoritative.items()):
        local=local_state(deliveries[eid])
        remote='not_checked' if checked is None else _remote_class(event,dmap[eid],amap[eid])
        if local=='journal_conflict':action='HOLD_MANUAL_JOURNAL_INVESTIGATION'
        elif local=='processed_ack' and remote=='mirrored_fields_match_snapshot':action='IN_SYNC_LOCAL_ACK_AND_REMOTE_EVIDENCE'
        elif local=='processed_ack':action='HOLD_ACK_REQUIRES_REMOTE_RECHECK'
        elif local=='reserved':action='HOLD_REVIEW_INCOMPLETE_EXECUTION_NO_AUTO_RETRY'
        elif local=='uncertain':action='HOLD_VERIFY_REMOTE_THEN_MANUAL_DECISION'
        elif remote=='mirrored_fields_match_snapshot':action='HOLD_REMOTE_OBSERVED_NO_LOCAL_ACK_MANUAL_REVIEW'
        elif local=='pending' and remote in ('not_observed','not_checked'):
            action='PENDING_NOT_SENT_NO_ACTION_AUTOMATICALLY'
        else:action='HOLD_REMOTE_CONFLICT_MANUAL_INVESTIGATION'
        rows.append({'event_id':eid,'source_layer':event['source_layer'],
                     'local_state':local,'remote_evidence':remote,'action':action})
    extra=[]
    if checked is not None:
        extra=sorted((set(dmap)|set(amap))-set(authoritative))
    local_counts=Counter(x['local_state'] for x in rows)
    remote_counts=Counter(x['remote_evidence'] for x in rows)
    return {'schema_version':'crm_quality_a11_readonly_audit_v1',
            'policy':'read_only_no_dispatch_no_replay_no_ack_no_crm_write',
            'summary':{'outbox_rows':len(outbox),'delivery_event_rows':len(delivery_events),
                       'local_states':dict(sorted(local_counts.items())),
                       'remote_states':dict(sorted(remote_counts.items())),
                       'external_events_without_local_outbox':len(extra),
                       'remote_evidence_supplied':checked is not None,
                       'remote_snapshot_scope': snapshot['snapshot_scope'] if checked is not None else None,
                       'remote_snapshot_collected_at_utc':snapshot['collected_at_utc'] if checked is not None else None},
            'events':rows,
            'external_event_ids_without_local_outbox':extra,
            'requires_manual_review':any(x['action'].startswith('HOLD') for x in rows) or bool(extra)}
