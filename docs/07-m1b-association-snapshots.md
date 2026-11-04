# M1b — Contact/Company association snapshots in PostgreSQL

**Scope:** read-only HubSpot API, local PostgreSQL append-only-by-convention snapshots. This is a test-account implementation and not a production-grade backup/recovery system.

## Prerequisites

- M1a complete and committed; source files present in `scripts/`, `sql/`, and `requirements-m1.txt`.
- M1b read-only probe installed and `ACCOUNT: VERIFIED` for portal `149703596`.
- Local PostgreSQL container healthy, `.env` configured locally, `psycopg` installed.
- Do **not** publish `.env`, database dumps, CRM exports, logs containing PII, or Snapshot JSON.

## Local commands (PowerShell, repository root)

```powershell
py scripts\m1b_snapshot_associations.py --init-db
py scripts\m1b_snapshot_associations.py --snapshot
py scripts\m1b_snapshot_associations.py --status
py -m unittest discover -s tests -v
```

`--init-db` makes two tables in **local** PostgreSQL. `--snapshot` independently verifies source `portalId`, fetches Contacts and Companies via GET, fetches **all pages** of Contact-to-Company relationships via GET, checks that target companies exist in the extracted company set, then atomically inserts a new record snapshot + association snapshot + completion manifest in local PostgreSQL. If fetch/validation fails, no partial database snapshot is committed.

The output should include `contacts=3 | companies=1 | links=1 | contacts_without_company=2` if the HubSpot test account has not changed since the successful probe. These counts are examples; actual values depend on CRM state.

## Data model

- `crm_snapshot_runs`: existing M1a run metadata.
- `crm_record_snapshots`: complete (within configured cap) scoped Contact and Company properties for the same `run_id`.
- `crm_association_snapshots`: one row per unique Contact/Company relationship, retaining `association_types` (e.g. Primary/unlabeled/custom labels) and referencing record snapshots in the **same run** by foreign keys.
- `crm_association_run_stats`: completion manifest, including zero-association runs, verified portal and expected counts.

`--status` cross-checks actual counts against the manifest. A passing status verifies local persistence/row counts, **not** that cross-object data represents a fully atomic point-in-time HubSpot view. HubSpot can change during GET pagination; snapshot times are observed timestamps.

## Safety and limitations

- No CRM POST, PATCH, PUT, DELETE or Merge calls; `Service Key` stays read-only.
- PostgreSQL is local and contains potentially sensitive test-account data; never commit it.
- Association API used: the validated HubSpot v4 read endpoint already used in M1b probe. Migration to a documented date-versioned equivalent should be assessed separately before long-term use.
- Per-contact pagination and caps remain from M1b. For large CRMs, redesign with batch-read, rate budget and streaming extraction rather than removing caps blindly.
- If a Company is deleted or newly linked mid-snapshot and cannot be found in the Company extract, extraction fails conservatively and should be retried after the CRM stabilizes.
- Old M1a runs do not include the completion manifest; `--status` lists only new M1b runs.
- Separate snapshot runs intentionally preserve history. No backfill, no CRM writes, no irreversible operations.
