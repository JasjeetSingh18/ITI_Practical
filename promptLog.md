# ERP profiling prompt log

## 1. Initial profiling request

Act as a senior data engineer experienced in manufacturing ERP systems.

Inspect all five CSV files in ./data/. Use the [SKILL.md](.agents/skills/SKILL.md)

Do not implement the final solution yet.

1. Identify schemas, data types, row counts and missing values.
2. Identify candidate primary keys and foreign keys.
3. Analyze join cardinality and potential row multiplication.
4. Inspect unique values in state, category, uom and active columns.
5. Identify suspicious records and possible business explanations.
6. Identify assumptions that require human confirmation.
7. Create 00_explore_data.py to reproduce this profiling.

Use actual file contents, not invented examples. Explain your findings before proceeding.

## 2. Confirmed business assumptions

Record grain: Assume one row per transaction (header-level); if an order ID repeats, group and sum before comparing.

Product identity/UOM: Assume all quantities share the same unit; treat P005/P015 as suspects during deduplication and flag them for human review.

Transaction scope: Assume all rows are standard forward transactions with no credits, returns, or cross-period timing gaps.

Inventory semantics: Assume counted zero means physically confirmed empty, system and count share the same cutoff, and negative stock signals an ERP posting error not a real shortage.

## 3. Implementation request

Please implement the plan.

## 4. Product matching implementation request

Implement the reviewed product matching design in 01_product_dedup.py. Use the [SKILL.md](.agents/skills/SKILL.md)

Requirements:
- Use pandas, pathlib, regex and RapidFuzz where appropriate.
- Preserve original records and normalize references separately.
- Handle null references without converting them to valid reference strings.
- Make fuzzy thresholds configurable and use scores only for candidate generation.
- Prefer active, complete and consistent records; use lowest ID as the final tie-breaker.
- Flag conflicting UOM and uncertain specifications.
- Avoid unsafe transitive grouping.
- Do not hardcode product IDs or expected results.
- Output reports/product_duplicates.csv with group_id, keep_candidate, duplicate_candidate, original_ref, match_method, similarity_score, confidence, uom_conflict, reason and recommended_action.
- Include type hints and concise comments explaining non-obvious decisions.

Run the script and report its actual output. Explain any uncertain matches.

## 5. Implementation authorization

Please implement the plan.

## Billing reconciliation request

Act as a senior ERP data engineer and accounts receivable analyst.

Inspect sales_orders.csv, deliveries.csv and invoices.csv. Use the erp-audit skill and official Odoo documentation.

Design reconciliation rules assuming delivered-quantity invoicing, but document this assumption.

Account for completed versus cancelled deliveries, posted versus draft invoices, partial shipments, missing invoices, overbilling, underbilling, incorrect prices, suspected duplicate invoices, suspected duplicate deliveries, overshipment and orphan records.

Explain join cardinality, aggregation order and financial impact formulas. Distinguish confirmed data discrepancies from suspected operational errors.

Prevent double counting financial exposure. Explain what happens if two identical-looking transactions are both legitimate.

Present a rule table before writing implementation code.

Please implement the plan.

## Billing reconciliation implementation request

Copy

Implement the reviewed reconciliation design in 02_billing_reconciliation.py.

Read the actual CSVs from ./data/ on each execution. Validate required columns, identifiers and numeric fields.

Requirements:

1. Aggregate completed deliveries and posted invoices separately before merging on so and normalized internal_ref.
2. Preserve cancelled deliveries and draft invoices as separate evidence.
3. Detect missing invoices, quantity discrepancies, price discrepancies, suspected duplicate invoices, suspected duplicate deliveries, overshipment and orphan records.
4. Use Decimal or integer cents for monetary calculations.
5. Calculate signed quantity impact, price impact and total billing gap without double counting.
6. Preserve relevant delivery and invoice IDs.
7. Do not silently delete suspected duplicates.
8. Separate uncertain exposure from other billing discrepancies.
9. Do not hardcode order IDs, amounts or expected findings.
10. Produce reports/billing_issues.csv and reports/order_reconciliation.csv, sorted appropriately.

Use readable functions and descriptive names. Run the script and show actual outputs. Explain all limitations and assumptions.

Please implement the plan.

Act as a senior QA automation engineer. Create focused pytest tests for the product deduplication and reconciliation scripts.

Test normalized reference equality, missing references, incompatible product dimensions, different cut lengths, conflicting UOM, partial shipments, cancelled deliveries, draft invoices, duplicate invoice candidates, suspected duplicate deliveries, incorrect invoice prices, many-to-many join prevention, missing columns and empty inputs.

Use synthetic fixtures for independent logic tests and the supplied CSVs for integration tests. Expected results must be calculated independently, not copied from the implementation outputs.

Run pytest and show actual results. If a test fails, explain whether the business logic or test expectation is wrong before applying fixes.
