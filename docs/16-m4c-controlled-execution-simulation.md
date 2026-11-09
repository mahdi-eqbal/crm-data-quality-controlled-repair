# M4c — Controlled Execution Simulation, Postcheck & Compensation (Synthetic Only)

**Status:** offline patch; independent M4c tests executed in an isolated compatibility harness. **Not yet accepted on the owner's Windows checkout.** Does NOT authorize HubSpot writes. M4b fake/mock approvals are not authenticated authorizations.

## Scope and inherited gates

This milestone builds directly on the M4a country-normalization plan and M4b deterministic approval/preflight request contract. Inputs are **only** the original wholly synthetic 120 companies and 268 contact-company associations, the existing local policy, and the 31 M4b requests: 22 await an independent real approval, and 9 remain held for unresolved duplicate dependencies. All 31 requests permanently carry `write_authorized=false`, `merge_authorized=false` and `approval_recorded=false` for this milestone.

Only one fictitious operation is modelled: `company.country: "United States" -> "US"`. No contact email, record ID, customer property, ownership, other company field, association, or duplicate merge is proposed or changed. In-memory modifications exist **only** on deep copies inside an `MemoryExecutor`; source CSVs are not opened for writing.

No HubSpot, Airtable, PostgreSQL, network, Make, GitHub API, or external approval calls are present. The Python command never reads `.env`. `--report` is the only command that persists a result, as a local JSON file under the Git-ignored `private_exports/m4c/` directory.

## Behavior and safety contracts

1. **M4b source gate:** regenerate the entire original M4b approval plan from current synthetic fixture and policy files; verify the complete digest and cardinalities, individual request digests, source row SHA-256, source `updated_at`, association count/hash, allowlisted field, policy, and duplicate hold status. Reject malformed, drifted, or unexpectedly authorized requests.
2. **Mock decision gate:** a fixed synthetic self-asserted demo decision goes through the inherited M4b mock-only `preflight_request`. Claimed independent actor IDs and expiry are checked as part of the *simulation only*. Do not present this as real RBAC or verified approval.
3. **Pre-mutation TOCTOU gate:** immediately before the hypothetical mutation, independently recheck full source-row digest, the old field value, full association digest, and that the protected association copy has not changed. Stale changes block the edit; no blind overwrite.
4. **Isolated simulated operation:** write only `country` to the local copy and verify the resulting record differs in that single expected field, with association state unchanged. Keep an ordered in-memory event log for the attempt.
5. **Attempt idempotency:** an exact repeated attempt ID and payload becomes an idempotent replay without reapplying. Reusing the attempt ID with a changed payload fails closed. This is *not a durable idempotency store across restarts*.
6. **Partial batch failure:** a bounded batch may inject a failure after N simulated edits. Previously successful edits are compensated in reverse order. Exact restoration is checked. A compensation is permitted only if the current full row matches the exact expected post-state.
7. **Compensation conflict:** if a third-party-like simulated edit intervenes after the change, the engine refuses to overwrite it and reports `manual_reconciliation_required`. It does not claim full recovery.
8. **Zero external side effects:** even an apparently successful in-memory status is explicitly `simulated_verified`, never `approved`, `applied_to_crm`, or live-write-authorized. There is no import of API credentials or CRM client SDK.

**Important:** The compensation flow is a laboratory demonstration, **not an actual rollback contract** for HubSpot. There is no durable write-ahead journal, real snapshot locking or CRM conditional write/ETag guarantee, or recovery from a process crash after partial remote success. Any real-life production stage would require separate authorization, live developer-test preflight, error handling, reconciliation and narrowly permissioned write execution after explicit user consent.

## Acceptance scenarios

Run `--check` to regenerate and validate 31 non-authorizing operation packets. Run `--demo` for four in-memory scenarios:

| Scenario | Expected |
|---|---|
| Mock preflight + simulated change + postcheck | 1 verified |
| Replay of identical attempt | 1, no second simulated write |
| Source changed between preflight and simulated write | 1 blocked |
| Simulated partial failure after two operations | 2 exactly compensated |
| Postwrite conflict before compensation | 1 flagged for manual reconciliation |
| Actual approvals / HubSpot / Airtable / PostgreSQL writes, merges | **0** |

The M4c patch provides **42 offline tests**, bringing the expected whole-project total from 182 to **224** if the previous suite is unchanged. Local independent contract tests passed with stubbed M4b dependencies; **integration with the actual repository remains a required acceptance check** on Windows. Confirm the full suite, `--check`, `--demo`, and `--report` before staging any files.

## Windows PowerShell

Extract the ZIP *over the repository root*, retaining directory structure:

`D:\projects\crm-data-quality-controlled-repair`

Run only:

```powershell
cd D:\projects\crm-data-quality-controlled-repair
py -m unittest discover -s tests -v
py scripts\m4c_simulate_execution.py --check
py scripts\m4c_simulate_execution.py --demo
py scripts\m4c_simulate_execution.py --report
git check-ignore private_exports/m4c/execution_simulation.json
```

`--report` writes a **local ignored** JSON document with operation IDs, status, hashes, counts, and synthetic-only scenario outcomes; it does not export company names, emails, phone numbers or domains.

**Stop before `git add`, `git commit` or `git push`.** Verify output first. Never add ZIP files, `.env`, tokens, PostgreSQL data, private reports, customer data or local export helpers to public GitHub. Do not run GitHub Actions; all automated acceptance tests remain offline. Existing `config/quality_policy.json` and `.github/workflows/tests.yml` must not be altered by this patch.

## Next scope, separate decision

A future M4d may specify a production-relevant *execution contract* for actual authenticated approval, live read-only developer-test HubSpot preflight, conditional update semantics and crash recovery, but **do not turn on actual HubSpot writes** without a fresh explicit authorization and a new security and operational review. A synthetic PASS does not support a production readiness claim.
