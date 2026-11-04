"""M0 offline acceptance tests; no network connections or real customer data."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))
from generate_fixtures import generate  # noqa: E402
from crm_quality.profiling import load_csv, profile, is_valid_email, field_quality  # noqa: E402


class TestM0FixtureContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.path = Path(cls.temp.name)
        cls.meta = generate(cls.path)
        cls.contacts = load_csv(cls.path / "contacts.csv")
        cls.companies = load_csv(cls.path / "companies.csv")
        cls.associations = load_csv(cls.path / "associations.csv")
        cls.truth = json.loads((cls.path / "ground_truth.json").read_text())

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_exact_row_counts(self):
        self.assertEqual((len(self.contacts), len(self.companies)), (300, 120))
        self.assertEqual((self.meta["known_duplicate_contact_pairs"], self.meta["known_duplicate_company_pairs"]), (30, 15))

    def test_unique_object_ids(self):
        for rows in (self.contacts, self.companies):
            ids = [r["record_id"] for r in rows]
            self.assertEqual(len(ids), len(set(ids)))

    def test_all_emails_are_fictional(self):
        self.assertTrue(all(not r["email"].strip() or r["email"].strip().lower().endswith(".example") for r in self.contacts))
        self.assertTrue(all(not r["domain"] or r["domain"].endswith(".example") for r in self.companies))

    def test_ground_truth_pairs_exist_and_are_disjoint(self):
        contact_ids = {r["record_id"] for r in self.contacts}
        company_ids = {r["record_id"] for r in self.companies}
        for key, valid_ids in (("contact_same_person_pairs", contact_ids),
                               ("company_same_entity_pairs", company_ids),
                               ("contact_distinct_people_same_name_pairs", contact_ids),
                               ("company_distinct_similar_name_pairs", company_ids)):
            for a, b in self.truth[key]:
                self.assertIn(a, valid_ids)
                self.assertIn(b, valid_ids)
                self.assertNotEqual(a, b)
        self.assertEqual(len(self.truth["contact_distinct_people_same_name_pairs"]), 8)
        self.assertEqual(len(self.truth["company_distinct_similar_name_pairs"]), 3)

    def test_deterministic_files(self):
        with tempfile.TemporaryDirectory() as d:
            other = Path(d)
            generate(other)
            for filename in ("contacts.csv", "companies.csv", "associations.csv", "ground_truth.json", "manifest.json"):
                self.assertEqual((self.path / filename).read_bytes(), (other / filename).read_bytes())

    def test_baseline_detects_intentional_defects(self):
        summary = profile(self.contacts, self.companies, self.associations)
        self.assertEqual(summary["associations"]["dangling_count"], 1)
        self.assertGreater(summary["contacts"]["invalid_nonempty_email"], 0)
        self.assertGreater(summary["contacts"]["fields"]["email"]["missing"], 0)
        self.assertGreater(summary["contacts"]["without_any_association"], 0)

    def test_email_syntax_does_not_claim_deliverability(self):
        self.assertTrue(is_valid_email("someone@example.test"))
        self.assertFalse(is_valid_email("someone@@invalid.example"))
        self.assertFalse(is_valid_email(""))

    def test_empty_dataset_is_rejected(self):
        with self.assertRaises(ValueError):
            field_quality([], ["email"])

    def test_policy_disables_writes(self):
        policy = json.loads((ROOT / "config" / "quality_policy.json").read_text())
        self.assertFalse(policy["writes_enabled"])
        self.assertFalse(policy["automatic_merges_enabled"])
        self.assertTrue(policy["human_approval_required_for_all_writes"])
        self.assertIn("email", policy["protected_fields"])


if __name__ == "__main__":
    unittest.main()
