"""Read the five ERP extracts and print a read-only profile."""
import csv
import re
import sys
from collections import Counter, defaultdict
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

DATA = Path(__file__).resolve().parent / "data"
SCHEMAS = {
    "products": "product_id internal_ref name uom category active",
    "sales_orders": "so customer internal_ref qty_ordered unit_price order_date due_date",
    "deliveries": "delivery so internal_ref qty_shipped ship_date state",
    "invoices": "invoice so internal_ref qty_invoiced unit_price invoice_date state",
    "inventory_counts": "lot internal_ref location uom system_qty counted_qty",
}
TYPES = {
    "integer": (int, "qty_ordered qty_shipped qty_invoiced system_qty counted_qty"),
    "decimal": (Decimal, "unit_price"),
    "date": (date.fromisoformat, "order_date ship_date due_date invoice_date"),
    "boolean": ({"True": True, "False": False}.__getitem__, "active"),
}
FIELDS = {col: (label, parse) for label, (parse, cols) in TYPES.items() for col in cols.split()}


def read_table(path, columns):
    rows = []
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream, strict=True)
        try:
            if sorted(reader.fieldnames or []) != sorted(columns):
                raise ValueError(f"{path}: expected {columns}, found {reader.fieldnames}")
            for raw in reader:
                if None in raw or None in raw.values():
                    raise ValueError(f"{path}:{reader.line_num}: wrong number of fields")
                row = {}
                for col, value in raw.items():
                    parse = FIELDS.get(col, ("text", str))[1]
                    try:
                        parsed = parse(value) if value.strip() else None
                        if isinstance(parsed, Decimal) and not parsed.is_finite():
                            raise ValueError("nonfinite price")
                    except (ValueError, KeyError, InvalidOperation) as exc:
                        raise ValueError(f"{path}:{reader.line_num}: invalid {col} {value!r}") from exc
                    row[col] = parsed
                row["_line"] = reader.line_num
                rows.append(row)
        except csv.Error as exc:
            raise ValueError(f"{path}:{reader.line_num}: {exc}") from exc
    return reader.fieldnames, rows


def group(rows, *cols):
    groups = defaultdict(list)
    for row in rows:
        groups[tuple(row[c] for c in cols)].append(row)
    return groups


def ids(rows, key):
    return ", ".join(str(r[key] or f'line {r["_line"]}') for r in rows) or "—"


def profile(name, columns, rows, pk):
    print(f"\n{name}.csv | {len(rows)} rows")
    for col in columns:
        missing = [r for r in rows if r[col] is None]
        dtype = FIELDS.get(col, ("text", str))[0]
        detail = f" ({ids(missing, pk)})" if missing else ""
        print(f"  {col}: {dtype}, {len(missing)} blank{detail}")
        if col in {"state", "category", "uom", "active"}:
            counts = Counter(r[col] for r in rows if r[col] is not None)
            print("   ", ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    duplicates = {k: len(v) for (k,), v in group(rows, pk).items() if k and len(v) > 1}
    print(f"  Candidate PK {pk}: {sum(r[pk] is None for r in rows)} blank, repeated IDs {duplicates}")


def match_profile(label, parents, children, cols, pk, normalize=False):
    def key(row):
        values = tuple(row[c] for c in cols)
        return tuple(v.strip().casefold() if v else None for v in values) if normalize else values

    counts = Counter(key(r) for r in parents if all(r[c] is not None for c in cols))
    matches = [counts[key(r)] for r in children]
    absent = [r for r, n in zip(children, matches) if n == 0]
    many = [r for r, n in zip(children, matches) if n > 1]
    print(f"{label} | zero={len(absent)}, one={matches.count(1)}, multiple={len(many)}, "
          f"inner rows={sum(matches)}")
    if absent or many:
        print(f"  unmatched IDs: {ids(absent, pk)} | multiple-match IDs: {ids(many, pk)}")


def joins(tables):
    print("\nJoin cardinality (all document states)")
    for name, rows in tables.items():
        if name == "products":
            continue
        pk = SCHEMAS[name].split()[0]
        for normalized in (False, True):
            method = "trim + casefold" if normalized else "exact"
            match_profile(f"{name} -> products ({method})", tables["products"], rows,
                          ["internal_ref"], pk, normalized)
        if name in {"deliveries", "invoices"}:
            for cols in (["so"], ["so", "internal_ref"]):
                match_profile(f"{name} -> sales_orders ({', '.join(cols)})",
                              tables["sales_orders"], rows, cols, pk)
    cols = ("so", "internal_ref")
    deliveries = group(tables["deliveries"], *cols)
    invoices = group(tables["invoices"], *cols)
    inner = left = 0
    for r in tables["sales_orders"]:
        key = tuple(r[c] for c in cols)
        d, i = (0, 0) if None in key else (len(deliveries[key]), len(invoices[key]))
        inner += d * i
        left += max(1, d) * max(1, i)
    print(f"Orders joined to both child tables on {cols}: inner={inner}, left={left}")


def product_review(rows):
    print("\nProduct references for human review")
    candidates = defaultdict(list)
    for r in rows:
        ref = r["internal_ref"]
        if ref is None:
            print(f"  {r['product_id']}: missing reference, {r['name']}")
            continue
        # Compare decimal formatting within codes without changing master data.
        key = re.sub(r'\d+\.\d+', lambda m: format(Decimal(m[0]).normalize(), 'f'),
                     ref.strip().casefold())
        candidates[key].append(r)
    for records in candidates.values():
        if len(records) < 2:
            continue
        reason = "conflicting UOM" if len({r["uom"] for r in records}) > 1 else "possible alias"
        detail = ", ".join(f"{r['product_id']} {r['internal_ref']!r} ({r['uom']}, active={r['active']})"
                           for r in records)
        print(f"  {reason}: {detail}")


def total(rows, field):
    values = [r[field] for r in rows]
    return None if None in values else sum(values)


def difference(a, b):
    return "unknown" if a is None or b is None else f"{a - b:+}"


def transactions(tables):
    print("\nOrder quantities (header totals, shared units, forward transactions at one cutoff)")
    orders, deliveries, invoices = (group(tables[t], "so") for t in
                                   ("sales_orders", "deliveries", "invoices"))
    for (so,), lines in orders.items():
        if so is None:
            continue  # Already identified by source line in the candidate-key report.
        ds, inv = deliveries[(so,)], invoices[(so,)]
        ordered = total(lines, "qty_ordered")
        shipped, cancelled = (total([r for r in ds if r["state"] == state], "qty_shipped")
                              for state in ("done", "cancelled"))
        posted, draft = (total([r for r in inv if r["state"] == state], "qty_invoiced")
                         for state in ("posted", "draft"))
        print(f"  {so}: ordered={ordered}, done={shipped}, cancelled={cancelled}, posted={posted}, "
              f"draft={draft}, done-ordered={difference(shipped, ordered)}, "
              f"posted-done={difference(posted, shipped)} | {ids(ds, 'delivery')} | {ids(inv, 'invoice')}")
        for invoice in inv:
            prices = {r["unit_price"] for r in lines if r["internal_ref"] == invoice["internal_ref"]}
            if len(prices) != 1 or None in prices or invoice["unit_price"] is None:
                print(f"    {invoice['invoice']}: order/invoice price comparison unresolved")
            elif invoice["unit_price"] not in prices:
                expected = next(iter(prices))
                print(f"    {invoice['invoice']}: invoice price={invoice['unit_price']}, order price={expected}")
    for table, pk, fields in [
        ("deliveries", "delivery", "so internal_ref state ship_date qty_shipped"),
        ("invoices", "invoice", "so internal_ref state qty_invoiced unit_price"),
    ]:
        for key, rows in group(tables[table], *fields.split()).items():
            if len(rows) > 1:
                print(f"  Review repeated {table} details {key}: {ids(rows, pk)}")


def main(data=DATA):
    tables = {}
    for name, schema in SCHEMAS.items():
        columns, rows = read_table(data / f"{name}.csv", schema.split())
        tables[name] = rows
        profile(name, columns, rows, schema.split()[0])
    joins(tables)
    product_review(tables["products"])
    transactions(tables)
    print("\nInventory variances (counted minus system, same cutoff)")
    for r in tables["inventory_counts"]:
        system, counted = r["system_qty"], r["counted_qty"]
        posting_error = system is not None and system < 0
        if system is None or counted is None or counted != system or posting_error:
            note = " | ERP posting error" if posting_error else ""
            if counted == 0:
                note += " | physically confirmed empty"
            print(f"  {r['lot']}: system={system}, counted={counted}, "
                  f"variance={difference(counted, system)} {r['uom']}{note}")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError) as error:
        sys.exit(str(error))
