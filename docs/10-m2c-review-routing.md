# M2c — Safe review routing and weak-signal diagnostics

**Status:** offline prototype; M2a candidate generation and its thresholds are **unchanged**. This step does not use AI, HubSpot APIs, PostgreSQL, Make or Airtable. It cannot patch or merge records.

## Why M2c isn't simply a more aggressive matcher

The M2b challenge was deliberately created after inspecting M2a. Raising recall on those examples alone would encourage overfitting and could create false duplicate assertions. Seven known-positive M0 Contact pairs were not emitted by M2a due to missing or conflicting identity evidence; a name alone cannot safely resolve them. We have therefore split **candidate detection** from **review routing**, without claiming a more accurate identity classifier.

## Three review routes plus non-actionable hints

- `priority_review`: multiple correlated signals, such as matching email and highly similar name; still **requires human review**.
- `standard_review`: evidence-backed but incomplete or ambiguous; still **requires human review**.
- `needs_external_evidence`: identity conflict or shared generic identifier; not automatically eligible for the M3 main review queue. A reviewer needs further independent evidence before continuing.
- `exploratory_only`: bounded **exact full-name hints** that the original matching engine did not select. NOT identity predictions, **not eligible for normal review queue, approval, write or merge**. Retained only to document what happens when you broaden retrieval without proof.

Even `priority_review` does not imply merge eligibility. All outputs enforce `requires_human_review=true`, `merge_allowed=false`, `approved_for_crm_write=false`. No real review queue is built in M2c.

## Offline execution

```powershell
py scripts\m2c_review_triage.py
py scripts\m2c_evaluate_triage.py
py -m unittest discover -s tests -v
```

Both scripts require only the existing M2 dependency (`rapidfuzz`) and local synthetic fixtures. They do **not** read `.env`, connect to any network, or write to HubSpot/PostgreSQL. Only `m2c_evaluate_triage.py` writes a **synthetic aggregate** to `evidence/matching/M2C_TRIAGE_EVALUATION.json`; it does not export CRM data or any names/emails.

## Measured offline results (not production metrics)

- M0 original Contact positives: baseline 23/30. The optional name-only hint queue contains **114** pairs but retrieves only **1 of the 7** missed labeled positives. 29 overlarge name-blocks were deliberately skipped. Thus name-only retrieval is a noisy and incomplete substitute for strong evidence.
- On the hand-authored, fully labeled M2b challenge, the **original M2a candidate set is unchanged**: Contacts TP=2, FP=2, FN=3; Companies TP=2, FP=2, FN=0.
- Contact routing on that challenge: `priority_review` 1 TP/0 FP, `standard_review` 1 TP/0 FP, `needs_external_evidence` 0 TP/2 FP.
- Company routing: `priority_review` 1 TP/0 FP; `needs_external_evidence` 1 TP/2 FP. Importantly, the Company conflict group **also contains a true duplicate**; do not treat the group as disposable or simply reject its proposals.
- Contact `exploratory_only` hints: 3 known positives and 1 known distinct-person pair on the challenge; all remain excluded from normal review/approval routing.

**Selection-bias warning:** M2c routing was designed *after* observing the M2b errors. It is NOT validation of the improved precision of a real-world model, and it cannot be presented as an independent evaluation. The strong route's zero observed FPs in this tiny sample does not establish safety in production. We need an independently authored, blinded, fully labeled set before making accuracy claims.

## Important engineering limitations

1. A shared generic email, domain or CRM company is not proof of identity. Different email addresses do not definitively prove different people either.
2. Name-only blocking is limited to groups of 5 or fewer. The matcher still has its separate 80-record block cap; neither system guarantees exhaustive duplicate discovery.
3. Suggestions carry stable **IDs and reason codes**, not CRM PII. Future M3 may rehydrate only necessary fields with explicit data-protection review and documented retention.
4. No mutation rights exist here. Airtable approval is NOT equivalent to authorized CRM merge or patch. M4 must introduce independent DB-backed authorization, preflight and idempotency.
5. The original M0 synthetic fixture is not fully identity-adjudicated. Its contact 23/30 figure is an intentional-positive retrieval diagnostic, not a precision estimate.
6. `needs_external_evidence` may contain true duplicates. Do not silently discard such cases. Treat them as a separate research backlog.
7. M2c modifies no baseline detection thresholds and adds no AI inference.

## Definition of Done for M2c

- Existing M0–M2b tests still pass; new M2c safety/routing tests pass.
- Original M2a candidate set is unchanged.
- Reports reproduce from synthetic fixture data, with explicit limitations.
- New code/docs/evidence are committed to GitHub; `.env`, private exports and PostgreSQL data are excluded.
- M3 can design a reviewer UI using distinct statuses, without making unsupported duplicate or merge claims.
