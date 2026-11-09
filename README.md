# CRM Data Quality & Controlled Repair

**Revenue Systems / RevOps engineering case study** — a review-first technical workflow for detecting suspected CRM duplicates, controlling low-risk data-quality repairs, and preserving auditable decisions.

**Status — November 2026:** Working prototype, **not production-write-ready**. The HubSpot developer-test integration is **GET-only**. Matching and repair simulations use fictitious data; the human review interface is in Airtable and durable decision evidence is in local PostgreSQL. **No HubSpot PATCH, merge, or real CRM repair has been performed or authorized.**

## Problem and workflow

Duplicate records, inconsistent values and stale CRM assumptions can lead to incorrect routing, bad attribution and risky manual cleanup. This project separates **candidate detection**, **human review**, **repair planning**, **preflight validation**, and **execution authorization** rather than interpreting a match score as permission to merge.

`Synthetic CRM fixtures → Profiling / matching / triage → Airtable review → Validated PostgreSQL decision journal → Reconciliation → Guarded repair plan → Mock approval and in-memory execution → Verification / exception reporting`

A separate **HubSpot developer-test read-only path** provides observed Contacts, Companies and associations and reports source drift. **Synthetic repair proposals are never mapped automatically to live HubSpot records.**

## Evidence by layer

| Layer | Demonstrated | Safety / limitation |
|---|---|---|
| Data profiling | Deterministic fictitious fixtures and quality baseline | Does not prove production data quality |
| Duplicate discovery | Deterministic and fuzzy candidate matching, challenge-set evaluation, evidence-based routing | Candidates require human review; no automatic merges |
| Human decision workflow | Airtable review console, decision validation and append-only-by-application-convention PostgreSQL journal | Synthetic review records; one reviewed case demonstrated, not 57 completed reviews |
| Reconciliation | Latest Airtable decision compared against PostgreSQL history, revisions and conflicts | Read-only; no automatic reconciliation writes |
| Repair planning | Synthetic Company Country normalization proposal and dry run | 31 proposals: 22 simulated as reviewable; 9 held for duplicate dependencies |
| Approval & preflight | Proposal digests, policy and freshness gates, mock independent-review conditions | **Mock identities are not authenticated approvals** |
| Execution & recovery | In-memory idempotent replay, pre-mutation checks, partial-failure compensation and conflict detection | No real CRM writes or guaranteed remote rollback |
| HubSpot read-only integration | Verified developer-test portal, bounded GETs, PostgreSQL snapshots, association integrity and drift checks | Not atomic, no production write readiness |

### Observed acceptance evidence

- **309/309 automated tests passed locally** on Windows after M5c (November 9, 2026). Unit tests are not proof of production reliability.
- The synthetic review queue contained **57 candidates**, with **one human decision** and a later notes revision. The PostgreSQL journal retained **two events for one candidate**; repeating the same revision inserted no new event.
- Review reconciliation observed **1 synchronized decision, 56 not reviewed and 0 conflicts** for that snapshot.
- The synthetic repair pipeline identified **31 country-value proposals**. Of these, **22** were simulated through guarded planning and **9** remained blocked by duplicate dependencies. No actual approvals were granted.
- A bounded live developer-test HubSpot comparison observed **3 Contacts, 1 Company, and 1 Contact–Company association**. The selected properties and associations matched the earlier stored snapshot; all **3 Contacts' `updatedAt` values had changed**.
- Follow-up diagnostics showed those timestamp changes did not form a five-minute cluster. Selected-property history returned **no events near the changed timestamps**. **Cause unresolved; baseline preserved and drift remains flagged.** This does not establish that other HubSpot properties or system events were unchanged.

Private source identifiers, access tokens, customer information and local reports are not published.

## Technical components

**HubSpot API**, **Python**, **PostgreSQL**, **Airtable**, **SQL**, deterministic/fuzzy matching, evidence-based triage, SHA-256 integrity checks, read-only preflight and offline tests.

- `scripts/m1b_snapshot_associations.py` — verified GET-only object/association snapshot to local PostgreSQL
- `scripts/m2_match_synthetic.py` and `scripts/m2c_review_triage.py` — synthetic matching and routing
- `scripts/m3c_sync_review_decisions.py` and `scripts/m3d_reconcile.py` — decision journal and reconciliation
- `scripts/m4a_plan_repairs.py`, `scripts/m4b_approval_preflight.py`, `scripts/m4c_simulate_execution.py` — synthetic repair planning and guarded simulation
- `scripts/m5a_live_readonly_preflight.py`, `scripts/m5b_timestamp_diagnostics.py`, `scripts/m5c_property_history_diagnostics.py` — developer-test HubSpot read-only drift investigation

See [case study and demo notes](docs/20-portfolio-case-study-and-demo.md) and the milestone documentation in `docs/`.

## Minimal local verification

These checks have different scopes and are **not a single atomic workflow**. Use only when needed:

```powershell
# Synthetic execution / recovery demo (offline)
py scripts/m4c_simulate_execution.py --demo

# Read-only review reconciliation (Airtable GET + local PostgreSQL)
py scripts/m3d_reconcile.py --check

# Optional: developer-test HubSpot GET-only observation against local baseline
py scripts/m5a_live_readonly_preflight.py --check
```

For the latest diagnostics alone, the targeted unit test is:

```powershell
py -m unittest discover -s tests -p "test_m5c_history_attribution.py"
```

The full suite `py -m unittest discover -s tests -v` should be run at final release acceptance or after changes that cross module boundaries, not for documentation-only edits. The GitHub Actions test workflow is **manual-dispatch only**. A live `DRIFT_REQUIRES_REVIEW` result exits with code `3` by design; do not treat it as clearance to proceed with a repair.

## What is *not* claimed

This prototype is **not** a production CRM repair engine, a deployed SaaS product, an autonomous agent or a customer implementation. It does **not** implement live authenticated repair approvals, remote conditional PATCH semantics, crash-durable execution journaling, guaranteed rollback, automatic HubSpot merges, Make orchestration or a measured commercial ROI. Those require separate authorization, design, risk review and controlled testing.

**Data handling:** `.env`, tokens, live record values and `private_exports/` must remain local/private. Passing simulations never authorize a CRM write.
