# Architecture Decision Record 0001 — Controlled Remediation

**Date:** 2026-11-04  
**Status:** Proposed for V1; M0 offline scaffold implemented.

## Decision

- HubSpot source of truth, test-account-first.
- Python for extraction, pure quality rules, matching and policy-protected PATCH.
- PostgreSQL for immutable snapshots, proposal state, approval evidence, operation keys, attempts, verification and reconciliation.
- Airtable for review UI only, not a trusted authorization or audit database.
- Make for orchestration and notifications, never independent authorization for high-risk writes.
- Optional AI only for uncertain pair evaluation after offline comparison with deterministic/fuzzy methods.

## Workflow to implement

```text
HubSpot read only → Extract → PostgreSQL snapshot → Profile/Match
→ Repair proposal → Airtable review → Make approved event
→ Python gate (policy + approval + preflight + idempotency)
→ HubSpot field patch → Direct read → Verification → Reconciliation
```

`Merge` and association changes stay outside the automated path. A failed validation ends with a durable `conflict`/`failed` status; it never silently retries with stale approval.

## Why not only Make + Airtable?

Need strict operation-state control, deterministic tests, deduplication of execution requests, independent evidence and reconciliation. UI/orchestration should not be the authority for authorizing writes.

## Why not build a new SaaS?

The goal is an adaptable workflow implementation and credible delivery evidence for real CRM cleanup engagements—not a replacement for native CRM or specialized deduplication products.

## Unresolved design details for M1

- HubSpot account entitlements and supported object/association API versions.
- Availability of a test developer account, scopes and credential flow.
- PostgreSQL hosting choice and secret handling.
- Make/Airtable plan limits and webhook authentication.
- Customer-level retention, deletion and data-processing policies for any later real-world use.
