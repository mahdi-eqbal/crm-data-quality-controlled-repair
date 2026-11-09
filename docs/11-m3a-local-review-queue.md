# M3a — Local PostgreSQL Review Queue (synthetic-only)

**Status:** implementation and offline tests. Live local PostgreSQL execution requires user-side verification.

## Purpose

Stage M2c candidates into a transaction-backed queue before building Airtable/Make integration.
This is a **review staging system, not an approval/merge/repair implementation**. It has no HubSpot,
Airtable or Make API calls and does not read HubSpot snapshots or share data with third parties.

## Safety boundaries

- **Only** the fixed `fixtures/synthetic/` dataset is accepted (manifest seed `20261104`, 300 Contacts,
  120 Companies, 268 associations, `.example` emails/domains, synthetic IDs).
- Only 57 M2c evidence-backed candidates are staged. Of these, 50 enter `pending_review` and seven are
  `needs_evidence`, outside the main review queue.
- **114 name-only exploratory hints are not staged** because they lack corroborating identity evidence.
- Database rows contain IDs and evidence *codes* only, no names/emails/phone/CRM properties.
- `approval`, `approved_for_crm_write` and `merge_allowed` are never actionable. The database explicitly
  requires `merge_allowed = false` and `approved_for_crm_write = false` for every candidate.
- Every candidate gets a deterministic identifier; rerunning exactly the same fixture cannot create
  duplicates or reset previously created records.
- The entire batch, candidates and initial audit events are stored in one PostgreSQL transaction.
- If another synthetic batch with a different fingerprint already exists, the script fails closed.
- PostgreSQL is restricted to `127.0.0.1`/`localhost`, port `5433`, database `crm_data_quality`.
- Nothing in the script connects to HubSpot. API keys remain in `.env` and are never emitted in logs.
- The event log is append-only *by code convention*, not tamper-proof and not sufficient to authorize
  CRM operations. Reviewer decisions and authenticated authorization are separate M3b work.

## Local usage

Run from the repository root on Windows PowerShell. PostgreSQL must be `healthy`.

```powershell
docker compose ps
py scripts\m3a_review_queue.py --init-db
py scripts\m3a_review_queue.py --stage-synthetic
py scripts\m3a_review_queue.py --status
py scripts\m3a_review_queue.py --stage-synthetic
py scripts\m3a_review_queue.py --status
py -m unittest discover -s tests -v
```

Expected `--status`: `candidates=57/57`, `pending_review=50`, `needs_evidence=7`.
The second `--stage-synthetic` is an **idempotency test**, not a new batch.

## Future M3b/M3c

- M3b: create Airtable base/interface, show synthetic evidence without personal data, establish
  reviewed vs needs-evidence workflow. Scope/permissions and batch synchronization to be tested.
- M3c: add an authenticated approval callback and immutable-by-policy decision journal in PostgreSQL.
  Make will orchestrate events only. No Airtable field on its own is authorization to change HubSpot.
- M4 will separately implement policy checks, preflight, snapshots, idempotency and *approved field*
  PATCH in an isolated CRM test account. **No automatic merge.**

## GitHub usage policy

`.github/workflows/tests.yml` is now `workflow_dispatch` only: no push/PR automatic runners,
no matrix, no artifacts. Run Python tests locally for each change. At milestone release, optionally
launch the workflow from GitHub > Actions > Offline Tests > Run workflow for independent evidence.
The workflow is for offline tests only and needs **no GitHub secrets**.

Official billing guidance: standard GitHub-hosted runners in public repositories are free, but
this low-noise configuration avoids unnecessary cloud execution and does not imply that other
GitHub products (Codespaces/Models/other metered services) are free.
