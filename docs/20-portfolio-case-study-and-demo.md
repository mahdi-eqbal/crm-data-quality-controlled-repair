# Case Study — CRM Data Quality & Controlled Repair

**Role:** Revenue Systems / RevOps engineering | **Format:** workflow prototype and technical portfolio case study | **Environment:** Python, HubSpot developer test account, PostgreSQL, Airtable

## Challenge

In many CRM environments, similar names or email domains are insufficient evidence that records represent the same legal entity. Cleanup can also overwrite newer data or break relationships if the operator acts on a stale snapshot. The objective was to prototype a **review-first data quality workflow**, with observable decisions, fail-closed controls and explicit separation between detection and remediation.

## Built workflow

1. **Synthetic data quality and matching:** Generate deterministic fictitious Contacts, Companies and associations. Profile missing/invalid values; generate and evaluate deterministic/fuzzy duplicate candidates. Route ambiguity and conflicts for human review.
2. **Review and journal:** Expose the synthetic candidate queue in Airtable. Validate a human-entered decision and reviewer notes before recording append-only decision events in local PostgreSQL. Keep revisions rather than overwriting them.
3. **Reconcile:** Compare the latest Airtable state with the PostgreSQL journal; flag missing, stale, cleared or conflicting decisions. Do not turn a review outcome into a HubSpot write permission.
4. **Repair planning:** On synthetic records only, generate bounded Country normalization proposals; hold cases with duplicate dependencies. Validate proposal hashes, allowlisted fields and source association context.
5. **Mock approval and simulated execution:** Test stale source detection, fake approval binding, in-memory idempotency, post-check, partial failure compensation and manual-reconciliation triggers. All simulated changes are restricted to copies in memory.
6. **Live read-only verification:** Independently verify a HubSpot developer-test portal, fetch a capped set of objects and associations with GET, compare against a complete stored snapshot and investigate source timestamp drift without changing live records.

## Measured results (prototype evidence, not production impact)

| Evidence | Observed result | Interpretation |
|---|---|---|
| Automated tests | 309/309 local tests passed after M5c | Good prototype coverage; no production reliability claim |
| Human review queue | 57 synthetic candidates, 1 reviewed | Human decision path demonstrated; backlog mostly unreviewed |
| Decision audit | 2 revision events for 1 candidate; replay adds 0 | Idempotency demonstrated for this scenario |
| Review reconciliation | 1 in sync, 56 not reviewed, 0 conflicts | Read-only correctness for the observed snapshot |
| Field-repair plan | 31 synthetic Company Country proposals | 22 simulated reviewable; 9 held for duplicate dependency |
| Live HubSpot source | 3 Contacts, 1 Company, 1 association | Verified developer-test read-only extraction |
| Drift diagnostics | Selected properties unchanged, 3 Contact timestamps changed | Drift preserved as unexplained; no baseline reset |
| External changes | 0 HubSpot writes / 0 merges / 0 actual repair approvals | Read-only and simulated boundary respected |

**Important distinction:** The "22 reviewable" proposals are **not** approved repair operations. A simulated compensation is **not** the ability to reverse a production CRM update.

## Architecture in one line

`Fictional CRM data → Python quality/matching → Airtable human review → PostgreSQL journal → Reconciliation → Guarded synthetic repair plan → Mock approval → In-memory execution + recovery tests`

Separate live observation:

`HubSpot developer-test account (GET only) → verified object/association snapshots → local PostgreSQL baseline → bounded drift investigation`

The two branches intentionally **do not** auto-map synthetic IDs to HubSpot IDs.

## Three short technical demonstrations

These commands assume an existing configured Windows checkout. Run from the repository root. They are optional for showcasing; no need to repeat all 309 unit tests at each demo.

### 1. Synthetic execution and recovery

```powershell
py scripts/m4c_simulate_execution.py --demo
```

Show idempotent replay, stale-record blocking, compensation of two simulated edits, conflict detection and zero external writes. **This is an in-memory lab demonstration.**

### 2. Review decision reconciliation

```powershell
py scripts/m3d_reconcile.py --check
```

Show the latest Airtable review decision versus the PostgreSQL journal. This reads the connected Airtable dataset and local database but does not modify either. Do not assume the count remains 57/1 if reviewers changed records later.

### 3. Live source drift detection (optional)

```powershell
py scripts/m5a_live_readonly_preflight.py --check
```

Show independent developer-test portal verification, source/association counts and detected drift. A `DRIFT_REQUIRES_REVIEW` result is an **expected detection**, not a successful resolution or permission to change CRM. Never expose `.env`, CRM record fields or private reports in a public recording.

## Engineering choices and trade-offs

- **Human judgment over automatic merging:** Similarity alone cannot establish identity; record changes require separate authorization.
- **Fail closed on stale context:** Treat changed source timestamps, policy digests and associations as review signals.
- **Preserve decisions and evidence:** Keep revisions and reconciliation outcomes rather than silently rewriting history. The journal is append-only by application convention, not a cryptographic immutability guarantee.
- **Bound API usage:** Developer-test GETs are limited; missing/partial pages must fail rather than silently imply complete coverage.
- **Expose limitations:** Local in-memory idempotency, mock approvals and rollback simulation do not translate into safe remote production execution.

## Handoff and remaining gaps

The portfolio-scale prototype is suitable for **technical walkthroughs and architecture reviews**, not unsupervised customer deployment. Real repair execution would need authenticated reviewer authorization, narrowly scoped HubSpot write credentials, a durable operation journal, time-of-check/time-of-use protections supported by the remote API, read-after-write verification, recovery/compensation rules and explicit, separate test-environment approval. Make orchestration and AI matching are deliberately not presented as implemented.

No commercial deployment, client outcomes, time savings or revenue uplift have been independently measured. The deliverable demonstrates engineering approach and safeguards, not business ROI.
