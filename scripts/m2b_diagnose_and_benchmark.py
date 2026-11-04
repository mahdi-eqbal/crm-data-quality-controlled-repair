"""M2b offline diagnostics and deliberately small, fully-labeled challenge benchmark.

No service keys, HubSpot requests, DB connections or writes; synthetic files only.
Ground-truth identity groups are read only AFTER candidate inference.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from itertools import combinations
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from crm_quality.matching import (  # noqa: E402
    match_records, _possible_pairs, normalized_email, normalized_phone,
    normalized_words,
)
from crm_quality.profiling import load_csv  # noqa: E402


def pair(a: str, b: str) -> tuple[str, str]:
    return tuple(sorted((a, b)))


def diagnosed_missed(original_contacts: list[dict], original_candidates: list[dict], truth: dict) -> dict:
    """Analyze known M0 positive pairs only; DO NOT change matching thresholds."""
    by_id = {r['record_id']: r for r in original_contacts}
    candidate_pairs = {pair(r['record_id_1'], r['record_id_2']) for r in original_candidates
                       if r['object_type'] == 'contacts'}
    blocks = set(_possible_pairs(original_contacts, 'contacts'))
    missed = []
    for a_id, b_id in truth['contact_same_person_pairs']:
        key = pair(a_id, b_id)
        if key in candidate_pairs:
            continue
        a, b = by_id[a_id], by_id[b_id]
        ea, eb = normalized_email(a.get('email')), normalized_email(b.get('email'))
        pa, pb = normalized_phone(a.get('phone')), normalized_phone(b.get('phone'))
        name_agrees = normalized_words(a.get('first_name', '') + ' ' + a.get('last_name', '')) == normalized_words(
            b.get('first_name', '') + ' ' + b.get('last_name', ''))
        if not key in blocks:
            reason = 'not_in_blocking_candidates'
        elif (not ea or not eb) and not (pa and pb and pa == pb):
            reason = 'insufficient_independent_evidence_missing_email'
        elif ea and eb and ea != eb and not (pa and pb and pa == pb):
            reason = 'different_emails_without_independent_evidence'
        else:
            reason = 'other_rule_threshold_or_context'
        missed.append({'record_ids': list(key), 'was_blocked': key in blocks,
                       'names_normalize_equal': name_agrees, 'reason': reason})
    return {
        'positive_pairs_labeled': len(truth['contact_same_person_pairs']),
        'retrieved_positive_pairs': len(truth['contact_same_person_pairs']) - len(missed),
        'missed_pairs': len(missed),
        'failure_reason_counts': dict(sorted(Counter(r['reason'] for r in missed).items())),
        'details': missed,
        'explanation': 'A matching name alone does not prove a shared identity. These are not safe auto-merge cases.',
    }


def evaluate_complete_groups(rows: list[dict], matches: list[dict], kind: str,
                             identity_groups: dict[str, str]) -> dict:
    """Full pair confusion matrix is valid only because every challenge ID has a constructed identity group."""
    ids = [r['record_id'] for r in rows]
    if len(ids) != len(set(ids)) or set(ids) != set(identity_groups):
        raise ValueError('All benchmark IDs must have exactly one identity-group label')
    if not all(isinstance(identity_groups[rid], str) and identity_groups[rid] for rid in ids):
        raise ValueError('Invalid identity group')
    predicted = {}
    for r in matches:
        if r['object_type'] != kind:
            continue
        key = pair(r['record_id_1'], r['record_id_2'])
        if key[0] == key[1] or key in predicted or not set(key).issubset(identity_groups):
            raise ValueError('Invalid, duplicate, or unknown prediction pair')
        if r.get('merge_allowed') is not False or r.get('requires_human_review') is not True:
            raise ValueError('Benchmark forbids merge-eligible candidates')
        predicted[key] = r['tier']
    positive = {pair(a, b) for a, b in combinations(ids, 2)
                if identity_groups[a] == identity_groups[b]}
    universe = {pair(a, b) for a, b in combinations(ids, 2)}
    emitted = set(predicted)
    tp, fp = len(emitted & positive), len(emitted - positive)
    fn, tn = len(positive - emitted), len(universe - positive - emitted)
    strong = {p for p, tier in predicted.items() if tier == 'strong_evidence'}
    precision = round(100 * tp / (tp + fp), 2) if tp + fp else None
    recall = round(100 * tp / (tp + fn), 2) if tp + fn else None
    return {
        'records': len(ids), 'all_unordered_pairs': len(universe),
        'true_positive': tp, 'false_positive': fp, 'false_negative': fn, 'true_negative': tn,
        'candidate_precision_pct': precision, 'candidate_recall_pct': recall,
        'strong_evidence_count': len(strong), 'strong_false_positives': len(strong - positive),
        'review_false_positives': len({p for p in emitted - positive if predicted[p] == 'review'}),
        'distinct_group_pairs_wrongly_flagged_for_review': fp,
        'note': 'Pair metrics apply only to THIS small, fully-labeled synthetic challenge set; not customer-data estimates.'
    }


def run() -> dict:
    original = ROOT / 'fixtures' / 'synthetic'
    contacts = load_csv(original / 'contacts.csv')
    companies = load_csv(original / 'companies.csv')
    associations = load_csv(original / 'associations.csv')
    original_matches = match_records(contacts, companies, associations)
    # Read original labels only after original candidate inference.
    labels = json.loads((original / 'ground_truth.json').read_text(encoding='utf-8'))
    misses = diagnosed_missed(contacts, original_matches, labels)

    challenge = ROOT / 'fixtures' / 'm2b_challenge'
    cs = load_csv(challenge / 'contacts.csv')
    os = load_csv(challenge / 'companies.csv')
    links = load_csv(challenge / 'associations.csv')
    challenge_matches = match_records(cs, os, links)
    # After inference; challenge label file NEVER imported by matcher.
    groups = json.loads((challenge / 'identity_groups.json').read_text(encoding='utf-8'))
    if groups.get('status') != 'fully_adjudicated_by_construction':
        raise ValueError('Challenge label contract not met')
    return {
        'scope': 'M2b offline synthetic-only diagnostic; NO CRM/DB calls or changes',
        'engine': 'unchanged M2a engine (no thresholds tuned against labels)',
        'm0_missed_positive_diagnostics': misses,
        'm2b_challenge': {
            'contacts': evaluate_complete_groups(cs, challenge_matches, 'contacts', groups['contact_identity_groups']),
            'companies': evaluate_complete_groups(os, challenge_matches, 'companies', groups['company_identity_groups']),
        },
        'limitations': [
            'Challenge data were authored with knowledge of M2a rules; this is NOT a blinded held-out sample.',
            'The full-pair labels in the small challenge permit precision/recall for this specific constructed dataset only.',
            'Original M0 only labels selected pairs and cannot support a full-dataset precision estimate.',
            'No customer or production performance is measured; no AI; no automatic merge or write.',
            'A candidate is a manual-review suggestion, not an assertion that records are identical.',
        ],
    }


def main() -> int:
    result = run()
    out = ROOT / 'evidence' / 'matching' / 'M2B_CHALLENGE_EVALUATION.json'
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    diag = result['m0_missed_positive_diagnostics']
    print('M2b DIAGNOSTIC — offline synthetic-only; no HubSpot/DB access')
    print(f"Original fixture: found={diag['retrieved_positive_pairs']}/{diag['positive_pairs_labeled']} "
          f"missed={diag['missed_pairs']} | reasons={diag['failure_reason_counts']}")
    for kind, metric in result['m2b_challenge'].items():
        print(f"Challenge {kind}: TP={metric['true_positive']} FP={metric['false_positive']} "
              f"FN={metric['false_negative']} TN={metric['true_negative']} "
              f"pair_precision={metric['candidate_precision_pct']}% "
              f"pair_recall={metric['candidate_recall_pct']}% "
              f"strong_FP={metric['strong_false_positives']}")
    print('All candidates require human review; no merge; no CRM write; no AI.')
    print('Report: evidence/matching/M2B_CHALLENGE_EVALUATION.json')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (ValueError, KeyError, OSError) as exc:
        print(f'FAIL: {type(exc).__name__} — check synthetic fixture contract')
        raise SystemExit(1) from None
