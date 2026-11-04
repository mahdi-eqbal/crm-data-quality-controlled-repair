"""Evaluate M2 candidate generator AFTER inference on known synthetic labels.

Labels are accessed only in this evaluation entrypoint, NEVER during matching.
Metrics are from the same generator family: not a customer-data benchmark.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from crm_quality.matching import match_records  # noqa: E402
from crm_quality.profiling import load_csv  # noqa: E402


def _pair(pair: list[str]) -> tuple[str, str]:
    return tuple(sorted(pair))


def calculate_metrics(matches: list[dict], truth: dict) -> dict:
    result: dict = {}
    for kind, positive_name, negative_name in (
        ("contacts", "contact_same_person_pairs", "contact_distinct_people_same_name_pairs"),
        ("companies", "company_same_entity_pairs", "company_distinct_similar_name_pairs"),
    ):
        positives = {_pair(v) for v in truth[positive_name]}
        hard_negatives = {_pair(v) for v in truth[negative_name]}
        all_candidates = {(_pair([r["record_id_1"], r["record_id_2"]]))
                          for r in matches if r["object_type"] == kind}
        strong = {_pair([r["record_id_1"], r["record_id_2"]])
                  for r in matches if r["object_type"] == kind and r["tier"] == "strong_evidence"}
        found_positive = positives & all_candidates
        strong_tp = positives & strong
        # The fixture generator defines intentional duplicate pairs, but does not
        # fully adjudicate incidental name/phone collisions as distinct humans.
        # Report strong candidate purity vs tagged positives as a diagnostic,
        # NOT a validated precision statistic.
        result[kind] = {
            "known_positive_pairs": len(positives),
            "candidate_pairs": len(all_candidates),
            "known_positives_retrieved": len(found_positive),
            "known_positive_recall_pct": round(100 * len(found_positive) / len(positives), 2) if positives else None,
            "strong_evidence_pairs": len(strong),
            "strong_evidence_known_positives": len(strong_tp),
            "strong_evidence_other_or_unlabeled": len(strong - positives),
            "hard_negative_pairs": len(hard_negatives),
            "hard_negatives_flagged_for_review": len(hard_negatives & all_candidates),
            "hard_negatives_misclassified_strong": len(hard_negatives & strong),
        }
    return result


def main() -> int:
    fixture_dir = ROOT / "fixtures" / "synthetic"
    manifest = json.loads((fixture_dir / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("dataset") != "wholly_synthetic":
        raise ValueError("Only synthetic fixtures are supported")
    rows = [load_csv(fixture_dir / f) for f in ("contacts.csv", "companies.csv", "associations.csv")]
    matches = match_records(*rows)  # inference completed before labels load
    truth = json.loads((fixture_dir / "ground_truth.json").read_text(encoding="utf-8"))
    metrics = calculate_metrics(matches, truth)
    destination = ROOT / "evidence" / "matching"
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "M2_SYNTHETIC_EVALUATION.json").write_text(
        json.dumps({"dataset": "wholly_synthetic", "scope": "offline fixture-only",
                    "metrics": metrics, "limitations": [
                        "Not an independent held-out dataset; generator patterns are known.",
                        "Unlabeled non-positive pairs may be ambiguous; precision is not reported.",
                        "Every candidate requires human review. No merge/repair can execute.",
                    ]}, indent=2) + "\n", encoding="utf-8")
    print("M2 evaluation on synthetic labels only (not independent validation)")
    for kind, result in metrics.items():
        print(f"{kind}: found={result['known_positives_retrieved']}/{result['known_positive_pairs']} "
              f"({result['known_positive_recall_pct']}%); "
              f"strong={result['strong_evidence_pairs']}; "
              f"hard_negative_strong_errors={result['hard_negatives_misclassified_strong']}")
    print("No precision claim; no CRM write; no merge; no AI")
    print("evidence/matching/M2_SYNTHETIC_EVALUATION.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
