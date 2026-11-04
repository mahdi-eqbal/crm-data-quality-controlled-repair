"""Offline read-only M2 matching on explicitly synthetic CRM fixtures.

No CRM API calls, no PostgreSQL writes, no auto merge and no data repair.
Ground truth is not loaded by this inference script.
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from collections import Counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from crm_quality.matching import match_records  # noqa: E402
from crm_quality.profiling import load_csv  # noqa: E402


def main() -> int:
    folder = ROOT / "fixtures" / "synthetic"
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("dataset") != "wholly_synthetic":
        raise ValueError("M2 only permits the project's synthetic fixture dataset")
    contacts = load_csv(folder / "contacts.csv")
    companies = load_csv(folder / "companies.csv")
    associations = load_csv(folder / "associations.csv")
    if len(contacts) != manifest["contacts"] or len(companies) != manifest["companies"]:
        raise ValueError("Fixture count differs from manifest")
    results = match_records(contacts, companies, associations)
    output_dir = ROOT / "private_exports" / "m2"
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / "synthetic_candidates.csv"
    fields = ["object_type", "record_id_1", "record_id_2", "tier", "rule",
              "evidence", "name_similarity", "requires_human_review", "merge_allowed"]
    with output.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for result in results:
            writer.writerow({**result, "evidence": ";".join(result["evidence"])})
    summary = dict(sorted(Counter((r["object_type"], r["tier"]) for r in results).items()))
    print("M2 synthetic candidate generation — OFFLINE, no CRM calls")
    for (kind, tier), count in summary.items():
        print(f"{kind}: {tier}={count}")
    print(f"candidate_count={len(results)} | all_require_review=True | crm_writes=0 | merges=0")
    print(f"Candidate export: {output.relative_to(ROOT)} (gitignored)")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, OSError, KeyError) as exc:
        print(f"FAIL: {type(exc).__name__}: fixture validation failed")
        sys.exit(1)
