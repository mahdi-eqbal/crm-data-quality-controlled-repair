"""Conservative, OFFLINE duplicate candidate generation for synthetic CRM data.

No API clients, database connections, merge operations, or repair proposals.
Every result requires human review, including 'strong_evidence' candidates.
Ground-truth labels MUST NOT be imported or used here.
"""
from __future__ import annotations

from collections import defaultdict
from itertools import combinations
import re
import unicodedata
from typing import Iterable

from rapidfuzz import fuzz

EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
DOMAIN_PATTERN = re.compile(r"^(?:[a-z0-9-]+\.)+[a-z]{2,}$")
LEGAL_SUFFIXES = {"llc", "ltd", "limited", "inc", "incorporated", "corp", "corporation", "co"}
MAX_BLOCK_SIZE = 80


def normalized_words(value: str | None) -> str:
    value = unicodedata.normalize("NFKC", value or "").casefold()
    value = re.sub(r"[^\w\s]+", " ", value, flags=re.UNICODE)
    return " ".join(value.split())


def normalized_email(value: str | None) -> str:
    cleaned = (value or "").strip().casefold()
    return cleaned if EMAIL_PATTERN.fullmatch(cleaned) else ""


def normalized_domain(value: str | None) -> str:
    cleaned = (value or "").strip().casefold()
    cleaned = re.sub(r"^https?://", "", cleaned).split("/")[0]
    return cleaned if DOMAIN_PATTERN.fullmatch(cleaned) else ""


def normalized_phone(value: str | None) -> str:
    digits = re.sub(r"\D", "", value or "")
    return digits if 10 <= len(digits) <= 15 else ""


def core_company_name(value: str | None) -> str:
    """Loose key for blocking only. Removing legal suffix NEVER proves identity."""
    tokens = normalized_words(value).split()
    while tokens and tokens[-1] in LEGAL_SUFFIXES:
        tokens.pop()
    return " ".join(tokens)


def _add(index: dict[str, set[str]], key: str, record_id: str) -> None:
    if key:
        index[key].add(record_id)


def _index_rows(rows: list[dict], kind: str) -> dict[str, set[str]]:
    index: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        rid = row["record_id"]
        if kind == "contacts":
            first = normalized_words(row.get("first_name"))
            last = normalized_words(row.get("last_name"))
            name = f"{first} {last}".strip()
            _add(index, "email:" + normalized_email(row.get("email")) if normalized_email(row.get("email")) else "", rid)
            _add(index, "name:" + name if first and last else "", rid)
            _add(index, "phone:" + normalized_phone(row.get("phone")) if normalized_phone(row.get("phone")) else "", rid)
            if first and last:
                _add(index, f"name_near:{first[0]}:{last[:4]}", rid)
        elif kind == "companies":
            domain = normalized_domain(row.get("domain"))
            core = core_company_name(row.get("name"))
            _add(index, "domain:" + domain if domain else "", rid)
            _add(index, "core:" + core if core else "", rid)
            if core:
                _add(index, "name_near:" + core[:4], rid)
        else:
            raise ValueError("Only contacts and companies are supported")
    return index


def _possible_pairs(rows: list[dict], kind: str) -> list[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    for _, ids in _index_rows(rows, kind).items():
        if 1 < len(ids) <= MAX_BLOCK_SIZE:
            pairs.update(combinations(sorted(ids), 2))
    return sorted(pairs)


def _company_assoc_map(associations: list[dict], contact_ids: set[str], company_ids: set[str]) -> dict[str, set[str]]:
    result: dict[str, set[str]] = defaultdict(set)
    for assoc in associations:
        cid, oid = assoc.get("contact_id"), assoc.get("company_id")
        if cid in contact_ids and oid in company_ids:
            result[cid].add(oid)
    return result


def _contact_decision(a: dict, b: dict, associations: dict[str, set[str]]) -> dict | None:
    email_a, email_b = normalized_email(a.get("email")), normalized_email(b.get("email"))
    name_a = normalized_words(f'{a.get("first_name", "")} {a.get("last_name", "")}')
    name_b = normalized_words(f'{b.get("first_name", "")} {b.get("last_name", "")}')
    similarity = fuzz.token_sort_ratio(name_a, name_b) if name_a and name_b else 0.0
    email_exact = bool(email_a and email_b and email_a == email_b)
    email_conflict = bool(email_a and email_b and email_a != email_b)
    phone_a, phone_b = normalized_phone(a.get("phone")), normalized_phone(b.get("phone"))
    phone_exact = bool(phone_a and phone_a == phone_b)
    shared_company = bool(associations.get(a["record_id"], set()) & associations.get(b["record_id"], set()))
    name_exact = bool(name_a and name_a == name_b)
    evidence = []
    if email_exact:
        evidence.append("same_valid_email")
    if name_exact:
        evidence.append("exact_normalized_name")
    elif similarity >= 85:
        evidence.append("similar_name")
    if phone_exact:
        evidence.append("same_phone_not_unique_identifier")
    if shared_company:
        evidence.append("shared_company")
    if email_conflict:
        evidence.append("different_valid_emails")

    # Exact email is strong evidence only when names also agree.
    if email_exact and similarity >= 90:
        return {"tier": "strong_evidence", "rule": "email_and_name", "evidence": evidence, "name_similarity": round(similarity, 1)}
    if email_exact and similarity < 90:
        return {"tier": "review", "rule": "email_shared_or_name_conflict", "evidence": evidence, "name_similarity": round(similarity, 1)}
    # A shared phone or company is not identity proof. Different emails reduce trust.
    if (name_exact or similarity >= 92) and (phone_exact or shared_company):
        return {"tier": "review", "rule": "name_plus_context", "evidence": evidence, "name_similarity": round(similarity, 1)}
    return None


def _company_decision(a: dict, b: dict) -> dict | None:
    domain_a, domain_b = normalized_domain(a.get("domain")), normalized_domain(b.get("domain"))
    core_a, core_b = core_company_name(a.get("name")), core_company_name(b.get("name"))
    similarity = fuzz.token_sort_ratio(core_a, core_b) if core_a and core_b else 0.0
    exact_domain = bool(domain_a and domain_b and domain_a == domain_b)
    domain_conflict = bool(domain_a and domain_b and domain_a != domain_b)
    exact_core = bool(core_a and core_a == core_b)
    evidence = []
    if exact_domain:
        evidence.append("same_valid_domain")
    if exact_core:
        evidence.append("same_name_after_suffix_removal_not_identity_proof")
    elif similarity >= 88:
        evidence.append("similar_company_name")
    if domain_conflict:
        evidence.append("different_valid_domains")
    if exact_domain and similarity >= 80:
        return {"tier": "strong_evidence", "rule": "domain_and_name", "evidence": evidence, "name_similarity": round(similarity, 1)}
    if exact_domain:
        return {"tier": "review", "rule": "shared_domain_different_name", "evidence": evidence, "name_similarity": round(similarity, 1)}
    if exact_core:
        return {"tier": "review", "rule": "equivalent_display_names", "evidence": evidence, "name_similarity": round(similarity, 1)}
    if similarity >= 94 and (not domain_a or not domain_b) and not domain_conflict:
        return {"tier": "review", "rule": "similar_name_incomplete_domain", "evidence": evidence, "name_similarity": round(similarity, 1)}
    return None


def match_records(contacts: list[dict], companies: list[dict], associations: list[dict]) -> list[dict]:
    """Return deterministic, non-authoritative review candidates; no side effects."""
    for kind, rows in (("contacts", contacts), ("companies", companies)):
        ids = [r.get("record_id") for r in rows]
        if not all(isinstance(x, str) and x for x in ids) or len(ids) != len(set(ids)):
            raise ValueError(f"Missing or duplicated {kind} IDs")
    company_assoc = _company_assoc_map(associations, {r["record_id"] for r in contacts},
                                       {r["record_id"] for r in companies})
    results: list[dict] = []
    for kind, rows in (("contacts", contacts), ("companies", companies)):
        by_id = {r["record_id"]: r for r in rows}
        for left, right in _possible_pairs(rows, kind):
            decision = (_contact_decision(by_id[left], by_id[right], company_assoc)
                        if kind == "contacts" else _company_decision(by_id[left], by_id[right]))
            if decision:
                results.append({"object_type": kind, "record_id_1": left, "record_id_2": right,
                                **decision, "requires_human_review": True, "merge_allowed": False})
    return sorted(results, key=lambda r: (r["object_type"], r["record_id_1"], r["record_id_2"]))
