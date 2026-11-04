-- Append-only by application convention, not a cryptographically immutable log.
-- Contains limited fields from a dedicated HubSpot test account. Keep private.
CREATE TABLE IF NOT EXISTS crm_snapshot_runs (
  run_id uuid PRIMARY KEY,
  source_system text NOT NULL CHECK (source_system = 'hubspot_test'),
  configured_account_id bigint NOT NULL,
  started_at timestamptz NOT NULL,
  completed_at timestamptz NOT NULL DEFAULT now(),
  contact_count integer NOT NULL CHECK (contact_count >= 0),
  company_count integer NOT NULL CHECK (company_count >= 0),
  api_version text NOT NULL,
  UNIQUE (run_id, configured_account_id)
);
CREATE TABLE IF NOT EXISTS crm_record_snapshots (
  run_id uuid NOT NULL REFERENCES crm_snapshot_runs(run_id),
  object_type text NOT NULL CHECK (object_type IN ('contacts','companies')),
  hubspot_record_id text NOT NULL,
  source_updated_at timestamptz NULL,
  observed_at timestamptz NOT NULL,
  properties jsonb NOT NULL,
  record_hash char(64) NOT NULL,
  PRIMARY KEY (run_id, object_type, hubspot_record_id)
);
CREATE INDEX IF NOT EXISTS idx_m1_snapshot_object_record
  ON crm_record_snapshots (object_type, hubspot_record_id);
