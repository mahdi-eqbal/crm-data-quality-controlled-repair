"""Run M0 offline baseline profiling on synthetic CSV files."""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from crm_quality.profiling import load_csv, profile  # noqa: E402


def audit(data_dir: Path, report_dir: Path) -> dict:
    result = profile(*(load_csv(data_dir / name) for name in ("contacts.csv", "companies.csv", "associations.csv")))
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "baseline.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    lines = ["# M0 Synthetic CRM Data Quality Baseline", "", "> Generated fixture data, not a customer environment.", "",
             "## Counts", ""]
    lines += [f"- {name}: {count}" for name, count in result["record_counts"].items()]
    for obj in ("contacts", "companies"):
        lines += ["", f"## {obj.title()} fields", "", "| Field | Missing | Completeness |", "|---|---:|---:|"]
        for field, metrics in result[obj]["fields"].items():
            lines.append(f"| {field} | {metrics['missing']} | {metrics['completeness_pct']}% |")
    lines += ["", "## Exceptions", "",
              f"- Invalid nonempty email: {result['contacts']['invalid_nonempty_email']}",
              f"- Emails with surrounding whitespace: {result['contacts']['email_with_surrounding_whitespace']}",
              f"- Contacts without association: {result['contacts']['without_any_association']}",
              f"- Dangling associations: {result['associations']['dangling_count']}", "",
              "This audit does **not** yet detect duplicates, issue proposals, or modify a CRM.", ""]
    (report_dir / "baseline.md").write_text("\n".join(lines), encoding="utf-8")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=ROOT / "fixtures" / "synthetic")
    parser.add_argument("--report-dir", type=Path, default=ROOT / "evidence" / "baseline")
    args = parser.parse_args()
    print(json.dumps(audit(args.data_dir, args.report_dir), indent=2))
