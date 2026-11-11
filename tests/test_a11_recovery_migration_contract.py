"""Static safety checks; does not connect to PostgreSQL or Make."""
import unittest
from pathlib import Path

SQL = (Path(__file__).resolve().parents[1] / 'sql' / '014_a11_recovery_evidence.sql').read_text()

class RecoveryMigrationContract(unittest.TestCase):
    def test_only_new_tables(self):
        self.assertNotIn('ALTER TABLE crm_make_observation_delivery_events', SQL)
        self.assertNotIn('DROP TABLE', SQL)
        self.assertNotIn('UPDATE crm_make_observation_', SQL)
    def test_append_only_triggers(self):
        self.assertEqual(SQL.count('EXECUTE FUNCTION crm_a11_no_mutation()'), 2)
    def test_no_replay_authorization(self):
        self.assertNotIn("'approve_replay'", SQL)
        self.assertNotIn("'retry'", SQL)
    def test_transactions(self):
        self.assertIn('BEGIN;', SQL)
        self.assertIn('COMMIT;', SQL)

if __name__ == '__main__': unittest.main()
