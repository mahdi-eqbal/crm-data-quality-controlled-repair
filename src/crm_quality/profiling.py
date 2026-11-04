"""Pure, read-only profiling of exported synthetic CRM rows. No network or CRM writes."""
from __future__ import annotations
import csv
import re
from pathlib import Path

EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
DOMAIN_RE = re.compile(r"^(?:[a-zA-Z0-9-]+\.)+[a-zA-Z]{2,}$")


def load_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def is_valid_email(value: str) -> bool:
    return bool(EMAIL_RE.fullmatch(value.strip()))


def is_valid_domain(value: str) -> bool:
    return bool(DOMAIN_RE.fullmatch(value.strip().lower()))


def field_quality(rows: list[dict[str, str]], fields: list[str]) -> dict:
    if not rows:
        raise ValueError("Cannot calculate field completeness without records")
    return {
        field: {"missing": sum(not (row.get(field) or "").strip() for row in rows),
                "completeness_pct": round(100 * sum(bool((row.get(field) or "").strip()) for row in rows) / len(rows), 2)}
        for field in fields
    }


def profile(contacts: list[dict], companies: list[dict], associations: list[dict]) -> dict:
    contact_ids = {r["record_id"] for r in contacts}
    company_ids = {r["record_id"] for r in companies}
    dangling = [a for a in associations if a["contact_id"] not in contact_ids or a["company_id"] not in company_ids]
    return {
        "record_counts": {"contacts": len(contacts), "companies": len(companies), "associations": len(associations)},
        "contacts": {
            "fields": field_quality(contacts, ["first_name", "last_name", "email", "phone"]),
            "invalid_nonempty_email": sum(bool(r["email"].strip()) and not is_valid_email(r["email"]) for r in contacts),
            "email_with_surrounding_whitespace": sum(r["email"] != r["email"].strip() for r in contacts),
            "without_any_association": len(contact_ids - {a["contact_id"] for a in associations}),
        },
        "companies": {
            "fields": field_quality(companies, ["name", "domain", "country"]),
            "invalid_nonempty_domain": sum(bool(r["domain"].strip()) and not is_valid_domain(r["domain"]) for r in companies),
        },
        "associations": {"dangling_count": len(dangling), "dangling_examples": dangling[:5]},
        "important_note": "Baseline profiling only: no inferred duplicates, no merge proposals, no CRM writes.",
    }
