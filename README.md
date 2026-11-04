# CRM Data Quality, AI-Assisted Matching & Controlled Repair

**Status:** `M0 / Synthetic-first` — initial contract, fixture generator, read-only profiling and tests are implemented. **No HubSpot integration, Make scenario, Airtable Interface, AI matching, approval engine or CRM writes have been implemented yet.**

A workflow-based Revenue Systems / RevOps engineering case study—not a SaaS product. The planned architecture combines HubSpot (source CRM), Python (profiling, matching, guarded repair), PostgreSQL (operational state/audit), Airtable (human review) and Make (orchestration). AI remains conditional on measurable evaluation.

## Safety boundary

- **All supplied records are fictitious** and use the reserved `.example` domain.
- **Writes are disabled** in `config/quality_policy.json`; M0 scripts never connect to any remote system.
- No automated merge; no customer data; no API tokens; no CRM credentials.
- Before a later test-account write: snapshot, valid reviewer approval, field allowlist, current-record preflight, idempotency, verification and explicit authorization are required.
- A field snapshot is **not** a full HubSpot backup or a guarantee of rollback.

## Quick start — Python 3.11+

No third-party packages are required for M0.

```bash
python scripts/generate_fixtures.py
python scripts/run_audit.py
python -m unittest discover -s tests -v
```

Outputs:

- `fixtures/synthetic/contacts.csv` — 300 synthetic contacts.
- `fixtures/synthetic/companies.csv` — 120 synthetic companies.
- `fixtures/synthetic/associations.csv` — synthetic contact–company relationships with one deliberately invalid reference.
- `fixtures/synthetic/ground_truth.json` — **sealed evaluation labels**, including 30 synthetic contact duplicate pairs, 15 company duplicate pairs and hard negatives. Future matching code must not read this during inference.
- `evidence/baseline/baseline.json` and `.md` — **descriptive quality profile only**, not duplicate detection.

## Milestones

- **M0 (this package):** scope, safety policy, synthetic dataset, acceptance plan, offline baseline.
- **M1:** HubSpot test-account read-only extraction + PostgreSQL snapshots.
- **M2:** deterministic and fuzzy matching with held-out evaluation.
- **M3:** Airtable approval queue + Make orchestration; database-backed approval validation.
- **M4:** guarded approved *field* PATCH in test environment only.
- **M5:** verification, reconciliation and recovery testing.
- **M6 (optional):** AI-assisted ambiguous-candidate evaluation against non-AI baseline.
- **M7:** reproducible demo, runbook and market-facing case study.

## Project decisions & docs

- [`docs/01-scope-and-safety.md`](docs/01-scope-and-safety.md)
- [`docs/02-data-contract-and-rules.md`](docs/02-data-contract-and-rules.md)
- [`docs/03-acceptance-plan.md`](docs/03-acceptance-plan.md)
- [`docs/04-architecture.md`](docs/04-architecture.md)

Do not treat a passing offline fixture test as evidence that a production CRM integration works.
