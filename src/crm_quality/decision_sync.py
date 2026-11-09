"""M3c: synthetic-only, read-only Airtable decision intake / validation.

No CRM code, no Airtable writes, no repair permissions. SQL writes belong in a
separate, locally invoked decision-event journal after hash confirmation.
"""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

BASE_ID = 'appjSQYQroqDfLPPC'
TABLE_ID = 'tbly8zziUKydsqRfI'
FIELD = {
    'key': 'flduxJVqaHq9jyNHe',
    'uuid': 'fldApnH3X3SlYgGhY',
    'kind': 'fld4obhIgGVZiK5uL',
    'id1': 'fld4sT5NJLoD4mXDF',
    'id2': 'fldrsuvdmbU3LcPT7',
    'tier': 'fld9W6tq3W9hHP3Le',
    'route': 'fldLnRDc8IsRdAH7I',
    'status': 'fldaGGKRASvcd9IzD',
    'evidence': 'fldgIoO7PGBaFbOpW',
    'rule': 'fldnORRs18EnhdnUA',
    'reason': 'fldW0ufcNkmnaWfry',
    'similarity': 'fldIhaI8WXymANMTx',
    'batch': 'fldLOMkP6kQIszCoW',
    'source': 'fldngK9VCmmHePmjV',
    'decision': 'fld2466GeWPFLtLmP',
    'notes': 'fldWu5q2DAuraZevf',
    'edited_at': 'fld4kIpjyHulmWM5i',
    'edited_by': 'fld7LFFL8kJ21WLin',
}
ALLOWED_DECISIONS = {'Same Entity', 'Different Entity', 'Needs More Evidence'}
FUTURE_SCOPE = 'synthetic_fixture_only'
NAMESPACE = uuid.UUID('54165211-83db-4c8c-a6b4-990c50da2461')
MAX_API_PAGES = 2
MAX_SOURCE_ROWS = 60  # Original Airtable base has 57 candidates and 3 blank template rows.
MAX_DECISIONS = 57
NOTES_MIN, NOTES_MAX = 8, 500


class IntakeError(ValueError):
    """Fail closed, with a non-sensitive explanation."""


def _select(v):
    if isinstance(v, str):
        return v
    if isinstance(v, dict) and isinstance(v.get('name'), str):
        return v['name']
    return None


def _instant(value: str) -> str:
    if not isinstance(value, str):
        raise IntakeError('Decision Last Edited is missing or invalid')
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        raise IntakeError('Invalid decision timestamp') from None
    if parsed.tzinfo is None:
        raise IntakeError('Decision timestamp must contain a time zone')
    return parsed.astimezone(timezone.utc).isoformat(timespec='microseconds')


def _editor(value) -> str:
    # Airtable's lastModifiedBy field has a user object. Do not store name/email.
    user_id = value.get('id') if isinstance(value, dict) else value
    if not isinstance(user_id, str) or not re.fullmatch(r'usr[A-Za-z0-9]{8,50}', user_id):
        raise IntakeError('Airtable editor provenance is missing or invalid')
    return user_id


def _score(v):
    if v is None or v == '':
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float, str, Decimal)):
        raise IntakeError('Invalid similarity score')
    try:
        number = Decimal(str(v))
    except InvalidOperation:
        raise IntakeError('Invalid similarity score') from None
    if not number.is_finite() or not (Decimal(0) <= number <= Decimal(100)):
        raise IntakeError('Similarity score outside accepted range')
    return number.quantize(Decimal('0.01'))


def _note(text):
    if not isinstance(text, str):
        raise IntakeError('Reviewer Notes are required')
    cleaned = text.strip()
    if not NOTES_MIN <= len(cleaned) <= NOTES_MAX:
        raise IntakeError('Reviewer Notes require 8–500 characters')
    # Synthetic-only milestone. This is best-effort, not a comprehensive DLP engine.
    if re.search(r'[\r\n\t\x00-\x1f]', cleaned) or '@' in cleaned or re.search(r'(?i)https?://|\b(?:\+?\d[ -]?){9,}\b', cleaned):
        raise IntakeError('Reviewer Notes must not contain contact details, links or multiline text')
    return cleaned


def request_records(token: str, opener=urlopen) -> list[dict]:
    """One GET for <=100 rows. Bounded pagination, no retries or write requests."""
    if not isinstance(token, str) or not token.startswith('pat') or len(token) < 15:
        raise IntakeError('Set a read-only Airtable personal access token locally')
    records, cursor, seen_ids, seen_offsets = [], None, set(), set()
    fields = list(FIELD.values())
    for _page in range(MAX_API_PAGES):
        query = [('pageSize', 100), ('returnFieldsByFieldId', 'true')]
        query += [('fields[]', f) for f in fields]
        if cursor:
            query.append(('offset', cursor))
        url = f'https://api.airtable.com/v0/{BASE_ID}/{TABLE_ID}?{urlencode(query)}'
        req = Request(url, method='GET', headers={'Authorization': 'Bearer ' + token, 'Accept': 'application/json'})
        try:
            with opener(req, timeout=20) as response:
                payload = json.load(response)
        except HTTPError as exc:
            raise IntakeError(f'Airtable GET failed (HTTP {exc.code}); no database changes') from None
        except (URLError, TimeoutError, OSError, json.JSONDecodeError):
            raise IntakeError('Airtable GET failed (network/invalid response); no database changes') from None
        if not isinstance(payload, dict) or not isinstance(payload.get('records'), list):
            raise IntakeError('Unexpected Airtable API response')
        for row in payload['records']:
            if not isinstance(row, dict) or not re.fullmatch(r'rec[A-Za-z0-9]{14}', str(row.get('id', ''))):
                raise IntakeError('Airtable record lacks a valid ID')
            if row['id'] in seen_ids:
                raise IntakeError('Repeated Airtable record across pages')
            seen_ids.add(row['id'])
            records.append(row)
        if len(records) > MAX_SOURCE_ROWS:
            raise IntakeError('Unexpected row count in review table')
        cursor = payload.get('offset')
        if not cursor:
            return records
        if not isinstance(cursor, str) or cursor in seen_offsets:
            raise IntakeError('Repeated or malformed Airtable offset')
        seen_offsets.add(cursor)
    raise IntakeError('Airtable page limit exceeded; refusing partial snapshot')


def _same_expected_fields(actual: dict, candidate: dict, plan: dict) -> bool:
    expected = {
        'key': f'{candidate["object_type"]}:{candidate["record_id_1"]}:{candidate["record_id_2"]}',
        'uuid': str(candidate['candidate_id']),
        'kind': candidate['object_type'],
        'id1': candidate['record_id_1'],
        'id2': candidate['record_id_2'],
        'tier': candidate['tier'],
        'route': candidate['route'],
        'status': candidate['queue_status'],
        'evidence': ';'.join(candidate['evidence_codes']),
        'rule': candidate['rule_code'],
        'reason': candidate['route_reason'],
        'batch': str(plan['batch_id']),
        'source': plan['source_fingerprint'],
    }
    if any((_select(actual.get(FIELD[k])) if k in ('kind', 'tier', 'route', 'status') else actual.get(FIELD[k])) != val
           for k, val in expected.items()):
        return False
    return _score(actual.get(FIELD['similarity'])) == _score(candidate['name_similarity'])


def prepare_snapshot(records: list[dict], plan: dict) -> dict:
    """Check *every* candidate and source fingerprint before accepting any decision."""
    expected_rows = {str(r['candidate_id']): r for r in plan['rows']}
    if len(expected_rows) != 57 or len(records) < 57 or len(records) > MAX_SOURCE_ROWS:
        raise IntakeError('Unexpected candidate or source-record count')
    seen = set()
    decisions = []
    blanks = 0
    for rec in records:
        fields = rec.get('fields')
        if not isinstance(fields, dict):
            raise IntakeError('Malformed Airtable fields')
        cid = fields.get(FIELD['uuid'])
        if not cid:
            # There were three blank starter records; refuse any partly populated extras.
            if any(fields.get(FIELD[k]) not in (None, '') for k in ('key', 'decision', 'notes', 'id1', 'id2', 'batch')):
                raise IntakeError('Unidentified record contains candidate or decision fields')
            blanks += 1
            continue
        if not isinstance(cid, str) or cid not in expected_rows or cid in seen:
            raise IntakeError('Unknown or duplicate candidate UUID')
        seen.add(cid)
        candidate = expected_rows[cid]
        if not _same_expected_fields(fields, candidate, plan):
            raise IntakeError('Airtable candidate metadata differs from the PostgreSQL source plan')
        decision = _select(fields.get(FIELD['decision']))
        if decision == 'Not Reviewed':
            continue
        if decision not in ALLOWED_DECISIONS:
            raise IntakeError('Unrecognized/blank Reviewer Decision')
        if candidate['queue_status'] == 'needs_evidence' and decision != 'Needs More Evidence':
            raise IntakeError('Evidence backlog cannot be classified Same/Different Entity')
        notes = _note(fields.get(FIELD['notes']))
        edited_at = _instant(fields.get(FIELD['edited_at']))
        reviewer_id = _editor(fields.get(FIELD['edited_by']))
        fingerprint_payload = {
            'candidate_id': cid, 'airtable_record_id': rec['id'],
            'decision': decision, 'notes': notes, 'edited_at': edited_at,
            'reviewer_id': reviewer_id,
        }
        canonical = json.dumps(fingerprint_payload, sort_keys=True, ensure_ascii=True, separators=(',', ':'))
        hash_ = hashlib.sha256(canonical.encode('utf-8')).hexdigest()
        event_id = str(uuid.uuid5(NAMESPACE, cid + ':' + edited_at + ':' + hash_))
        decisions.append({**fingerprint_payload, 'payload_sha256': hash_, 'event_id': event_id})
    if seen != set(expected_rows):
        raise IntakeError('Airtable is missing one or more expected candidates')
    if blanks != len(records) - 57 or blanks > 3 or len(decisions) > MAX_DECISIONS:
        raise IntakeError('Unexpected blank template or decision count')
    decisions.sort(key=lambda x: x['candidate_id'])
    # Digest covers decisions and the full observed set of 57 identities/source plan.
    material = {'batch_id': str(plan['batch_id']), 'source_fingerprint': plan['source_fingerprint'],
                'candidate_uuids': sorted(seen), 'decisions': decisions}
    serial = json.dumps(material, sort_keys=True, separators=(',', ':'), ensure_ascii=True)
    return {
        'sha256': hashlib.sha256(serial.encode('utf-8')).hexdigest(),
        'batch_id': str(plan['batch_id']),
        'total': len(seen), 'blanks': blanks, 'decisions': decisions,
        'not_reviewed': 57 - len(decisions),
    }


def ensure_db_plan(cur, plan):
    """Verify synthetic batch, every candidate ID and review metadata under lock."""
    cur.execute('SELECT pg_advisory_xact_lock(%s)', (573001,))
    cur.execute('''SELECT batch_id,source_fingerprint,source_type,rule_version,expected_candidates
                   FROM crm_review_batches WHERE batch_id=%s''', (plan['batch_id'],))
    batch = cur.fetchone()
    if (not batch or str(batch[0]) != str(plan['batch_id']) or batch[1].strip() != plan['source_fingerprint']
            or batch[2] != FUTURE_SCOPE or batch[3] != plan['rule_version'] or batch[4] != 57):
        raise IntakeError('PostgreSQL synthetic review batch does not match Airtable source')
    cur.execute('''SELECT candidate_id, object_type, record_id_1, record_id_2, tier,
                          route, queue_status, rule_code, route_reason, evidence_codes,
                          name_similarity, merge_allowed, approved_for_crm_write
                   FROM crm_review_candidates WHERE batch_id=%s ORDER BY candidate_id FOR UPDATE''',
                (plan['batch_id'],))
    actual = cur.fetchall()
    expected = {str(r['candidate_id']): r for r in plan['rows']}
    if len(actual) != 57:
        raise IntakeError('PostgreSQL review queue is incomplete')
    for row in actual:
        cid = str(row[0]); p = expected.get(cid)
        if (not p or list(row[1:9]) != [p[k] for k in ('object_type','record_id_1','record_id_2','tier',
                                                   'route','queue_status','rule_code','route_reason')]
                or list(row[9]) != p['evidence_codes'] or _score(row[10]) != _score(p['name_similarity'])
                or row[11] is not False or row[12] is not False):
            raise IntakeError('PostgreSQL candidate state differs from validated source plan')
    if set(str(r[0]) for r in actual) != set(expected):
        raise IntakeError('PostgreSQL candidate IDs differ from validated source plan')


def apply_snapshot(conn, snapshot: dict, plan: dict) -> dict:
    """Atomic append-only decisions. No updates to CRM or M3a queue statuses."""
    inserted, skipped = 0, 0
    with conn.cursor() as cur:
        ensure_db_plan(cur, plan)
        cur.execute('SELECT candidate_id FROM crm_reviewer_latest_decision')
        existing_decided = {str(row[0]) for row in cur.fetchall()}
        incoming_decided = {event['candidate_id'] for event in snapshot['decisions']}
        if not existing_decided.issubset(incoming_decided):
            raise IntakeError('Previously recorded decision was cleared in Airtable; manual reconciliation required')
        for event in snapshot['decisions']:
            cid = uuid.UUID(event['candidate_id'])
            new_at = datetime.fromisoformat(event['edited_at'])
            cur.execute('''SELECT source_modified_at, payload_sha256 FROM crm_reviewer_decision_events
                           WHERE candidate_id=%s ORDER BY source_modified_at DESC LIMIT 1''', (cid,))
            old = cur.fetchone()
            if old:
                if old[0] > new_at:
                    raise IntakeError('Stale Airtable decision; full transaction rolled back')
                if old[0] == new_at:
                    if old[1] != event['payload_sha256']:
                        raise IntakeError('Same-timestamp conflicting decision; full transaction rolled back')
                    skipped += 1
                    continue
            cur.execute('''INSERT INTO crm_reviewer_decision_events
                (event_id,candidate_id,airtable_record_id,source_modified_at,
                 reviewer_airtable_user_id,decision,reviewer_notes,payload_sha256)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)''',
                (uuid.UUID(event['event_id']),cid,event['airtable_record_id'],new_at,
                 event['reviewer_id'],event['decision'],event['notes'],event['payload_sha256']))
            inserted += 1
    return {'inserted': inserted, 'replayed_without_change': skipped, 'observed_decisions': len(snapshot['decisions'])}
