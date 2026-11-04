-- M1b: snapshot relationships and a completion manifest for each run.
-- Local PostgreSQL only. No changes to HubSpot schema or CRM records.
CREATE TABLE IF NOT EXISTS crm_association_snapshots (
    run_id uuid NOT NULL REFERENCES crm_snapshot_runs(run_id) ON DELETE RESTRICT,
    contact_object_type text NOT NULL DEFAULT 'contacts' CHECK (contact_object_type = 'contacts'),
    company_object_type text NOT NULL DEFAULT 'companies' CHECK (company_object_type = 'companies'),
    contact_id text NOT NULL,
    company_id text NOT NULL,
    association_types jsonb NOT NULL DEFAULT '[]'::jsonb,
    observed_at timestamptz NOT NULL,
    PRIMARY KEY (run_id, contact_id, company_id),
    CHECK (length(contact_id) > 0 AND length(company_id) > 0),
    CHECK (jsonb_typeof(association_types) = 'array'),
    FOREIGN KEY (run_id, contact_object_type, contact_id)
      REFERENCES crm_record_snapshots(run_id, object_type, hubspot_record_id),
    FOREIGN KEY (run_id, company_object_type, company_id)
      REFERENCES crm_record_snapshots(run_id, object_type, hubspot_record_id)
);
CREATE TABLE IF NOT EXISTS crm_association_run_stats (
    run_id uuid PRIMARY KEY REFERENCES crm_snapshot_runs(run_id) ON DELETE RESTRICT,
    verified_portal_id bigint NOT NULL CHECK (verified_portal_id = 149703596),
    checked_contact_count integer NOT NULL CHECK (checked_contact_count >= 0),
    link_count integer NOT NULL CHECK (link_count >= 0),
    contacts_without_company integer NOT NULL CHECK (contacts_without_company >= 0),
    CHECK (contacts_without_company <= checked_contact_count)
);
