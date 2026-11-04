"""Generate reproducible, wholly fictional CRM fixtures for M0. Stdlib only."""
from __future__ import annotations
import argparse
import csv
import json
import random
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIRST = ["Alex", "Taylor", "Jordan", "Morgan", "Avery", "Casey", "Riley", "Robin", "Skyler", "Quinn", "Drew", "Emery", "Jamie", "Reese", "Kai", "Parker", "Sage", "Jules", "Sam", "Rowan"]
LAST = ["Carter", "Lee", "Rivera", "Patel", "Brooks", "Nguyen", "Bennett", "Hayes", "Price", "Howard", "Turner", "Adams", "Khan", "Perry", "Bell", "Morris", "Foster", "Reed", "Gray", "Diaz"]
ADJ = ["Amber", "Bluewater", "Cedar", "Evergreen", "Granite", "Harbor", "Juniper", "Lumen", "Northfield", "Oakridge", "Pinnacle", "Redwood"]
NOUN = ["Analytics", "Systems", "Research", "Digital", "Software", "Logistics", "Consulting", "Health", "Manufacturing", "Services"]
COMPANY_HEADER = ["record_id", "name", "domain", "country", "industry", "updated_at"]
CONTACT_HEADER = ["record_id", "first_name", "last_name", "email", "phone", "job_title", "updated_at"]
ASSOCIATION_HEADER = ["contact_id", "company_id", "association_type"]


def slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def write_csv(path: Path, header: list[str], rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=header)
        writer.writeheader()
        writer.writerows(rows)


def generate(out: Path, seed: int = 20261104) -> dict:
    rng = random.Random(seed)
    out.mkdir(parents=True, exist_ok=True)
    companies: list[dict] = []
    contacts: list[dict] = []
    associations: list[dict] = []
    company_positive = []
    contact_positive = []

    fixed_names = ["Northstar Systems", "Northstar Systemics", "Pioneer Labs", "Pioneer Logistics", "Atlas Digital", "Atlas Diagnostics"]
    for i in range(105):
        name = fixed_names[i] if i < len(fixed_names) else f"{ADJ[i // 10]} {NOUN[i % 10]}"
        companies.append({
            "record_id": f"O{i + 1:04d}", "name": name,
            "domain": f"{slug(name)}.example" if i % 13 else "",
            "country": "US" if i % 4 else "United States",
            "industry": ["Software", "Services", "Manufacturing", "Research"][i % 4],
            "updated_at": f"2026-10-{(i % 25) + 1:02d}T10:00:00Z",
        })
    for i in range(15):
        original = companies[i * 3 + 6]
        variant = dict(original)
        variant["record_id"] = f"O{106 + i:04d}"
        variant["name"] = ("  " + original["name"].upper() + " " if i % 3 == 0
                           else original["name"] + " Ltd." if i % 3 == 1
                           else original["name"].lower())
        if i % 3 == 2:
            variant["domain"] = ""  # deliberately ambiguous
        variant["updated_at"] = "2026-10-29T13:00:00Z"
        companies.append(variant)
        company_positive.append([original["record_id"], variant["record_id"]])

    for i in range(270):
        first, last = FIRST[i % len(FIRST)], LAST[(i // len(FIRST) + i % 7) % len(LAST)]
        if 200 <= i < 208:  # same display names, demonstrably DIFFERENT people
            first, last = contacts[i - 200]["first_name"], contacts[i - 200]["last_name"]
        email = f"person{i + 1}@sample-org-{(i % 105) + 1}.example"
        if i % 19 == 0:
            email = ""
        elif i % 29 == 0:
            email = f"person{i + 1}@@invalid.example"
        elif i % 17 == 0:
            email = f" {email.upper()} "
        phone = "" if i % 3 == 0 else f"+1 202 555 {100 + i % 100:04d}"
        contacts.append({
            "record_id": f"C{i + 1:04d}", "first_name": first,
            "last_name": last, "email": email, "phone": phone,
            "job_title": ["Analyst", "Operations Manager", "Sales Lead", "Engineer", "Director"][i % 5],
            "updated_at": f"2026-10-{(i % 25) + 1:02d}T09:00:00Z",
        })
        if i % 11 != 0:
            associations.append({
                "contact_id": f"C{i + 1:04d}",
                "company_id": f"O{(i % 105) + 1:04d}", "association_type": "primary",
            })
    for i in range(30):
        original = contacts[i * 3 + 12]
        variant = dict(original)
        variant["record_id"] = f"C{271 + i:04d}"
        if i % 3 == 0:
            variant["email"] = original["email"].strip().upper() if original["email"] else ""
            variant["last_name"] = original["last_name"].upper()
        elif i % 3 == 1:
            variant["email"] = ""  # match requires human judgement
            variant["first_name"] = original["first_name"].lower()
        else:
            variant["email"] = f"alias{i}@alternate-{i}.example"  # distinct email, true synthetic duplicate
            variant["phone"] = original["phone"]
        variant["updated_at"] = "2026-10-30T11:00:00Z"
        contacts.append(variant)
        contact_positive.append([original["record_id"], variant["record_id"]])
        if i % 4 != 0:
            associations.append({
                "contact_id": variant["record_id"],
                "company_id": f"O{((i * 3 + 12) % 105) + 1:04d}", "association_type": "primary",
            })

    # Deliberate association inconsistency, for audit-only detection and tests.
    associations.append({"contact_id": "C0002", "company_id": "O9999", "association_type": "secondary"})
    rng.shuffle(companies)
    rng.shuffle(contacts)
    rng.shuffle(associations)
    write_csv(out / "companies.csv", COMPANY_HEADER, companies)
    write_csv(out / "contacts.csv", CONTACT_HEADER, contacts)
    write_csv(out / "associations.csv", ASSOCIATION_HEADER, associations)
    ground_truth = {
        "notice": "Synthetic labels created by generator; NEVER feed these labels to matching logic.",
        "seed": seed,
        "contact_same_person_pairs": contact_positive,
        "company_same_entity_pairs": company_positive,
        "contact_distinct_people_same_name_pairs": [[f"C{i + 1:04d}", f"C{201 + i:04d}"] for i in range(8)],
        "company_distinct_similar_name_pairs": [["O0001", "O0002"], ["O0003", "O0004"], ["O0005", "O0006"]],
    }
    (out / "ground_truth.json").write_text(json.dumps(ground_truth, indent=2) + "\n", encoding="utf-8")
    manifest = {"dataset": "wholly_synthetic", "generator_seed": seed, "contacts": len(contacts),
                "companies": len(companies), "associations": len(associations),
                "known_duplicate_contact_pairs": len(contact_positive),
                "known_duplicate_company_pairs": len(company_positive),
                "contains_deliberate_invalid_association": True}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "fixtures" / "synthetic")
    parser.add_argument("--seed", type=int, default=20261104)
    args = parser.parse_args()
    print(json.dumps(generate(args.out, args.seed), indent=2))
