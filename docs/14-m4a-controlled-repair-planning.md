# M4a — Synthetic-only Controlled Repair Planning & Reversible Dry Run

## Intent and non-goals

Extend M3d read-only, reconciled decision evidence into **reversible repair design** without any CRM execution privileges. This milestone is *not* a deployment, Airtable approval automation, PostgreSQL migration, field PATCH, or merge engine.

M4a deliberately covers a *single normalization*: synthetic **company.country** from `United States` to `US` (ISO 3166-1 alpha-2) when the exact old value is present. No domain, email, name, phone, association or identity repair is proposed. Real customer data and HubSpot records are not used.

A company occurring in **any** of the 57 duplicate candidate pairs is placed on hold, regardless of whether that pair has been reviewed or classified. A reviewer decision never grants write authority. The original policy's future company-country allowlist is *not* permission to write; `writes_enabled=false` is required, or the planner fails closed.

## Architecture

1. Read local generated fixture CSVs and the existing `config/quality_policy.json`.
2. Validate original synthetic seed, record counts, `.example` domains, source fingerprint, and matching candidate plan via M3a functions.
3. Derive deterministic candidate-specific dependency holds from M3a matching pairs.
4. Produce proposal objects with immutable record identity, `old_value`, `proposed_value`, rule and policy version, row/source SHA256, association count, dependency keys, risk, explicit denials of write/merge authority and rollback value.
5. Simulate only `reviewable_dry_run` country edits **in an in-memory copy**, verify the country field is the only delta, preserve all relationships, revert the changes and check exact rollback.
6. Generate a deterministic plan digest. Only `--report` writes a human-readable JSON report to a Git-ignored local folder; it never modifies CRM, DB, Airtable or synthetic fixture files.

The existing `schemas/repair_proposal.schema.json` targets a hypothetical `source_system=hubspot` contract. This milestone uses a **separate** `m4a_repair_dry_run.schema.json` contract explicitly tagged `synthetic_fixture_only` to avoid falsely claiming there are HubSpot-native repair proposals.

## Data fields and semantics

- `reviewable_dry_run`: safe to *simulate* and inspect, **not approved** for a real write.
- `held_duplicate_dependency`: company is part of one or more duplicate candidate pairs. Do not simulate that update; resolve identity and downstream effects in a separate gated future milestone.
- `source_record_sha256` is a digest of all six original company fields; it is *not* an authoritative HubSpot `etag` or version check.
- `association_count` is source fixture context. No association is rewritten or reparented.
- `rollback_value` is the original synthetic country string, **not** a production-ready rollback command.
- `plan_sha256` is a deterministic content digest; it is not a signature or attestation of reviewer approval.

The fixture contains 120 companies; 31 have `country=United States`. Of those, 9 participate in duplicate candidate pairs and are held; 22 are simulated for review. Remaining 89 need no normalization. This is fixture-specific, not a customer metric.

## Local-only acceptance

From `D:\projects\crm-data-quality-controlled-repair` (PowerShell):

```powershell
py -m unittest discover -s tests -v
py scripts\m4a_plan_repairs.py --preview
py scripts\m4a_plan_repairs.py --report

git check-ignore private_exports/m4a/company_country_dry_run.json
```

Expected: previous 124 tests plus 23 new M4a tests = **147** tests; preview counts `31` opportunities, `22` reviewable, `9` held, and simulated rollback exact. No external API calls and no database calls. For the report, only `private_exports/m4a/company_country_dry_run.json` is created. It is ignored by `.gitignore`.

Do not push until the user has verified the local results. Avoid scheduling GitHub Actions; existing offline tests run locally. No new pip requirements are needed.

## Remaining before any production write

Fresh HubSpot GET and conditional preflight/optimistic concurrency, documented RBAC/approval authority, data-minimization of actual CRM values, immutable audit destination, explicit patch allowlist, dependency mapping and association safety, dry-run evidence per record, transactional/retry semantics, approval expiration and revocation, recovery/rollback testing and staging-only write tests. Automated merge remains prohibited in this project.
