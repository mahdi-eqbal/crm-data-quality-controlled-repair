-- A11 recovery audit extension: storage only. No replay, dispatch or ACK authorization.
-- Apply once after 013, with a reviewed backup and a controlled migration process.
BEGIN;
CREATE TABLE crm_a11_recovery_evidence (
 evidence_id uuid PRIMARY KEY,
 event_id uuid NOT NULL REFERENCES crm_make_observation_outbox(event_id) ON DELETE RESTRICT,
 evidence_kind text NOT NULL CHECK (evidence_kind IN ('webhook_http_rejection','remote_inventory','operator_review')),
 source_system text NOT NULL CHECK (source_system IN ('make_webhook_log','make_data_store','airtable','local_operator')),
 observed_at timestamptz NOT NULL,
 recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 http_status integer CHECK (http_status IS NULL OR http_status BETWEEN 100 AND 599),
 evidence_sha256 char(64) NOT NULL CHECK (evidence_sha256 ~ '^[a-f0-9]{64}$'),
 evidence_reference text NOT NULL CHECK (length(evidence_reference) BETWEEN 1 AND 256),
 notes text NOT NULL DEFAULT '' CHECK (length(notes) <= 500),
 CHECK (evidence_kind <> 'webhook_http_rejection' OR (source_system='make_webhook_log' AND http_status IS NOT NULL)),
 UNIQUE (event_id, evidence_kind, evidence_sha256)
);
CREATE INDEX crm_a11_recovery_evidence_event_idx ON crm_a11_recovery_evidence(event_id,recorded_at);
CREATE TABLE crm_a11_recovery_decisions (
 decision_id uuid PRIMARY KEY,
 event_id uuid NOT NULL REFERENCES crm_make_observation_outbox(event_id) ON DELETE RESTRICT,
 decision_kind text NOT NULL CHECK (decision_kind IN ('hold','investigate','close_without_replay')),
 reviewer_reference text NOT NULL CHECK (length(reviewer_reference) BETWEEN 1 AND 128),
 evidence_digest char(64) NOT NULL CHECK (evidence_digest ~ '^[a-f0-9]{64}$'),
 rationale text NOT NULL CHECK (length(rationale) BETWEEN 1 AND 1000),
 recorded_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX crm_a11_recovery_decisions_event_idx ON crm_a11_recovery_decisions(event_id,recorded_at);
CREATE TRIGGER trg_a11_recovery_evidence_immutable BEFORE UPDATE OR DELETE ON crm_a11_recovery_evidence
 FOR EACH ROW EXECUTE FUNCTION crm_a11_no_mutation();
CREATE TRIGGER trg_a11_recovery_decisions_immutable BEFORE UPDATE OR DELETE ON crm_a11_recovery_decisions
 FOR EACH ROW EXECUTE FUNCTION crm_a11_no_mutation();
COMMIT;
