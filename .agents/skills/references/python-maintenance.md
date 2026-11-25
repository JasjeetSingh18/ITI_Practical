# Maintaining the audit Python files

## Find the owner and its callers

Start with the output the user wants to change. Paths below are relative to the repository root. The [README](../../../README.md) documents supported Python versions, pinned dependency setup, CSV schemas, CLI examples, and report meanings.

| Entrypoint | Inputs and observable result | Tests under `tests/` |
| --- | --- | --- |
| `00_explore_data.py` | `main(data=DATA)` reads all five exports and prints profiles, join diagnostics, and inventory quantity variances. Tests can supply a fixture directory and capture stdout. | `test_explore_data.py` |
| `01_product_dedup.py` | `report(products, ref_threshold, name_threshold)` accepts a DataFrame and returns candidate pairs with the columns in `COLUMNS`. The CLI reads products and writes `product_duplicates.csv`. | `test_product_dedup.py` |
| `02_billing_reconciliation.py` | `reconcile(tables)` consumes sales orders, deliveries, and invoices and returns balances and issues, written to `order_reconciliation.csv` and `billing_issues.csv`. | `test_reconciliation_rules.py` |
| `02_reconcile_billing.py` | `reconcile(data)` consumes the same three tables and returns balances, exceptions, and duplicate candidates, written to `billing_reconciliation.csv`, `billing_exceptions.csv`, and `billing_duplicate_candidates.csv`. | `test_billing_reconciliation.py`, `test_reconciliation_rules.py` |

Search for both the function name and script filename. Tests load numbered scripts by path using `runpy.run_path` or `importlib`, and some call functions by dictionary key. Trace the change from reader through calculation to writer. Check argument defaults, return order, column names and order, and empty-input behavior wherever a caller relies on them.

## Check the rules at the boundary being changed

- The profiler checks exact schemas and integer quantities. Billing readers allow extra columns and parse nonnegative decimal quantities and prices. Check the owning reader before extracting shared parsing.
- The product CLI reads identifiers as strings and preserves blanks. Keep threshold flags wired to the matching function. Exercise both the candidate evidence and the proposed keeper when changing matching or ranking.
- The order-and-issues workflow trims order keys and uppercases references. It can combine repeated valid order lines when customer and price agree and retain invalid orders as unquantified balances. The balances-and-exceptions workflow uses exact keys and excludes repeated order keys as ambiguous. For a repeated-order change, exercise agreeing and conflicting lines in the affected workflow and check both its balance and issue or exception output.
- Both billing workflows aggregate shipments and invoices independently. Check a multi-shipment, multi-invoice order when changing joins or totals. Completed shipments and posted invoices drive the gap. Cancelled shipments and draft invoices have separate totals. Suspected duplicate transactions with distinct valid IDs stay in totals pending review. The README gives the signed quantity and price impact formulas.

## Add a Python file

Use a numbered root script for a runnable audit stage. Give reusable logic an ordinary importable module name when multiple callers need the same behavior. Keep argument parsing, filesystem access, and report writes behind a guarded `main()` entrypoint. Accept rows, tables, or paths at the relevant function boundary so tests can supply small fixtures. Follow existing scripts in resolving default data and report directories relative to the script.

Place behavior tests under `tests/test_*.py`. For a new stage, exercise a representative input through the entrypoint and check its observable result. Update the README when a change affects setup, commands, flags, input schemas, business rules, or reports. The manager note is a manually maintained snapshot.

## Verify the change

From the root, run the affected test modules using the environment from the README, then run `python -m pytest -q`. The shared reconciliation tests run against both billing scripts. Put workflow-specific expectations in tests scoped to that script. For CLI output checks, use a temporary output directory with `02_reconcile_billing.py --output-dir`; for fixed-path stages, exercise the writer against a temporary path or run the CLI in a disposable copy. Inspect CSV headers and rows, including source IDs and financial values when relevant.
