# M0 Scope Contract & Safety Policy

## Commercial user story

As a RevOps practitioner responsible for HubSpot data quality, I need to identify suspect contacts and companies, review evidence-backed repair proposals, approve limited field changes, and verify the resulting CRM state—without unexpectedly merging customers or breaking associations.

## V1 in scope

- Contacts, Companies, and read-only inspection of selected associations.
- Baseline missing/invalid-format profiling and field-level quality summaries.
- Deterministic and fuzzy duplicate-candidate identification with evidence and abstention.
- Human review in Airtable, durable policy and execution state in PostgreSQL.
- Pre-snapshots, controlled approved updates to a small allowlist in a HubSpot **test account**.
- Read-after-write verification, exception queue, audit trail, reconciliation report.
- Synthetic data, reproducible tests, documented implementation limitations.

## Out of scope

- Automated merge (including "high confidence" duplicates), production write/merge, full migration, multi-tenant SaaS, paid enrichment, custom browser frontend, irreversible association edits, autonomous AI approval.

## Non-negotiable controls before a future write

1. Isolated test account and explicit authorization for that test action.
2. Valid field allowlist and policy version; never infer write permission from a UI button alone.
3. Pre-change snapshot of relevant property values and record/association context.
4. Verified human identity, review decision and approval bound to an immutable proposal version.
5. Preflight direct read and comparison of the current field state with the approved snapshot.
6. Idempotency record with collision-safe operation identifier and execution state.
7. Bounded retry and explicit handling of "write may have succeeded but acknowledgement failed".
8. Direct post-write verification and reconciliation.
9. Explicit quarantine for conflicts, partial failures and manual review.

## Risk model

- **Low**: reversible formatting-only suggestion, still requires approval.
- **Medium**: business-significant field conflict, require evidence and reviewer.
- **High**: merge, change of identity fields, ownership, lifecycle or associations; no automated write in V1.

## Limitations

A snapshot is not a full CRM backup. CRM APIs may not provide atomic compare-and-swap. Race conditions and automation side effects require scoped test-account verification. HubSpot merges cannot be assumed reversible. Historical records are not evidence of a real customer engagement.
