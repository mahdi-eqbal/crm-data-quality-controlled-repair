# M2b — Missing-match root causes and fully labeled challenge evaluation

**Status:** offline synthetic evaluation. No CRM or PostgreSQL access; no changes to the M2a matcher. The challenge set was *authored after reviewing M2a* and is therefore **not an independent blinded held-out test**.

## Why this step

The original M0 fixtures label only 30 Contact and 15 Company positive pairs, plus a few curated hard negatives; they do not adjudicate every possible record pair. It would be statistically misleading to claim overall precision from those labels. This patch creates a separate small challenge with complete, synthetic identity-group assignments. All pairs within an identity group are positives; all cross-group pairs are explicitly distinct by construction.

## Findings on the original M0 fixtures

Seven of 30 intentionally duplicated Contact pairs are not emitted. All seven enter candidate blocking, so the immediate cause is the rule's evidence gate, not blocking. Four have a missing email without corroborating phone/company; three have different valid emails without corroborating evidence. Names agree in this fixture, but name-only evidence is unsafe: two real people can share a name. **Do not make a name-only pair a strong match to inflate recall.**

## Controlled synthetic challenge

`fixtures/m2b_challenge/contacts.csv` and `companies.csv` contain new records, all synthetic; `identity_groups.json` contains complete labels and is loaded ONLY after inference. It includes same-name distinct people, shared generic emails, same company, changed legal suffix/domain, and missing or differing email signals.

Run from project root:

```powershell
py scripts\m2b_diagnose_and_benchmark.py
py -m unittest discover -s tests -v
```

The script writes only an aggregate synthetic evaluation to `evidence/matching/M2B_CHALLENGE_EVALUATION.json`. Do not equate the resulting pair precision with real-world duplicate merge precision: candidates are requests for human review, and the challenge set deliberately includes hard negatives. **Strong evidence is not authorization to merge.**

## Interpretation of errors

- An ordinary `review` candidate can be a false positive. These are not safe corrections.
- Some true duplicate pairs remain non-candidates without adequate corroborating evidence.
- Simple phone digit normalization misses equivalent international/national formats and can be unsafe across countries. Consider country-aware parsing in a later version, not unconditional last-10-digit matching.
- All candidate classification output must include source evidence and an explicit `requires_human_review=true`, `merge_allowed=false`.
- Not all companies sharing domains are the same legal entity; never merge by domain alone.

## Acceptance criteria

1. Full original M0 tests plus new challenge tests pass.
2. M0 missing-positive reasons are reproducible, with no raw contact PII in logs.
3. All pair confusion-matrix cells sum to all pair combinations in challenge.
4. No source code modification to the M2a matcher; no high-risk threshold increase without a separate objective.
5. No API keys, .env, data exports, database dumps, or CRM writes.

## Next design decision

Keep M2a detection rules conservative. For M2c, if market requirements justify, test a **separate, non-merging exploratory queue** for evidence-poor pairs (different from the existing `review` tier) and measure reviewer burden. For M3, only evidence-backed review candidates should be imported into Airtable; identity uncertainty must remain visible.
