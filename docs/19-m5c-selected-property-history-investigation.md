# M5c — Selected CRM Property History Correlation (Read Only)

**Status:** Offline implementation verified against a reconstructed subset of the project; actual HubSpot acceptance must be performed on the owner's Windows checkout. **No cause is presumed, no baseline reset, no repair permission.**

## Reason for this milestone

M5a verified portal `149703596` and found 3 Contacts, 1 Company and 1 Contact–Company association unchanged in the *selected* fields and association set, but all 3 Contacts had different `updatedAt` timestamps from the M1b baseline. M5b determined that the new update times were not a single five-minute cluster. This does **not** establish whether there were changes to other CRM properties, workflows, or integrations.

## Source API contract

HubSpot documents `propertiesWithHistory` as a query parameter of **GET** `/crm/objects/2026-03/{objectType}`. The source may return history versions with `timestamp` and `sourceType`; source type is metadata, **not verified actor attribution**. References:

- https://developers.hubspot.com/docs/api-reference/latest/crm/objects/users/get-users (generic objects List, `propertiesWithHistory` query)
- https://developers.hubspot.com/changelog/august-2022-developer-updates (sourceType semantics can change)
- https://developers.hubspot.com/docs/reference/api/overview (date-based API versioning)

M5c reuses existing M5a independent portal verification, bounded GET collection and `default_transaction_read_only=on` PostgreSQL connection. It makes **one extra GET** for all current Contacts, with `propertiesWithHistory` limited to `hs_lastmodifieddate`, `lifecyclestage`, and `hs_lead_status`. These are *not* a complete set of CRM fields. The request also restricts returned `properties` to these fields. It does not request history of names, emails or phones.

All three history rows must have the same record IDs and *exact same updatedAt timestamps* as the first M5a observation; any mismatch, pagination, unknown IDs, malformed history or oversized version list **fails closed**. No snapshot is refreshed automatically. The API budget is **at most 14 GETs** (M5a <=13 plus 1 history GET); for the known 3 Contact test account, expect **7 GETs**. Requests are single-shot without retries.

## What it can conclude

The output includes only pseudonymous per-run aliases (`changed_contact_01` etc.), counts of history versions, a count of versions within **five seconds** of a changed `updatedAt`, and allowlisted `sourceType` classes. Raw values, `sourceId`, user IDs, contact/record IDs, domains, personal fields and tokens are **never** included in CLI or JSON output. Timestamps are also omitted from the M5c per-row details; refer to private M5b report if needed.

Possible classification:

- `HISTORY_CORRELATION_OBSERVED_NO_CAUSAL_PROOF` — one or more requested property versions were temporally close to `updatedAt`, *not* proof of what caused it.
- `HISTORY_UNAVAILABLE_FOR_SELECTED_PROPERTIES` — no versions returned; not proof that nothing changed.
- `NO_NEAR_HISTORY_IN_SELECTED_PROPERTIES` — versions returned but none within five seconds; unknown cause.
- `NO_CONTACT_TIMESTAMP_DRIFT` — current observation found no contact timestamp difference, but any other M5a drift still remains actionable.

If **any** other M5a drift is detected, it is carried through to the M5c report. `cause_confirmed=false`, `write_authorized=false` and `baseline_reset=false` are always enforced. Even a `CRM_UI` or `INTEGRATION` category is observational metadata only: it is not signed actor identity and does not prove a particular user, integration, or workflow changed the record. `sourceType` values outside the hardcoded allowlist are generalized to `OTHER_OR_UNKNOWN`.

## Install and run locally (Windows)

Extract patch ZIP into `D:\projects\crm-data-quality-controlled-repair`, preserving the nested paths. The ZIP includes five **new** files and does not replace `.env`, HubSpot services, stored baseline, policy, SQL, or workflow files.

```powershell
cd D:\projects\crm-data-quality-controlled-repair
py -m unittest discover -s tests -v
py scripts\m5c_property_history_diagnostics.py --check
```

There are **36 new offline unit tests**. The owner's previously verified total was **273**, so the expected full suite is **309** if unchanged. An independent reconstructed checkout contained 267 preceding tests (missing six pre-existing M1b probe tests from the reconstruction) and passed **303 including M5c**. This is not a substitute for the full owner checkout acceptance.

`--check` makes real GET requests and PostgreSQL **SELECT only**, but writes no files. Exit codes: **0** = no M5a drift, **3** = M5a drift still exists, **1** = blocked/invalid observation. `3` is intentional, not a crash. A `403` or unavailable property history should not trigger adding scopes or changing the service key automatically.

After inspecting the `--check` output, optionally run:

```powershell
py scripts\m5c_property_history_diagnostics.py --report
git check-ignore private_exports/m5c/property_history_diagnostics.json
```

`--report` repeats the GET requests and atomically writes only a private Git-ignored JSON. Do not share raw HubSpot payloads, test account key or local `.env` in chat or public GitHub.

## Non-goals / future direction

- No full property history audit, no private user IDs, no claims of who/what caused changes, no activity log or workflow audit access.
- No POST/PATCH/PUT/DELETE/merge, no PG/Airtable write, no real approval, no mapping between synthetic M4 proposals and HubSpot objects.
- A new M1b baseline would need independent evidence review, not automatic drift suppression.
- Stop at the selected-property diagnostic if history does not establish cause. Additional scopes and broad audit access should require a separate necessity/privacy assessment.
- GitHub Actions is `workflow_dispatch` only in this repo; do not run it for acceptance. Work locally and stage only the five named M5c files after the owner verifies outputs.
