# Acceptance Test Matrix and Evidence Plan

## M0 — acceptance gates

- [x] Deterministic generator produces 300 contacts / 120 companies with known labels.
- [x] Fixture data remain synthetic; email domains end in `.example` (malformed examples remain synthetic).
- [x] Labels include positives and near-match negatives; no real customer data.
- [x] Offline profiler emits JSON and Markdown baseline with record counts and quality metrics.
- [x] Automated tests confirm deterministic output, unique object IDs, and a dangling association.
- [x] Runtime policy explicitly disables writes and automated merges.
- [ ] Stakeholder accepts scope and risk rules before M1 setup.

## M1 — read-only extraction (future)

- Read-only access to an isolated HubSpot developer test account.
- Correct pagination, field and association mapping, controlled retries and `429` handling.
- Snapshot counts reconcile with test CRM; rerun does not corrupt prior runs.

## M2 — matching (future)

- Positive-pair precision/recall on held-out labels; hard negatives not misrepresented as true duplicates.
- Explanation and conflict features for every suggested pair; low confidence abstains.
- No merge actions, no CRM updates.

## M3 — approvals (future)

- Reviewer identity verified server-side; approval references unchanged proposal version.
- Repeated or stale approvals do not create additional operations.
- Rejected cases never reach executor.

## M4/M5 — repair + reconciliation (future)

- Every write uses approved allowlist and pre-change snapshot.
- Deliberate timeout after successful PATCH does not trigger blind duplicate write.
- Concurrent modification results in conflict rather than overwrite where detectable.
- Applied fields are independently verified through a CRM direct read.
- No unexplained status/count differences after failed or partial batches.
- Merge and association modification remain disabled.

## M6 — AI (conditional, future)

- Compare with baseline on separate evaluation examples; track precision, false positives, review time, cost, abstention.
- No model output is treated as a write authorization; do not send sensitive data without permission and privacy review.

## Evidence handling

Record command, date, synthetic seed, test result and failure cause for each milestone. Do not claim production reliability based on synthetic/offline tests. Never publish tokens, CRM exports, actual client identifiers or unredacted logs.
