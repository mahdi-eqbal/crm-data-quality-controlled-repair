"""A11: safe, notification-only Make event contract and strict webhook transport.

This module contains no HubSpot connector, CRM credential reader, PATCH or merge path.
PostgreSQL remains the source of truth. All events are observational and test-only.
"""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

VERSION = 'crm_quality_a11_event_v1'
ACK_VERSION = 'crm_quality_a11_ack_v1'
NAMESPACE = uuid.UUID('b477add9-4070-42ba-943e-a14502f71c08')
MAX_SOURCES = 100

# Explicitly enumerated source contracts; no dynamic SQL, no arbitrary fields.
SOURCE_TYPES = {
    'a6': frozenset({'test_review_observed'}),
    'a7': frozenset({'blocked_test_review_only', 'blocked_live_source_drift'}),
    'a8': frozenset({'dispatch_reserved', 'patch_http_accepted',
                    'postwrite_verified', 'outcome_unknown', 'manual_recovery_required'}),
    'a9': frozenset({'rollback_reserved', 'rollback_http_accepted',
                    'rollback_verified', 'rollback_outcome_unknown',
                    'manual_intervention_required'}),
}

class MakeSafetyError(ValueError):
    pass


def canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(',', ':'), ensure_ascii=True)


def digest(obj):
    return hashlib.sha256(canonical(obj).encode('utf-8')).hexdigest()


def utc_time(value):
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace('Z', '+00:00'))
        except ValueError:
            raise MakeSafetyError('Invalid event timestamp') from None
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise MakeSafetyError('Timezone-aware timestamp required')
    return value.astimezone(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')


def strict_uuid(value):
    try:
        obj = uuid.UUID(str(value))
        if str(obj) != str(value).lower():
            raise ValueError
        return str(obj)
    except (ValueError, TypeError, AttributeError):
        raise MakeSafetyError('Invalid source UUID') from None


def sha256(value):
    if not isinstance(value, str) or re.fullmatch(r'[a-f0-9]{64}', value) is None:
        raise MakeSafetyError('Invalid source evidence digest')
    return value


def construct(source, source_id, case_id, event_type, source_digest, recorded_at):
    if source not in SOURCE_TYPES or event_type not in SOURCE_TYPES[source]:
        raise MakeSafetyError('Unallowlisted event source or type')
    source_id, case_id = strict_uuid(source_id), strict_uuid(case_id)
    evidence = sha256(source_digest)
    event_id = str(uuid.uuid5(NAMESPACE, f'{source}:{source_id}'))
    case_ref = hashlib.sha256(f'crm-quality-a11:{case_id}'.encode()).hexdigest()[:24]
    body = {
        'schema_version': VERSION,
        'event_id': event_id,
        'case_ref': case_ref,
        'source_layer': source,
        'event_type': event_type,
        'source_evidence_sha256': evidence,
        'occurred_at': utc_time(recorded_at),
        'environment': 'hubspot_developer_test',
        'authority': 'notification_only',
        'independent_human_approval': False,
        'authorizes_crm_write': False,
    }
    validate_payload(body)
    return body


def validate_payload(body):
    if not isinstance(body, dict) or set(body) != {
        'schema_version','event_id','case_ref','source_layer','event_type',
        'source_evidence_sha256','occurred_at','environment','authority',
        'independent_human_approval','authorizes_crm_write'}:
        raise MakeSafetyError('Unexpected event fields')
    if (body['schema_version'] != VERSION or body['environment'] != 'hubspot_developer_test'
        or body['authority'] != 'notification_only'
        or body['independent_human_approval'] is not False
        or body['authorizes_crm_write'] is not False):
        raise MakeSafetyError('Non-observational event rejected')
    strict_uuid(body['event_id'])
    if not isinstance(body['case_ref'], str) or re.fullmatch(r'[0-9a-f]{24}', body['case_ref']) is None:
        raise MakeSafetyError('Invalid case reference')
    sha256(body['source_evidence_sha256'])
    if body['source_layer'] not in SOURCE_TYPES or body['event_type'] not in SOURCE_TYPES[body['source_layer']]:
        raise MakeSafetyError('Invalid event label')
    utc_time(body['occurred_at'])
    return True


def validate_hook(url, apikey):
    if not isinstance(url, str) or not isinstance(apikey, str):
        raise MakeSafetyError('Make webhook credentials missing')
    if len(apikey.strip()) < 16 or len(apikey) > 256 or any(c in '\r\n' for c in apikey):
        raise MakeSafetyError('Invalid Make webhook API key')
    if len(url) > 500:
        raise MakeSafetyError('Invalid Make webhook URL')
    try:
        parsed = urlsplit(url)
    except ValueError:
        raise MakeSafetyError('Invalid Make webhook URL') from None
    host = (parsed.hostname or '').lower()
    if (parsed.scheme != 'https' or parsed.username or parsed.password or
        parsed.port is not None or parsed.query or parsed.fragment or
        re.fullmatch(r'hook(?:\.(?:eu|us|au|ca|in)[1-9][0-9]?)?\.make\.com', host) is None or
        re.fullmatch(r'/[a-zA-Z0-9_-]{10,130}', parsed.path) is None):
        raise MakeSafetyError('Only a dedicated Make HTTPS custom webhook is permitted')
    return url


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def send_once(url, apikey, body, *, opener=None):
    validate_hook(url, apikey)
    validate_payload(body)
    req = Request(url, data=canonical(body).encode('utf-8'), method='POST', headers={
        'Content-Type': 'application/json', 'Accept': 'application/json',
        'x-make-apikey': apikey, 'User-Agent': 'crm-quality-a11-observer/1.0',
    })
    transport = opener if opener is not None else build_opener(NoRedirect())
    # One request, no automatic retries. A missing response is ambiguous.
    with transport.open(req, timeout=15) as response:
        if response.status != 200:
            raise MakeSafetyError('Make response not an acknowledged processing result')
        payload = response.read(4097)
    if len(payload) > 4096:
        raise MakeSafetyError('Unexpectedly long Make response')
    try:
        result = json.loads(payload)
    except (ValueError, UnicodeDecodeError):
        raise MakeSafetyError('Make did not supply a structured processing acknowledgment') from None
    if not isinstance(result, dict) or (result.get('schema') != ACK_VERSION
        or result.get('event_id') != body['event_id'] or result.get('processed') is not True):
        raise MakeSafetyError('Make processing acknowledgment missing or mismatched')
    return True
