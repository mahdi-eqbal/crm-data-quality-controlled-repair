# M4b — Independent Approval Request Contract & Synthetic Preflight Gates

Status: **offline design and tests; NO real approval authority, NO CRM execution**.

## Motivation / boundaries

M4a identified 31 synthetic `company.country = 'United States'` repair opportunities. M4b does not apply patches. It prepares **31 deterministic request packets**: **22 awaiting independent approval** and **9 held** because of unresolved duplicate-candidate dependencies. The M3c duplicate decision journal does not authorize repair; neither an Airtable reviewer decision nor a manually drafted approval document grants CRM permissions.

**No HubSpot, Airtable, PostgreSQL, Make, HTTP, or network access.** The only data sources are the existing synthetic fixture CSVs and the local read-only `quality_policy.json`. `--report` is the only operation that writes a file, and writes to Git-ignored `private_exports/m4b/`.

## Design

1. Rebuild the full original M4a report deterministically; validate its SHA256, 120 company fixture rows, 268 associations, and original 57 matching candidates.
2. Create one request per M4a proposal, bound to its M4a `plan_sha256`, source fingerprint, policy version **and full policy digest**, company row hash, source `updated_at`, full company-association digest/count, duplicate-dependency keys and allowed `country` patch.
3. All requests carry `approval_recorded=false`, `write_authorized=false`, `merge_authorized=false`, `requires_fresh_hubspot_read_before_any_future_write=true`.
4. Block any request involving a duplicate-candidate dependency, irrespective of the review verdict.
5. In-memory synthetic preflight verifies exact source-row hash/timestamp, association hash, policy hash, plan digest, old value and field allowlist. A stale source, policy drift, or relationship drift blocks further simulated progress.
6. For **test fixtures only**, an optional *self-asserted mock decision* can demonstrate role separation (`proposed_by != reviewed_by`), approval binding, decision type, mandatory reason, expiration (max 48 hours), and reject/request-changes/expired branches. `demo_only_preflight_eligible` is **not** a real approval or patch authorization.
7. A forged or edited *whole-plan report* fails the fresh-source check (byte-for-byte derived structure comparison against a re-generated plan); per-request digests detect accidental drift and not malicious authenticated signers.

## Acceptance results (synthetic fixture only)

| Metric | Expected |
|---|---:|
| Original tests | 147 |
| New M4b tests | 35 |
| Total local unit tests | **182** |
| Approval request packets | 31 |
| Awaiting independent approval | 22 |
| Held for duplicate dependency | 9 |
| Actual approvals granted | 0 |
| CRM/PostgreSQL/Airtable writes; merges | 0 |

## Safe local commands (Windows PowerShell)

From `D:\projects\crm-data-quality-controlled-repair` after extracting the ZIP into the repository root:

```powershell
py -m unittest discover -s tests -v
py scripts\m4b_approval_preflight.py --check
py scripts\m4b_approval_preflight.py --demo
py scripts\m4b_approval_preflight.py --report
git check-ignore private_exports/m4b/approval_preflight_plan.json
```

`--demo` creates an **in-memory mock** review by a fictional distinct actor and checks one positive synthetic-only gate plus one stale-record rejection. It does not enter Airtable, verify a person's identity, persist a decision, or grant an approval. `--check` never writes a file. `--report` atomically writes only `private_exports/m4b/approval_preflight_plan.json`, with IDs/hashes and no company names, emails, phone numbers, or domains. Never commit this report, personal access tokens, local PostgreSQL data, or `.env`.

## What this does *not* establish

- `source_record_sha256` and source `updated_at` are **synthetic fixture snapshots**, not a fresh HubSpot GET or a server-side optimistic lock/ETag.
- The mock reviewer ID is self-asserted and *not* a verified authority. Real independent Approval requires authenticated identity/RBAC, a separate approval queue, and immutable permission-scoped events.
- Even a valid real approval would still need a post-approval live preflight, conditional write concurrency, downstream-impact verification, exception handling and a real rollback plan. A reversed in-memory change does not prove a live rollback will be possible.
- No actual repair execution path, HubSpot PATCH, merge, or change authorization exists in this milestone.

## Future acceptance gate

Before moving past synthetic-only scope: design a separate authenticated approval flow with least-privilege reviewer role; retain versioned decision, expiration and revocation; require a new *read-only* HubSpot preflight against the developer test account with direct source-field and association checks; maintain a dedicated, permissioned audit trail; run bounded staging-only write tests only after distinct user permission and a new security review. Existing `writes_enabled=false` remains unchanged until an explicitly separate future controlled-write milestone.

## Cost discipline

All checks and tests run locally; no GitHub Actions or external automation is required. Do not run CI manually for this patch. Stage only six named M4b source/document/evidence files after verifying local outputs and protecting ignored reports. ZIP distribution files should remain untracked, not pushed.
