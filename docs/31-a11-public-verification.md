# A11 delivery verification

The public implementation includes the synthetic demo, the event contract and reconciliation logic, and the PostgreSQL outbox and audit schema. The operational runbooks and deployment configuration are maintained in the local project.

## Reproduce the synthetic checks

```powershell
python -m pip install -r requirements-m2.txt
python -B scripts/demo_controlled_repair.py
python -B -m unittest discover -s tests
```

The demo surfaces 57 synthetic match candidates and 31 country-normalization proposals. Nine proposals remain held for duplicate dependencies. The simulator verifies a mock-approved repair in memory, blocks a stale change, compensates two simulated edits and flags a recovery conflict.

The public checkout passed all 343 tests, including four static Migration 014 checks. The technical walkthrough shows the separately captured 708-test run from the full local project, which includes the operational modules.

## Inspect the delivery implementation

- [Event contract and transport](../src/crm_quality/make_orchestration.py)
- [Transport acceptance handling](../src/crm_quality/a11_async_transport.py)
- [Read-only reconciliation](../src/crm_quality/a11_delivery_reconciliation.py)
- [Outbox and delivery journal](../sql/013_a11_make_observability_outbox.sql)
- [Recovery audit schema](../sql/014_a11_recovery_evidence.sql)

The outbox stores notification events. The delivery journal distinguishes a reservation, a processing acknowledgment and an uncertain outcome. The reconciliation module checks the canonical payload, event identity and both provider records. Transport acceptance leaves downstream processing to be verified independently.

## Developer-test evidence

The local audit reconciled four acknowledged observations against Make Data Store and Airtable. The three pending observations and one uncertain observation had no corresponding mirror records at the time of the audit. Four additional provider records belonged to independent smoke tests.

The held POST returned HTTP 401. Correlation used the exact event ID, UTC time and canonical payload hash. In a separately authorized local transaction, Migration 014 created the recovery schema and recorded the rejection evidence and the decision to close the investigation without replay. The existing outbox and delivery journal were verified unchanged.

[Aggregate PostgreSQL capture](../evidence/public/a11-postgres-readonly-output.txt) · [Read-only query](../evidence/public/a11-postgres-readonly-query.sql)
