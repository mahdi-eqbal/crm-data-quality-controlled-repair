# M0 Execution Evidence — 2026-11-04

**Execution:** local Python 3.13.5, offline synthetic dataset.  
**Scope:** fixture generation, descriptive profiling and unit/contract checks only.

## Commands run

```bash
python scripts/generate_fixtures.py
python scripts/run_audit.py
python -m unittest discover -s tests -v
```

## Observed results

- 300 contacts, 120 companies, 268 associations.
- 30 contact same-person pairs, 15 company same-entity pairs **seeded as labels**, not detected by an algorithm.
- 26 missing contact emails, 9 malformed nonempty emails, 15 emails with surrounding whitespace.
- 14 companies missing domains, 33 contacts without company associations, 1 invalid association reference.
- 9 tests run; 9 passed; 0 failed.

## Not yet evidenced

- HubSpot API read/write connectivity, CRM normalization, real duplicate precision/recall.
- PostgreSQL persistence, Airtable Review, Make workflow, AI matching.
- Idempotent repair, version preflight, partial failure recovery and reconciliation against live CRM.

No claims of customer deployment or production reliability are made.
