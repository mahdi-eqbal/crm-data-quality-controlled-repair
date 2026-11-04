"""Offline unit tests: synthetic-only, no HubSpot or database access."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
from crm_quality.matching import (match_records, normalized_email, normalized_phone,
                                  normalized_domain, core_company_name)
from crm_quality.profiling import load_csv
from m2_evaluate_synthetic import calculate_metrics


class TestM2Engine(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture = ROOT / "fixtures" / "synthetic"
        cls.contacts = load_csv(fixture / "contacts.csv")
        cls.companies = load_csv(fixture / "companies.csv")
        cls.associations = load_csv(fixture / "associations.csv")

    def test_normalizers(self):
        self.assertEqual(normalized_email(" Person@Example.COM "), "person@example.com")
        self.assertEqual(normalized_email("person@@example.com"), "")
        self.assertEqual(normalized_domain(" HTTPS://Example.COM/abc "), "example.com")
        self.assertEqual(normalized_phone("+1 202-555-0123"), "12025550123")
        self.assertEqual(core_company_name(" Example Systems Ltd. "), "example systems")

    def test_fixture_is_deterministic(self):
        actual = match_records(self.contacts, self.companies, self.associations)
        reversed_result = match_records(list(reversed(self.contacts)),
                                        list(reversed(self.companies)),
                                        list(reversed(self.associations)))
        self.assertEqual(actual, reversed_result)

    def test_every_candidate_is_review_only(self):
        result = match_records(self.contacts, self.companies, self.associations)
        self.assertTrue(result)
        self.assertTrue(all(r["requires_human_review"] and not r["merge_allowed"] for r in result))

    def test_exact_email_plus_matching_name(self):
        rows = [
            {"record_id": "C1", "first_name": "Ava", "last_name": "Sample", "email": "ava@example.com", "phone": ""},
            {"record_id": "C2", "first_name": "AVA", "last_name": "sample", "email": " AVA@EXAMPLE.COM ", "phone": ""},
        ]
        result = match_records(rows, [], [])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["tier"], "strong_evidence")
        self.assertFalse(result[0]["merge_allowed"])

    def test_shared_email_conflicting_names_is_review_not_strong(self):
        rows = [
            {"record_id": "C1", "first_name": "Alex", "last_name": "Smith", "email": "team@example.com", "phone": ""},
            {"record_id": "C2", "first_name": "Mary", "last_name": "Brown", "email": "team@example.com", "phone": ""},
        ]
        result = match_records(rows, [], [])
        self.assertEqual(result[0]["tier"], "review")

    def test_same_name_alone_not_sufficient(self):
        rows = [
            {"record_id": "C1", "first_name": "Alex", "last_name": "Lee", "email": "a@example.com", "phone": ""},
            {"record_id": "C2", "first_name": "Alex", "last_name": "Lee", "email": "b@example.com", "phone": ""},
        ]
        self.assertEqual(match_records(rows, [], []), [])

    def test_shared_company_same_name_stays_review(self):
        rows = [
            {"record_id": "C1", "first_name": "Alex", "last_name": "Lee", "email": "a@example.com", "phone": ""},
            {"record_id": "C2", "first_name": "Alex", "last_name": "Lee", "email": "b@example.com", "phone": ""},
        ]
        companies = [{"record_id": "O1", "name": "Dummy", "domain": "dummy.example"}]
        assoc = [{"contact_id": rid, "company_id": "O1"} for rid in ("C1", "C2")]
        result = match_records(rows, companies, assoc)
        self.assertEqual(result[0]["tier"], "review")
        self.assertIn("different_valid_emails", result[0]["evidence"])

    def test_company_legal_suffix_does_not_establish_same_entity(self):
        rows = [
            {"record_id": "O1", "name": "Northstar Systems", "domain": "northstar-one.example"},
            {"record_id": "O2", "name": "Northstar Systems Ltd", "domain": "northstar-two.example"},
        ]
        result = match_records([], rows, [])
        self.assertEqual(result[0]["tier"], "review")
        self.assertIn("different_valid_domains", result[0]["evidence"])

    def test_identical_domain_and_name_still_not_auto_merge(self):
        rows = [
            {"record_id": "O1", "name": "Acme Ltd", "domain": "acme.example"},
            {"record_id": "O2", "name": "ACME LIMITED", "domain": "ACME.EXAMPLE"},
        ]
        result = match_records([], rows, [])
        self.assertEqual(result[0]["tier"], "strong_evidence")
        self.assertFalse(result[0]["merge_allowed"])

    def test_fuzzy_contact_typo_with_identical_email(self):
        rows = [
            {"record_id": "C1", "first_name": "Ava", "last_name": "Sample", "email": "ava@example.com", "phone": ""},
            {"record_id": "C2", "first_name": "Ava", "last_name": "Sampl", "email": "ava@example.com", "phone": ""},
        ]
        result = match_records(rows, [], [])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["rule"], "email_and_name")
        self.assertLess(result[0]["name_similarity"], 100)

    def test_fuzzy_company_typo_with_matching_domain(self):
        rows = [
            {"record_id": "O1", "name": "Acme Technologies", "domain": "acme.example"},
            {"record_id": "O2", "name": "Acme Technlogies", "domain": "acme.example"},
        ]
        result = match_records([], rows, [])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["tier"], "strong_evidence")
        self.assertLess(result[0]["name_similarity"], 100)

    def test_curated_hard_negatives_never_strong(self):
        import json
        data = json.loads((ROOT / "fixtures" / "synthetic" / "ground_truth.json").read_text())
        result = match_records(self.contacts, self.companies, self.associations)
        metric = calculate_metrics(result, data)
        self.assertEqual(metric["contacts"]["hard_negatives_misclassified_strong"], 0)
        self.assertEqual(metric["companies"]["hard_negatives_misclassified_strong"], 0)

    def test_duplicate_ids_fail_closed(self):
        with self.assertRaises(ValueError):
            match_records([{"record_id": "C1"}, {"record_id": "C1"}], [], [])

    def test_label_metrics_do_not_claim_precision(self):
        test_truth = {
            "contact_same_person_pairs": [["C1", "C2"]],
            "company_same_entity_pairs": [["O1", "O2"]],
            "contact_distinct_people_same_name_pairs": [["C1", "C3"]],
            "company_distinct_similar_name_pairs": [["O1", "O3"]],
        }
        pred = [
            {"object_type": "contacts", "record_id_1": "C2", "record_id_2": "C1", "tier": "review"},
            {"object_type": "companies", "record_id_1": "O1", "record_id_2": "O3", "tier": "strong_evidence"},
        ]
        m = calculate_metrics(pred, test_truth)
        self.assertEqual(m["contacts"]["known_positive_recall_pct"], 100.0)
        self.assertEqual(m["companies"]["hard_negatives_misclassified_strong"], 1)
        self.assertNotIn("precision", m["contacts"])


if __name__ == "__main__":
    unittest.main()
