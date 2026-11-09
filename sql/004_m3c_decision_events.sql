-- M3c: local, synthetic-only, append-only reviewer decisions.
-- No approval to change, PATCH, or MERGE CRM records is granted by this schema.
-- Requires 003_m3a_review_queue.sql to have been applied first.
CREATE TABLE IF NOT EXISTS crm_reviewer_decision_events (
    event_id uuid PRIMARY KEY,
    candidate_id uuid NOT NULL REFERENCES crm_review_candidates(candidate_id) ON DELETE RESTRICT,
    airtable_record_id text NOT NULL CHECK (airtable_record_id ~ '^rec[A-Za-z0-9]{14}$'),
    source_modified_at timestamptz NOT NULL,
    reviewer_airtable_user_id text NOT NULL CHECK (reviewer_airtable_user_id ~ '^usr[A-Za-z0-9]{8,50}$'),
    decision text NOT NULL CHECK (decision IN ('Same Entity','Different Entity','Needs More Evidence')),
    reviewer_notes text NOT NULL CHECK (char_length(btrim(reviewer_notes)) BETWEEN 8 AND 500),
    payload_sha256 char(64) NOT NULL CHECK (payload_sha256 ~ '^[0-9a-f]{64}$'),
    recorded_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(candidate_id, source_modified_at)
);
CREATE INDEX IF NOT EXISTS idx_crm_reviewer_events_candidate_time
    ON crm_reviewer_decision_events(candidate_id,source_modified_at DESC);

-- Guard against accidental mutation by the application's DB role.
-- DB owner/superuser can still drop triggers; this is *not* tamper-proof cryptographic storage.
CREATE OR REPLACE FUNCTION crm_m3c_reject_decision_mutation()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'reviewer decision events are append-only';
END; $$;
DROP TRIGGER IF EXISTS trg_crm_m3c_no_mutate ON crm_reviewer_decision_events;
CREATE TRIGGER trg_crm_m3c_no_mutate BEFORE UPDATE OR DELETE
ON crm_reviewer_decision_events FOR EACH ROW
EXECUTE FUNCTION crm_m3c_reject_decision_mutation();

CREATE OR REPLACE VIEW crm_reviewer_latest_decision AS
SELECT DISTINCT ON (candidate_id)
       candidate_id, event_id, decision, reviewer_airtable_user_id,
       source_modified_at, recorded_at
FROM crm_reviewer_decision_events
ORDER BY candidate_id, source_modified_at DESC, recorded_at DESC;
