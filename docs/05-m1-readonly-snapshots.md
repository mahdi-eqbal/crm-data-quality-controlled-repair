# M1a — HubSpot read-only extraction and local PostgreSQL snapshots

**Context:** Dedicated HubSpot developer test account `CRM Data Quality - Test`.
Account ID **149703596** is supplied as local configuration; this step does not independently verify the ID through an account-info endpoint. Always confirm which HubSpot account issued the Service Key before running.

## Safety rules
- No write/merge scope and no CRM mutation code. Script only calls `GET /crm/objects/2026-03/{contacts|companies}`.
- `--init-db` creates tables **locally** in PostgreSQL. `--snapshot` **writes only to local PostgreSQL**.
- Limited to max 1000 records per object; aborts before database write if a read/pagination fails.
- PostgreSQL contains possible personal data even in test accounts. Never upload DB volume, `.env`, real snapshots, logs with PII to GitHub.
- `crm_snapshot_runs`/`crm_record_snapshots` are append-only **by code convention**; they are not tamper-proof evidence and are not full backups.
- Associations are **not included in M1a**; implement and verify Association snapshots separately in M1b.
- Model does not implement incremental sync, retention/erasure, production controls, or field changes.

## Prerequisites
- Python 3.11+, Git and a Docker Desktop installation running Linux containers **or** an existing local PostgreSQL server configured with the same connection parameters.
- Working local `.env` containing `HUBSPOT_SERVICE_KEY=...` (never share it).
- New local `.env` settings:

```dotenv
HUBSPOT_ACCOUNT_ID=149703596
PGHOST=127.0.0.1
PGPORT=5433
PGDATABASE=crm_data_quality
PGUSER=crm_quality
PGPASSWORD=CHOOSE_A_UNIQUE_STRONG_PASSWORD
```

Avoid literal placeholder password. No quotation marks needed for normal ASCII letters/numbers/underscore. `compose.yaml` reads these values automatically from `.env`.

## Commands (PowerShell, from repository root)

```powershell
docker --version
docker compose version
py -m pip install -r requirements-m1.txt
docker compose up -d
docker compose ps
py scripts\m1_snapshot_hubspot.py --init-db
py scripts\m1_snapshot_hubspot.py --snapshot
py scripts\m1_snapshot_hubspot.py --status
py -m unittest discover -s tests -v
```

If Docker is unavailable, STOP before installing and discuss a local PostgreSQL or isolated Supabase alternative. Never point to a customer or production database.

## Expected first test
`contacts=2` and `companies=0` are plausible based on the last **two-record-only** connectivity probe, but the actual snapshot must read all pages (up to safety caps) to determine the counts.

The `--status` command should show `stored == contacts + companies`. Even if the count passes, M1a is not complete until we also test pagination, failure handling and associations.

## After successful execution

```powershell
git status --short
```

Before committing, inspect every staged filename. Do not stage `.env`, local credentials, database files, customer data or exported snapshots. The files in this patch are safe source templates and use no secrets.
