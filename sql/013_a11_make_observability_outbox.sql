-- A11: local durable notification outbox. Not a control plane or CRM authorization.
CREATE TABLE IF NOT EXISTS crm_make_observation_outbox (
  event_id uuid PRIMARY KEY,
  source_layer text NOT NULL CHECK (source_layer IN ('a6','a7','a8','a9')),
  source_event_id uuid NOT NULL,
  source_sha256 char(64) NOT NULL CHECK (source_sha256 ~ '^[a-f0-9]{64}$'),
  case_ref char(24) NOT NULL CHECK (case_ref ~ '^[a-f0-9]{24}$'),
  payload_sha256 char(64) NOT NULL CHECK (payload_sha256 ~ '^[a-f0-9]{64}$'),
  payload jsonb NOT NULL CHECK (jsonb_typeof(payload)='object'),
  occurred_at timestamptz NOT NULL,
  staged_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  UNIQUE (source_layer,source_event_id)
);
CREATE TABLE IF NOT EXISTS crm_make_observation_delivery_events (
  delivery_event_id uuid PRIMARY KEY,
  event_id uuid NOT NULL REFERENCES crm_make_observation_outbox(event_id) ON DELETE RESTRICT,
  event_kind text NOT NULL CHECK (event_kind IN ('dispatch_reserved','processing_acknowledged','outcome_uncertain')),
  recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  UNIQUE(event_id,event_kind)
);
CREATE OR REPLACE FUNCTION crm_a11_no_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'A11 event journal is append-only'; END; $$;
DROP TRIGGER IF EXISTS trg_a11_outbox_immutable ON crm_make_observation_outbox;
CREATE TRIGGER trg_a11_outbox_immutable BEFORE UPDATE OR DELETE ON crm_make_observation_outbox
FOR EACH ROW EXECUTE FUNCTION crm_a11_no_mutation();
DROP TRIGGER IF EXISTS trg_a11_delivery_immutable ON crm_make_observation_delivery_events;
CREATE TRIGGER trg_a11_delivery_immutable BEFORE UPDATE OR DELETE ON crm_make_observation_delivery_events
FOR EACH ROW EXECUTE FUNCTION crm_a11_no_mutation();
