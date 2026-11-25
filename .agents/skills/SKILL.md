---
name: erp-audit
description: Analyze manufacturing ERP CSV data, identify
  product duplicates, reconcile billing, and verify findings.
---

# ERP Data Audit

## Workflow
1. Inspect actual CSV schemas before proposing solutions.
2. Identify primary keys, join keys, nulls and cardinality.
3. Document business assumptions before implementing logic.
4. Preserve original data.
5. Generate reproducible reports.
6. Independently test important findings.

## Data Quality Rules
- Never silently drop anomalous records.
- Preserve identifiers and decimal precision.
- Do not treat fuzzy similarity as proof of duplication.
- Distinguish missing values from genuine zeros.
- Flag conflicting units of measure.
- Do not merge products with incompatible dimensions.

## Reconciliation Rules
- Separate completed and cancelled deliveries.
- Separate posted and draft invoices.
- Aggregate transactional data before joining.
- Flag suspected duplicates without automatically deleting them.
- Distinguish confirmed discrepancies from potential errors.
- Do not double-count overlapping financial exposure.

## Engineering Standards
- No hardcoded record IDs in business logic.
- Use small, readable functions.
- Validate input schemas and merge cardinality.
- Preserve source record IDs in reports.
- Use Decimal for financial calculations.
- Add regression tests for important edge cases.

## AI Usage
- Explain assumptions and limitations.
- Cite external documentation when used.
- Do not claim tests passed unless executed.
- Keep a record of prompts and human corrections. Use only the prompts sent by the user and append it to the prompt log file.

## Reporting
- Write concise findings for a non-technical manager.
- Separate observed facts from hypotheses.
- Recommend verification before corrective action.
