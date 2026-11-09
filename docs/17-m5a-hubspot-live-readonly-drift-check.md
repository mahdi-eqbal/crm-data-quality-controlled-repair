# M5a — Verified HubSpot Developer-Test Live Read-Only Drift Check

## Status and intent

**Offline implementation tested in an integration harness. Live HubSpot/PostgreSQL acceptance is not yet verified on the owner's Windows checkout.** This is **not** repair execution readiness or permission to update CRM.

M4a–M4c use **synthetic IDs** (e.g. `O0007`); HubSpot developer-test objects have real HubSpot numeric IDs. Never map synthetic repair requests onto live developer-test records. M5a is instead an **independent read-only observation** to compare the existing latest independently verified complete M1b PostgreSQL snapshot with a fresh bounded GET-only observation of HubSpot portal `149703596`.

## Flow and hard limits

1. Read local `.env` (do not print it); require `HUBSPOT_ACCOUNT_ID=149703596` and an existing `HUBSPOT_SERVICE_KEY` with *read* permissions.
2. `GET https://api.hubapi.com/account-info/2026-03/details`, require matching `portalId` from response. Any mismatch or inaccessible account information fails closed.
3. GET Contacts and Companies using the previously established `2026-03` object endpoint with the *same minimal field lists as M1b*: contacts `firstname`, `lastname`, `email`, `phone`; companies `name`, `domain`, `country`, `phone`. **One page per object, max 10 records each.** Any pagination is a hard stop, not partial comparison.
4. GET one bounded contact→company association page for each observed contact (max 500 association results per contact, no pagination accepted). Validate target IDs exist in the complete observed company set; preserve relationship categories, type IDs and labels.
5. Open the local dedicated PostgreSQL on `127.0.0.1:5433` with `default_transaction_read_only=on`; query the latest **M1b account-verified complete run** from `crm_snapshot_runs`, `crm_association_run_stats`, `crm_record_snapshots`, `crm_association_snapshots`. Validate all stored manifest counts, original record hashes and referential integrity. No SQL mutation.
6. Compare record identities, full previously-snapshotted property hashes, source update timestamps, association identities/types. Output **aggregate counts only**; do not log or export contact names, emails, phones, domains, source record IDs, bearer tokens or full SQL rows.
7. Status `READ_ONLY_IN_SYNC` only means no detected difference against the *prior* M1b snapshot for the checked fields, not an atomic source-of-truth guarantee. `DRIFT_REQUIRES_REVIEW` means something changed and requires human investigation. Neither authorizes CRM writes, repairs or merges.

API budget: **at most 13 total GET calls**, with **no automatic retries**, for 10 contacts (1 account + 2 object lists + one association GET/contact). The known prior test account had fewer records; the tool never assumes those counts remain unchanged. To support larger data sets requires a separate scoped extension, not silently lifting caps.

Version note: This tool intentionally uses the already-tested HubSpot `/2026-03/` object endpoints to remain compatible with the existing M1b snapshot. HubSpot uses date-based API versioning; migration to a new release requires separate testing.

## Windows PowerShell commands

Extract ZIP into `D:\projects\crm-data-quality-controlled-repair` preserving directories. Do **not** overwrite `.env`, policy, old scripts or database data.

```powershell
cd D:\projects\crm-data-quality-controlled-repair
py -m unittest discover -s tests -v
py scripts\m5a_live_readonly_preflight.py --check
```

Expected *unit test* count with unchanged prior suite: **253** = 224 prior + 29 new. This does not prove live behavior.

`--check` initiates bounded real HubSpot GETs and local PostgreSQL SELECTs. It writes no files and no databases. Interpret exit codes:

- **0**: full bounded observation completed, all stored rows/associations matched; `STATUS=READ_ONLY_IN_SYNC`.
- **3**: observation completed, at least one difference; `STATUS=DRIFT_REQUIRES_REVIEW`. **Do not refresh baseline automatically** or run any repair.
- **1**: fail closed (missing account proof, wrong credentials, unsupported pagination, malformed source, baseline corruption or network failure). No comparison is accepted.

Only after inspecting the `--check` result, optionally run:

```powershell
py scripts\m5a_live_readonly_preflight.py --report
git check-ignore private_exports/m5a/live_readonly_preflight.json
```

`--report` repeats the bounded GETs and saves **only aggregate metadata** to the existing ignored `private_exports/m5a/live_readonly_preflight.json`. Treat the report as private operational evidence despite data minimization. When reporting a drift, the process exits with code 3 by design.

**No new service key, scopes, GitHub Actions, cron jobs, Make workflows or Airtable modifications are needed.** Do not upload `.env`, debug dumps, private reports or credentials to ChatGPT or GitHub.

## Boundaries and known limitations

- No HubSpot PATCH, POST, PUT, DELETE, association modification, repair, merge, or authentication of independent approvals. No PostgreSQL writes, no Airtable calls.
- No automated mapping between synthetic M4 proposals and real HubSpot records.
- A set of API GETs across multiple requests is **not an atomic snapshot**. Another actor can change data during the observation; M5a reports what it saw, not a transactionally locked state.
- HubSpot record update times may change for reasons unrelated to the selected fields; timestamp drift is surfaced separately from actual property changes.
- `READ_ONLY_IN_SYNC` is **not** a live-write preflight, concurrency control, production readiness claim, approval, or safe-rollback proof. An eventual write-authorized milestone would require independent authenticated approval, bounded conditional writes/verification, a durable journal and explicit user permission.
- If `403` occurs on account-info, the result is `FAIL CLOSED`. Never weaken verification or broaden service-key scopes merely to make this check pass without a separate reviewed plan.
- No production data: dedicated developer test account only.

## Acceptance evidence and GitHub costs

The 29 new tests use only mocked API payloads and a fake SQL cursor, checking account mismatch, partial pagination, record and association drift, source digest, PII-free output and fail-closed behavior. The 253-test integrated suite is locally testable; user acceptance needs the Windows output. Do not commit before accepting; never run GitHub Actions for this stage. Stage only the **five** explicit source/test/docs/evidence files after acceptance and preserve ZIP artifacts as untracked.
