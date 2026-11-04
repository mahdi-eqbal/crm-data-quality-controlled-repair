# M0 Data Contract, Profiling Rules and Synthetic Fixture Design

## Logical entities

**Contact** `record_id`, `first_name`, `last_name`, `email`, `phone`, `job_title`, `updated_at`.

**Company** `record_id`, `name`, `domain`, `country`, `industry`, `updated_at`.

**Association** `contact_id`, `company_id`, `association_type`.

These are **portable fixture fields**, not HubSpot API property names. The M1 adapter will map `first_name` → `firstname`, `last_name` → `lastname`, `record_id` → HubSpot object ID, etc., and will preserve association semantics.

## Profiling rules implemented in M0

- Null-equivalent empty/whitespace-only values count as missing.
- Email: trim whitespace before syntax test; nonempty malformed values counted separately. This is syntax checking, not deliverability checking.
- Domain: basic hostname syntax check, not proof of ownership or company identity.
- Count contacts without any association and associations referencing absent fixture records.
- Baseline output aggregates only. M0 neither proposes nor writes repairs and does not classify duplicates.

## Future matching rules (NOT IMPLEMENTED)

1. Exact or normalized stable external identifier (only when evidence permits).
2. Exact normalized email **as a candidate signal**, never as sole proof for shared addresses.
3. Normalized company domain + name; subsidiaries or shared domains need review.
4. Fuzzy name and available corroborating fields, plus explicit conflicting evidence.
5. Return `needs_review` or `distinct` when evidence is insufficient. No auto-merge.

Ground truth is separate from candidate input; maintain held-out cases. Matching on only sample values and then scoring the same fitted set would be misleading.

## Synthetic fixture coverage

- 300 contacts, including 30 deliberate duplicate pairs.
- 120 companies, including 15 deliberate duplicate pairs.
- Distinct people with equal names and distinct companies with similar names (**hard negatives**).
- Missing/malformed emails, formatting differences, incomplete phone data, missing domains.
- Contacts lacking company association and one deliberately dangling relationship for audit detection.

`ground_truth.json` is a test oracle, not a table to join at inference time. Data are fictional and use `.example` domains. The fixed generator seed ensures reproducibility.

## Proposed repair document

`schemas/repair_proposal.schema.json` is a design-time contract for future iterations; no repair proposal is processed in M0. All proposed changes must include source record, field, original/proposed value, risk, policy version and snapshot hash. Approval must be bound to this immutable proposal version.
