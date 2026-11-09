# M5b — Timestamp Drift Diagnostics (Read Only)

This is an investigatory follow-up to M5a, not a CRM repair milestone.

## Known evidence before this patch

The independently verified M5a observation found the same three Contacts, one Company and one Contact→Company association as the latest M1b baseline; selected property values and association types were unchanged. All three Contacts had different `updatedAt` timestamps. Nothing in this evidence proves the source of those changes, or that unrequested properties were unchanged.

## What this does

- Reuse the **exact** M5a bounded GET-only collector, portal verification and read-only PostgreSQL baseline reader (at most 13 HubSpot GETs, zero retries).
- Show an **ephemeral anonymous alias** for each Contact with a changed timestamp, along with old/new timestamps in UTC, delta seconds and direction.
- Compute the spread between observed current update timestamps and flag a narrow 5-minute cluster as a temporal pattern **only**. This is not evidence of who/what caused it.
- Classify the observed difference as `TIMESTAMP_ONLY_IN_OBSERVED_SCOPE`, `OTHER_DRIFT_ALSO_PRESENT` or `NO_DETECTED_DRIFT`.
- Preserve the existing M1b baseline, the M5a report and all decision/repair state; issue no approval and no changes to HubSpot, PostgreSQL, or Airtable.
- Never include HubSpot record IDs, contact names, emails, phone numbers or properties in the output or the optional private JSON. Timestamps may be quasi-identifying; the report is private and must not be committed to public GitHub.

## Windows PowerShell

Extract the patch ZIP over the root of `D:\projects\crm-data-quality-controlled-repair` preserving subfolders. This patch contains five new files only, and replaces no prior M5a implementation, policy, `.env`, workflow or database schema.

```powershell
cd D:\projects\crm-data-quality-controlled-repair
py -m unittest discover -s tests -v
py scripts\m5b_timestamp_diagnostics.py --check
```

Expected total tests with unchanged checkout: **273** = 253 + 20 new offline M5b tests. The `--check` mode does not write any file. If the earlier M5a observations remain unchanged, the status should be `TIMESTAMP_ONLY_IN_OBSERVED_SCOPE` with three changed contacts; exact deltas and clustering cannot be predicted before a live read.

After reviewing check results only, optionally run:

```powershell
py scripts\m5b_timestamp_diagnostics.py --report
git check-ignore private_exports/m5b/timestamp_diagnostics.json
```

`--report` writes the latest diagnostic locally under an already Git-ignored folder; there are no database writes. Exit codes: `0` = M5a reports in-sync, `3` = drift observed, `1` = fail closed. An exit code of 3 is not a script crash.

## Safety and interpretation

- This is **observational**, not a transactionally atomic CRM snapshot, authenticated approval, live-write preflight, or rollback guarantee.
- Identical *selected* properties do not establish that other fields or metadata were unchanged. Do not assume the observed timestamp differences are harmless.
- A cluster of update timestamps is consistent with many possible causes; it does not establish a batch process, API writer, CRM automation or association editing.
- Preserve prior baseline and do not mark `READ_ONLY_IN_SYNC` by suppressing timestamp comparison.
- No new service key, scopes, scheduled automation, or GitHub Actions needed.
