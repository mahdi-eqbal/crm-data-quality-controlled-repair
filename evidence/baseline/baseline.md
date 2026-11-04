# M0 Synthetic CRM Data Quality Baseline

> Generated fixture data, not a customer environment.

## Counts

- contacts: 300
- companies: 120
- associations: 268

## Contacts fields

| Field | Missing | Completeness |
|---|---:|---:|
| first_name | 0 | 100.0% |
| last_name | 0 | 100.0% |
| email | 26 | 91.33% |
| phone | 120 | 60.0% |

## Companies fields

| Field | Missing | Completeness |
|---|---:|---:|
| name | 0 | 100.0% |
| domain | 14 | 88.33% |
| country | 0 | 100.0% |

## Exceptions

- Invalid nonempty email: 9
- Emails with surrounding whitespace: 15
- Contacts without association: 33
- Dangling associations: 1

This audit does **not** yet detect duplicates, issue proposals, or modify a CRM.
