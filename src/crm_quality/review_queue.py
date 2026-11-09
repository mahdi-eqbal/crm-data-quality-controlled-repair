"""M3a: purely local synthetic-only preparation of non-authoritative review rows.

No CRM access. No approval, identity verdict, merge, or field repair is possible.
Ground-truth labels are never consulted by this module.
"""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from pathlib import Path

from crm_quality.matching_triage import TRIAGE_VERSION, triage_matches
from crm_quality.profiling import load_csv

NAMESPACE = uuid.UUID('50db4637-af69-46d9-8cfa-015919c3a5bc')
ROUTES = {'priority_review', 'standard_review', 'needs_external_evidence'}
MAX_ROWS = 200
EXPECTED_DATASET = 'wholly_synthetic'
EXPECTED_SEED = 20261104
SYNTHETIC_FILENAMES = ('manifest.json', 'contacts.csv', 'companies.csv', 'associations.csv')
RECORD_ID_PATTERN = re.compile(r'^[CO][0-9]{4}$')
REASON_CODE_PATTERN = re.compile(r'^[a-z0-9_]+$')


def synthetic_fingerprint(folder: Path) -> str:
    h = hashlib.sha256()
    h.update(TRIAGE_VERSION.encode('ascii'))
    for filename in SYNTHETIC_FILENAMES:
        raw = (folder / filename).read_bytes()
        h.update(filename.encode('ascii') + b'\0' + len(raw).to_bytes(8, 'big') + raw)
    return h.hexdigest()


def validate_fixture(folder: Path) -> tuple[list[dict], list[dict], list[dict]]:
    """Deliberately refuse arbitrary files, new IDs, or non-.example contact/domain values."""
    manifest = json.loads((folder / 'manifest.json').read_text(encoding='utf-8'))
    if manifest.get('dataset') != EXPECTED_DATASET or manifest.get('generator_seed') != EXPECTED_SEED:
        raise ValueError('M3a only accepts the original synthetic fixture contract')
    contacts, companies, associations = (
        load_csv(folder / (name + '.csv')) for name in ('contacts', 'companies', 'associations')
    )
    if len(contacts) != 300 or len(companies) != 120 or len(associations) != 268:
        raise ValueError('Unexpected synthetic fixture record counts')
    if (len(contacts) != manifest.get('contacts') or
            len(companies) != manifest.get('companies') or
            len(associations) != manifest.get('associations')):
        raise ValueError('Synthetic fixture count mismatch')
    contact_ids = {r['record_id'] for r in contacts}
    company_ids = {r['record_id'] for r in companies}
    if (len(contact_ids) != len(contacts) or len(company_ids) != len(companies) or
            any(not RECORD_ID_PATTERN.fullmatch(x) for x in contact_ids | company_ids) or
            any(not x.startswith('C') for x in contact_ids) or
            any(not x.startswith('O') for x in company_ids)):
        raise ValueError('Unexpected synthetic IDs')
    for row in contacts:
        value = (row.get('email') or '').strip().lower()
        if value and not value.endswith('.example'):
            raise ValueError('Non-synthetic contact email; refusing to stage')
    for row in companies:
        value = (row.get('domain') or '').strip().lower()
        if value and not value.endswith('.example'):
            raise ValueError('Non-synthetic company domain; refusing to stage')
    for row in associations:
        # M0 intentionally contains a single dangling relationship. Do not resolve or import it.
        if row['contact_id'] not in contact_ids or not RECORD_ID_PATTERN.fullmatch(row['company_id']):
            raise ValueError('Unexpected association identity')
    return contacts, companies, associations


def validate_candidate(row: dict, contact_ids: set[str], company_ids: set[str]) -> dict:
    """Allowlist fields; reject hints and unsafe authorization/status flags."""
    kind, a, b = row['object_type'], row['record_id_1'], row['record_id_2']
    ids = contact_ids if kind == 'contacts' else company_ids if kind == 'companies' else set()
    if not a < b or a not in ids or b not in ids:
        raise ValueError('Invalid candidate pair')
    route = row.get('route')
    expected_eligible = route in ('priority_review', 'standard_review')
    if (route not in ROUTES or row.get('eligible_for_review_queue') is not expected_eligible or
            row.get('requires_human_review') is not True or
            row.get('merge_allowed') is not False or
            row.get('approved_for_crm_write') is not False or
            row.get('tier') not in ('strong_evidence', 'review')):
        raise ValueError('Unsafe candidate routing / authorization flags')
    for name in ('rule', 'route_reason'):
        if not isinstance(row.get(name), str) or not REASON_CODE_PATTERN.fullmatch(row[name]):
            raise ValueError('Unsafe reason code')
    codes = row.get('evidence')
    if (not isinstance(codes, list) or
            any(not isinstance(x, str) or not REASON_CODE_PATTERN.fullmatch(x) for x in codes)):
        raise ValueError('Unsafe evidence codes')
    score = row.get('name_similarity')
    if score is not None and (not isinstance(score, (int, float)) or isinstance(score, bool)
                              or not (0 <= score <= 100)):
        raise ValueError('Invalid similarity score')
    return {
        'object_type': kind,
        'record_id_1': a,
        'record_id_2': b,
        'tier': row['tier'],
        'route': route,
        'queue_status': 'pending_review' if expected_eligible else 'needs_evidence',
        'rule_code': row['rule'],
        'route_reason': row['route_reason'],
        'evidence_codes': list(codes),
        'name_similarity': score,
    }


def build_plan(folder: Path) -> dict:
    contacts, companies, associations = validate_fixture(folder)
    result = triage_matches(contacts, companies, associations)
    contact_ids = {r['record_id'] for r in contacts}
    company_ids = {r['record_id'] for r in companies}
    rows = [validate_candidate(r, contact_ids, company_ids) for r in result['candidates']]
    if len(rows) > MAX_ROWS or len(rows) != 57:
        raise ValueError('Unexpected review-candidate count; refusing to stage')
    keys = [(r['object_type'], r['record_id_1'], r['record_id_2']) for r in rows]
    if len(set(keys)) != len(keys):
        raise ValueError('Duplicate candidate pairs')
    fingerprint = synthetic_fingerprint(folder)
    batch_id = uuid.uuid5(NAMESPACE, 'synthetic-fixture:' + fingerprint)
    for r in rows:
        r['candidate_id'] = uuid.uuid5(NAMESPACE,
                                      f'{batch_id}:{r["object_type"]}:{r["record_id_1"]}:{r["record_id_2"]}')
        r['event_id'] = uuid.uuid5(NAMESPACE, 'staged:' + str(r['candidate_id']))
    return {
        'source_fingerprint': fingerprint,
        'batch_id': batch_id,
        'rule_version': TRIAGE_VERSION,
        'rows': rows,
        'excluded_exploratory_hints': len(result['exploratory_hints']),
    }


def local_pg_settings(env: dict[str, str]) -> dict:
    """No remote DB target is accepted, even if environment variables override .env."""
    host = env.get('PGHOST', '127.0.0.1')
    port = str(env.get('PGPORT', '5433'))
    database = env.get('PGDATABASE', 'crm_data_quality')
    user = env.get('PGUSER', 'crm_quality')
    password = env.get('PGPASSWORD', '')
    if (host not in ('127.0.0.1', 'localhost') or port != '5433' or
            database != 'crm_data_quality' or user != 'crm_quality' or not password):
        raise ValueError('M3a requires the dedicated local development PostgreSQL configuration')
    return {'host': host, 'port': 5433, 'dbname': database,
            'user': user, 'password': password, 'connect_timeout': 8}


def summarize_plan(plan: dict) -> dict[str, int]:
    from collections import Counter
    return dict(sorted(Counter(r['queue_status'] for r in plan['rows']).items()))
