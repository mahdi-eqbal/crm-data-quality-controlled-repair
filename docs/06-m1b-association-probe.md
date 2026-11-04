# M1b — HubSpot identity and read-only Contact→Company association probe

Initial probe only; no snapshots of associations yet. This is a safety check before adding PostgreSQL association tables.

## Run

From the repository root:

```powershell
py scripts\m1b_probe_associations.py
```

Check local `.env` has the existing scoped `HUBSPOT_SERVICE_KEY` and `HUBSPOT_ACCOUNT_ID=149703596`.

This script:
- Tries `GET /account-info/2026-03/details` to compare the returned `portalId` to the expected test account ID. Some keys may lack authorization for account-info, in which case the identity remains **UNVERIFIED**. Do not interpret 401/403 as successful identity verification, and do not add scopes until necessary.
- Extracts Contact IDs through the existing read-only M1a client.
- Reads each Contact's Company associations through `GET /crm/v4/objects/contacts/{id}/associations/companies`, using pagination.
- Prints only totals, not Contact or Company properties, and never writes to HubSpot or PostgreSQL.

Because the test portal currently has zero Companies, zero associations is the expected possible result. A zero result is not proof that the association integration is correctly exercised. In a later step, after explicit review and approval, use synthetic test records to prove nonzero associations and reconciliation.

No Service Key, `.env`, real CRM exports, or PostgreSQL snapshots should be committed to Git.
