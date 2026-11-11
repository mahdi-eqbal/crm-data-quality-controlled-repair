# CRM Data Quality, AI-Assisted Matching & Controlled Repair

*Technical case study · Project 01*

CRM teams need to investigate ambiguous records and document why a repair was approved. Project 01 separates candidate matching, reviewer decisions, controlled changes and operational evidence so a reviewer can trace each decision to its source.

## How the workflow works

The workflow captures CRM snapshots, screens candidate records and stages evidence for review. The runnable demo uses deterministic and fuzzy matching to surface candidates. AI-assisted candidate evaluation belongs upstream of the approval boundary. Review and preflight determine whether a proposed change can proceed. The sandbox path is designed to check fixture provenance and preconditions before a bounded patch, verify observed changes afterward and retain evidence for manual reconciliation.

The offline demo found 57 synthetic match candidates, all requiring review. Of 31 synthetic country-normalization requests, nine were held for duplicate dependencies. The other 22 were eligible for mock review. The simulation demonstrated one verified change, idempotent execution, stale-data blocking, compensation of two in-memory edits and a recovery conflict that required review.

A11 adds a PostgreSQL outbox for selected observations from the review, preflight, sandbox patch and recovery stages. Stable event IDs and SHA-256 digests support reconciliation against Make Data Store and an Airtable operations timeline. The PostgreSQL journal records reservation, processing acknowledgment and uncertain outcome as distinct states. An accepted HTTP request leaves processing to be verified independently.

## What the recovery audit showed

The November 11 audit read eight PostgreSQL observations and matched four existing acknowledgments to Make and Airtable. Three observations were pending, and one remained held after an HTTP 401. A follow-up review matched the rejected POST to the local reservation using the event ID, timestamp and canonical payload hash. The provider inventories contained four additional smoke-test events. Each had a matching mirror record, and all four were excluded from local delivery counts.

The audit showed how the workflow handles ambiguous outcomes while preserving the original journal. Migration 014 recorded the rejection evidence and the operator-approved decision to close the investigation without replay. The original journal state and delivery hold were preserved.

## Evidence and limits

The verification covered synthetic tests, a read-only PostgreSQL audit and point-in-time provider inventories. The mock review and simulated changes ran in memory. The A11 findings came from the developer-test workflow and observed provider records. Customer deployment, production throughput, business savings and exactly-once delivery were outside the evaluation. The [offline walkthrough](../README.md#run-the-demo) reproduces the synthetic portion.
