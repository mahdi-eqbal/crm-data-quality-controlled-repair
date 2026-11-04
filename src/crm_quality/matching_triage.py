"""M2c: cautious routing of offline matching results for a FUTURE review UI.

Never calls HubSpot, Make, Airtable, PostgreSQL, or AI. No writes, merges or
identity assertions. Does not consume truth labels. Inference output is ID-only.
"""
from __future__ import annotations

from collections import defaultdict
from itertools import combinations

from crm_quality.matching import match_records, normalized_words

TRIAGE_VERSION = 'm2c-v1'
MAX_EXPLORATORY_NAME_BLOCK = 5
MAX_EXPLORATORY_HINTS = 500


def _route(row: dict) -> tuple[str, str]:
    """Return (route, reason); never grant permission to merge or patch."""
    if row['tier'] == 'strong_evidence':
        return 'priority_review', 'multiple_correlated_signals_need_human_confirmation'
    evidence = set(row['evidence'])
    if row['object_type'] == 'contacts':
        if row['rule'] == 'email_shared_or_name_conflict' and row['name_similarity'] < 70:
            return 'needs_external_evidence', 'shared_mailbox_or_identity_conflict_possible'
        if ('different_valid_emails' in evidence and
                'same_phone_not_unique_identifier' not in evidence):
            return 'needs_external_evidence', 'contact_email_conflict_not_resolved'
    else:
        if row['rule'] == 'shared_domain_different_name':
            return 'needs_external_evidence', 'shared_domain_may_represent_distinct_entities'
        if 'different_valid_domains' in evidence:
            return 'needs_external_evidence', 'company_domain_conflict_not_resolved'
    return 'standard_review', 'human_adjudication_required'


def _name_only_hints(contacts: list[dict], existing_pairs: set[tuple[str, str]]) -> tuple[list[dict], dict]:
    by_name: dict[str, list[str]] = defaultdict(list)
    for record in contacts:
        first = normalized_words(record.get('first_name'))
        last = normalized_words(record.get('last_name'))
        if first and last:
            by_name[f'{first} {last}'].append(record['record_id'])
    hints = []
    skipped_groups = 0
    skipped_pairs = 0
    for ids in by_name.values():
        ids = sorted(ids)
        if len(ids) > MAX_EXPLORATORY_NAME_BLOCK:
            skipped_groups += 1
            skipped_pairs += len(ids) * (len(ids) - 1) // 2
            continue
        for a, b in combinations(ids, 2):
            if (a, b) in existing_pairs:
                continue
            hints.append({
                'object_type': 'contacts', 'record_id_1': a, 'record_id_2': b,
                'tier': 'insufficient_evidence', 'route': 'exploratory_only',
                'rule': 'same_normalized_name_no_independent_identity_proof',
                'evidence': ['same_normalized_full_name_only'],
                'route_reason': 'name_collision_possible_and_no_corroboration',
                'requires_human_review': True,
                'merge_allowed': False, 'approved_for_crm_write': False,
                'eligible_for_review_queue': False,
            })
            if len(hints) > MAX_EXPLORATORY_HINTS:
                raise ValueError('Exploratory candidate cap exceeded; fail closed')
    hints.sort(key=lambda r: (r['record_id_1'], r['record_id_2']))
    return hints, {'oversized_name_groups_skipped': skipped_groups,
                   'name_group_pairs_not_evaluated': skipped_pairs,
                   'exploratory_hint_cap': MAX_EXPLORATORY_HINTS}


def triage_matches(contacts: list[dict], companies: list[dict],
                   associations: list[dict]) -> dict:
    """Preserve baseline candidates, route their review needs, add ID-only weak hints.

    Weak name-only hints are NEVER eligible for automatic Airtable import,
    approval, patch or merge. 'strong_evidence' remains human-review-only.
    """
    existing = match_records(contacts, companies, associations)
    routed = []
    for item in existing:
        route, reason = _route(item)
        routed.append({**item, 'route': route, 'route_reason': reason,
                       'approved_for_crm_write': False,
                       'eligible_for_review_queue': route in ('priority_review', 'standard_review')})
    contact_pairs = {(c['record_id_1'], c['record_id_2'])
                     for c in existing if c['object_type'] == 'contacts'}
    hints, capacity = _name_only_hints(contacts, contact_pairs)
    if not all(x['requires_human_review'] and not x['merge_allowed'] and
               not x['approved_for_crm_write'] for x in routed + hints):
        raise ValueError('Unexpected unsafe candidate; fail closed')
    return {'rule_version': TRIAGE_VERSION, 'candidates': routed,
            'exploratory_hints': hints, 'capacity': capacity,
            'warning': ('Exploratory hints are not verified duplicates and MUST NOT be '
                        'auto-imported, approved, merged or patched.')}
