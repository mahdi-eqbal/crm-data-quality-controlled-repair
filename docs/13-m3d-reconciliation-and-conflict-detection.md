# M3d — Read-Only Reconciliation & Conflict Detection

## Purpose and delivery boundary

Provide an **independent, read-only comparison** between the 57 known synthetic review candidates in Airtable and the append-only PostgreSQL decision journal produced by M3c. This is a workflow-based CRM quality case study; it is **not** a CRM-write, merge-approval or automatic remediation system.

The local command validates:

1. All 57 candidate identities, source fingerprint, evidence metadata and routing fields through the existing M3c source validator.
2. The 57-row PostgreSQL synthetic review batch, all 57 candidate fields, and the two safety flags (`merge_allowed = false`, `approved_for_crm_write = false`).
3. Every stored decision event: candidate identity, chronological order, stable Airtable record provenance, payload SHA256 and deterministic event UUID.
4. The newest Airtable classification against the most recent PostgreSQL event for each candidate.

**No modification is made to Airtable, PostgreSQL, GitHub or HubSpot.** This tool uses one explicit Airtable GET (for the current 60-row table), and local PostgreSQL SELECTs in a read-only repeatable-read transaction. It does not invoke Make or AI.

## Architecture

```
                      Airtable Review Candidates
                        | GET only; all 60 rows
                        v
                 M3c source validation
                        | 57 expected candidates
                        v
   local PostgreSQL --> M3d reconciliation --> console summary
   (READ ONLY)          / conflict detection       |
       |                        |                    +--> optional local, gitignored JSON
       +--> 57 queue rows       +--> manual action only
       +--> decision event history
```

## Status classification

| Status | Meaning | Action |
| --- | --- | --- |
| `in_sync` | Latest Airtable decision hash and timestamp equal latest stored event | No action |
| `not_reviewed` | No decision in either system | No action |
| `pending_import` | Airtable has a new decision/revision absent from PostgreSQL | Run the existing **M3c** `--preview` then separately approve a digest-gated `--apply` |
| `cleared_in_airtable` | PostgreSQL retains an event but Airtable no longer has a decision | Investigate; no automatic clearing |
| `stale_airtable` | Airtable decision timestamp predates the latest PostgreSQL event | Investigate timing/source integrity |
| `same_timestamp_conflict` | Same timestamp but different, internally valid payload | Investigate; no automatic selection |

A source identity, field, batch or event hash violation is **fail-closed** (`exit code 1`), not an ordinary discrepancy. The count of `revisions` is the number of stored events *beyond the first event for each classified candidate*. It is not the number of decisions currently visible in Airtable.

## Local Windows PowerShell verification

Prerequisites already established in M3c: active local Docker PostgreSQL at `127.0.0.1:5433`, `psycopg[binary]`, existing `.env` with `PG*` settings and **Airtable-only read token** `AIRTABLE_REVIEW_PAT`. Do not paste or show `.env`, credentials or database dumps.

Extract the M3d patch **into the existing repo root** (preserving folders), then:

```powershell
cd D:\projects\crm-data-quality-controlled-repair
py -m unittest discover -s tests -v
py scripts\m3d_reconcile.py --check
```

Expected immediately after the already verified M3c second revision and repeat test, provided nothing changed in Airtable:

```
M3d READ-ONLY RECONCILIATION (synthetic-only)
candidates=57 | airtable_decisions=1 | postgres_events=2 | revisions=1
in_sync=1
not_reviewed=56
pending_import=0
cleared_in_airtable=0
stale_airtable=0
same_timestamp_conflict=0
RECONCILED=YES
Airtable=GET only | PostgreSQL=READ ONLY | crm_writes=0 | merges=0
```

**The above is expected output, not PowerShell commands.** Copy only the lines in the `powershell` fenced code blocks. If the user edited Airtable again, a `pending_import` finding may be correct; do not force it into sync without reviewing the new snapshot.

To create a *local-only, gitignored* machine-readable report:

```powershell
py scripts\m3d_reconcile.py --report
```

The report is written to `private_exports/m3d/reconciliation_report.json` (already ignored by `.gitignore`). The report deliberately excludes reviewer notes, reviewer IDs, emails, token values and detailed CRM fields. It includes only synthetic candidate keys for actionable discrepancies and source fingerprints.

Exit codes: **0** = reconciled (may still have `not_reviewed` candidates), **2** = valid sources but reconciliation discrepancies, **1** = fail-closed validation, database or API failure. A mismatch code does not automatically trigger an import or repair.

## Offline safety tests and negative paths

`tests/test_m3d_reconciliation.py` covers a synchronized two-revision case, no-decision baseline, pending import, stale Airtable, cleared decisions, same-timestamp conflicting notes/verdict, unknown candidates, tampered hashes/UUIDs, invalid payloads, duplicate and out-of-order events, changed Airtable record provenance, incomplete candidate coverage, and unexpected authorization flags in PostgreSQL. All tests are synthetic and do not issue API/database requests.

**Important limits:**

- This is *observational reconciliation*, not a distributed transaction or lock across Airtable and PostgreSQL. An edit after a GET may not appear in this report. Rerun before taking action.
- Airtable last-modified field observes only the latest edit between imports; intervening unsynchronized edits may be lost from the source revision stream.
- The PostgreSQL role and table owner are not cryptographically immutable. A privileged admin can still alter audit data. For production, require stronger RBAC, immutable offsite exports, tested backup/recovery and change approvals.
- SHA256 is a consistency digest, **not** identity, authenticity, or legal-entity proof. Reviewer classification never grants CRM write permission.
- This patch does not implement automatic conflict resolution, Make polling, CRM writes, snapshots of actual customer PII, or migration.
- All tests and data remain synthetic. The public portfolio must not claim live customer or production use.

## Definition of done (M3d)

1. All offline unit tests pass locally.
2. `--check` reports all 57 candidates, 2 events / 1 revised candidate, `in_sync=1`, `not_reviewed=56`, and **zero discrepancies** on the current local data.
3. Optional report is stored only at `private_exports/m3d/`.
4. Re-running `--check` does not write any new database event, change Airtable or call HubSpot.
5. Source inconsistency fails closed and all discrepancies are handled only after explicit review.
6. Commit only the five patch files after successful local verification; do not upload local reports or `.env`.
