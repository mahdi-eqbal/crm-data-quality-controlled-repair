-- M3a: local, synthetic-only review queue. NOT an approval or CRM-write system.
-- The CHECK constraints enforce that no row authorizes a merge or CRM repair.
CREATE TABLE IF NOT EXISTS crm_review_batches (
    batch_id uuid PRIMARY KEY,
    source_fingerprint char(64) NOT NULL UNIQUE,
    source_type text NOT NULL CHECK (source_type = 'synthetic_fixture_only'),
    rule_version text NOT NULL,
    expected_candidates integer NOT NULL CHECK (expected_candidates BETWEEN 0 AND 200),
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (source_fingerprint ~ '^[0-9a-f]{64}$')
);

CREATE TABLE IF NOT EXISTS crm_review_candidates (
    candidate_id uuid PRIMARY KEY,
    batch_id uuid NOT NULL REFERENCES crm_review_batches(batch_id) ON DELETE RESTRICT,
    object_type text NOT NULL CHECK (object_type IN ('contacts', 'companies')),
    record_id_1 text NOT NULL,
    record_id_2 text NOT NULL,
    tier text NOT NULL CHECK (tier IN ('strong_evidence', 'review')),
    route text NOT NULL CHECK (route IN ('priority_review', 'standard_review', 'needs_external_evidence')),
    queue_status text NOT NULL CHECK (queue_status IN ('pending_review', 'needs_evidence')),
    rule_code text NOT NULL,
    route_reason text NOT NULL,
    evidence_codes jsonb NOT NULL CHECK (jsonb_typeof(evidence_codes) = 'array'),
    name_similarity numeric(5,2) NULL CHECK (name_similarity BETWEEN 0 AND 100),
    requires_human_review boolean NOT NULL DEFAULT true CHECK (requires_human_review),
    merge_allowed boolean NOT NULL DEFAULT false CHECK (NOT merge_allowed),
    approved_for_crm_write boolean NOT NULL DEFAULT false CHECK (NOT approved_for_crm_write),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (batch_id, object_type, record_id_1, record_id_2),
    CHECK (record_id_1 < record_id_2),
    CHECK (
        (route IN ('priority_review', 'standard_review') AND queue_status = 'pending_review') OR
        (route = 'needs_external_evidence' AND queue_status = 'needs_evidence')
    )
);

CREATE INDEX IF NOT EXISTS idx_crm_review_queue_batch_status
    ON crm_review_candidates (batch_id, queue_status, route);

CREATE TABLE IF NOT EXISTS crm_review_events (
    event_id uuid PRIMARY KEY,
    candidate_id uuid NOT NULL REFERENCES crm_review_candidates(candidate_id) ON DELETE RESTRICT,
    event_type text NOT NULL CHECK (event_type = 'candidate_staged'),
    event_context jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(event_context) = 'object'),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (candidate_id, event_type)
);
-- Append-only by application convention, not immutable forensic evidence.
-- Future M3b: separate signed reviewer decisions and narrowly authorized backend roles.
