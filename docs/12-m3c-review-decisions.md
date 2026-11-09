# M3c — Human Review Decision Intake & Append-Only PostgreSQL Journal

Status: offline implementation and tests. **Not yet validated against the user's local PostgreSQL or live Airtable PAT.**

## Architecture and boundaries

Airtable Review (human edits, synthetic data) → **read-only local API GET** → full-source validation → SHA-256 snapshot preview → explicit digest-gated import → **local PostgreSQL reviewer decision events**.

- Only the existing 57 synthetic candidates from M3a are accepted. The initial three blank template records are ignored (and strictly capped).
- Validate every candidate against locally recomputed M3a identities, routing, evidence codes, rule codes, similarity, batch UUID and source fingerprint before accepting any decisions. If one row is missing or altered, fail closed.
- The PostgreSQL batch and all 57 existing candidate rows are checked under a transaction lock before any event insertion.
- Only explicit decisions `Same Entity`, `Different Entity`, or `Needs More Evidence` are recorded. `Not Reviewed` stays out of the journal.
- For `needs_evidence`, the only acceptable decision is `Needs More Evidence`; `Same Entity` and `Different Entity` fail closed.
- Notes must be 8–500 characters; basic PII/link checks reject `@`, URLs and phone-like strings. These are **not** complete privacy checks; only synthetic demo data is approved.
- Requires Airtable `Decision Last Edited` timestamp and `Decision Last Edited By` user ID, tracking only the decision and notes fields. User ID is provenance, not a cryptographic signature or authorization for any CRM write.
- Decision edits append a new event; replay of the same modification time + content is idempotent. A stale revision or conflicting content with the same timestamp fails closed. Clearing an already-imported decision requires manual reconciliation; it is not silently forgotten.
- PostgreSQL trigger blocks UPDATE/DELETE on reviewer decision journal rows for the application role; the DB owner can still alter the schema, so the journal is not tamper-proof.
- **No changes to M3a candidate statuses or approval flags.** No HubSpot API, merge, PATCH, Make automation, or Airtable write. An `Same Entity` label is *not* an authorization to merge.

## Airtable provenance field

Added directly to the existing Base `CRM Data Quality - Review Console`:

- `Decision Last Edited By` — Airtable `lastModifiedBy` field, ID `fld7LFFL8kJ21WLin`, tracks only `Reviewer Decision` and `Reviewer Notes`.
- Existing `Decision Last Edited` — `fld4kIpjyHulmWM5i` (tracks same two fields).

The API field map in `src/crm_quality/decision_sync.py` is pinned to the current review Base and table. IDs are not secrets, but credentials are.

## Minimal Airtable token (one-time setup)

The existing ChatGPT-Airtable connector does **not** automatically provide credentials to the user's local PowerShell script. For repeatable local execution, create a Personal Access Token at https://airtable.com/create/tokens with:

- Name: `crm-quality-m3c-readonly`
- Only one scope: `data.records:read`
- Access: **only** `CRM Data Quality - Review Console` (one base)

Never paste the token into ChatGPT, logs, GitHub, screenshots or documentation.
In the local untracked `.env` file, add exactly one new key:

```text
AIRTABLE_REVIEW_PAT=patXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
```

This is for the local script only. Do not rename existing Postgres or HubSpot settings.

## PowerShell acceptance sequence

From `D:\projects\crm-data-quality-controlled-repair`:

```powershell
# After unzipping the M3c patch over the repository root
py -m unittest discover -s tests -v
# Expected: previous 75 tests + 23 M3c tests = 98 tests, unless extra tests exist.

# Local PostgreSQL only, no Airtable request
py scripts\m3c_sync_review_decisions.py --init-db
py scripts\m3c_sync_review_decisions.py --status

# After adding read-only PAT to .env; one GET for 60 records
py scripts\m3c_sync_review_decisions.py --preview
# Expected: total=57, available_decisions=0, unreviewed=57
```

**First human smoke test:** In the `03 · Compare Before Decision` Airtable interface, choose one clearly synthetic *pending_review* candidate. Read both records and evidence, and write a synthetic justification (at least eight characters; do not include an email, phone number or URL). Select `Same Entity` or `Different Entity` according to the evidence **as a human demo classification**, or `Needs More Evidence` if uncertain. The user must make this decision; the script does not fabricate or auto-select a verdict.

Then:

```powershell
py scripts\m3c_sync_review_decisions.py --preview
# Copy only the 64 hex characters after SNAPSHOT_SHA256=

py scripts\m3c_sync_review_decisions.py --apply --expected-digest YOUR_64_CHARACTER_SHA256
py scripts\m3c_sync_review_decisions.py --status

# Repeat --apply with a fresh --preview digest: should insert zero new events if unchanged.
```

The digest is required on every apply, so an Airtable edit between `--preview` and `--apply` makes the command fail. With 57 candidates and three blank starter rows, a full list typically needs **one Airtable API GET** per preview/apply. This is not a scheduled poller.

Do not manually edit `Queue Status`, source IDs, or metadata in Airtable. Do not record real CRM PII in notes.

## Security & budget policy

- API calls to Airtable are explicitly user-initiated and GET-only. No automatic polling. Free Airtable plans currently allow 1,000 calls per workspace per month (check official documentation for plan changes).
- `.env` (including the PAT and PostgreSQL credentials) is in `.gitignore`. Public repo patch includes no token and no reviewer decision content.
- Keep GitHub Actions `workflow_dispatch` only and run Python unit tests locally. Review `git diff --cached` before committing.
- Local PostgreSQL decision events are data; **never commit database dumps** or reviewer decision notes to GitHub.
- This is not a production-grade permission system. Threat model for actual customer data requires stronger authenticated authorization, RBAC, field-level policy, provenance, retention and recovery.

## Done criteria

- All tests pass, including fail-closed tests.
- Airtable read-only preview returns exactly 57 expected candidate identities and no unexpected records.
- The same reviewed event imports once, and repeat import yields `inserted=0`.
- Changing a decision or its notes with a later Airtable modification timestamp appends a second event, without overwriting history.
- An invalid/unsafe change or source fingerprint mismatch results in **zero** new database events.
- No CRM write, Merge or Make execution occurs.
