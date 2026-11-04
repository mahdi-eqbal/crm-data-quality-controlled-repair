# M2a — Synthetic Duplicate Candidate Engine (offline)

**Status:** Offline implementation complete; local Windows execution and installed dependency verification pending.

This is NOT a CRM write, a merge engine, a repair-plan authorizer, or an AI-based identity resolver.
It uses only the committed, fully fictional M0 CSV fixtures. It does **not** read HubSpot, PostgreSQL,
Service Keys, `.env`, or `ground_truth.json` during inference.

## Why this architecture

1. **Normalization:** email whitespace/case, phone digits, Unicode/case normalization, company legal suffixes **for blocking only**.
2. **Blocking:** index on email, normalized name, phone, company domain/core name/near-name keys; no all-to-all join in normal execution.
3. **Conservative evidence rules:** normalized name alone is not an identity signal; company domains and email can be shared or reassigned.
4. **Evidence, not automatic decisions:** `strong_evidence` and `review` are **both** human-review classes. `merge_allowed=false` always.
5. **Validation:** separate evaluation script, using synthetic labels **after** running the inference code.

`name_similarity` is a RapidFuzz string similarity score (0–100), **NOT** a calibrated probability of being the same entity.

## Use (Windows PowerShell, repo root)

```powershell
py -m pip install -r requirements-m2.txt
py scripts\m2_match_synthetic.py
py scripts\m2_evaluate_synthetic.py
py -m unittest discover -s tests -v
```

Candidate CSV: `private_exports/m2/synthetic_candidates.csv` (ignored by Git on purpose).
Aggregate fixture-only evaluation: `evidence/matching/M2_SYNTHETIC_EVALUATION.json` (safe to commit if it remains synthetic).

## First offline diagnostic (run before Windows execution)

| Metric | Contacts | Companies |
|---|---:|---:|
| Intentional positive pairs | 30 | 15 |
| Positive pairs emitted as review candidates | 23 | 15 |
| Positive-candidate recall | 76.67% | 100% |
| Strong-evidence candidates | 9 | 10 |
| Curated hard negatives incorrectly in strong-evidence tier | 0 of 8 | 0 of 3 |
| Curated hard negatives flagged for manual review | 2 of 8 | 1 of 3 |

**These are fixture diagnostics, not production performance metrics.** No independent held-out test was performed.
We intentionally DO NOT report 'precision': labels do not fully adjudicate incidental collisions among all record pairs.
The 7 missed Contact positives are an important coverage limitation; generating name-only duplicate predictions to
inflate recall is not justified. Evaluate richer signals and a separate held-out fixture set before adjusting rules.

## Important risk and scalability limits

- A shared email is not necessarily a unique person (e.g. group mailbox); a shared domain is not necessarily one legal entity.
- Legal suffix removal helps find candidates, but does not assert two legally different companies are identical.
- Repeated mobile numbers and missing email/association may be inherently ambiguous.
- Candidate groups larger than `MAX_BLOCK_SIZE=80` are skipped as a bounded offline safety/performance control;
  skipped blocks can reduce recall. Production adaptation requires a measured, instrumented blocking strategy.
- No fuzzy score threshold or matching rule may autonomously trigger Merge or PATCH.
- Exact fixture performance is prone to generator-pattern overfitting; create a new held-out dataset before acceptance.
- This workflow does NOT yet match records from PostgreSQL snapshots or import candidates into Airtable.

## Done criteria for M2a

- All offline tests pass on user's environment and outputs reproducible from M0 fixture seed.
- Candidate export contains IDs/reason codes but no contact/company PII.
- Source, tests, docs and aggregate evaluation are committed in GitHub; secrets remain excluded.
- Missing positive cases and false-review burden remain documented.

## Next milestones

M2b: blocked-pair failure analysis, held-out noisy synthetic fixtures, meaningful Precision/Recall measurement;
then optionally connect read-only PostgreSQL snapshot **after** data protection review.
M3: review queue in Airtable; **no write/merge** until approved Repair Gate in M4.
