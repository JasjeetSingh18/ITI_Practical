"""Regression checks for the read-only ERP profile."""
import csv
import io
import runpy
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
profile = runpy.run_path(str(ROOT / "00_explore_data.py"))


def report(directory):
    output = io.StringIO()
    with redirect_stdout(output):
        profile["main"](directory)
    return output.getvalue()


class ExplorationTests(unittest.TestCase):
    def test_extracts(self):
        output = report(ROOT / "data")
        for name, count in [("products", 20), ("sales_orders", 10), ("deliveries", 13),
                            ("invoices", 9), ("inventory_counts", 10)]:
            self.assertIn(f"{name}.csv | {count} rows", output)
        self.assertIn("internal_ref: text, 1 blank (P017)", output)
        self.assertEqual(output.count("1 blank ("), 1)
        for name in ("sales_orders", "deliveries", "invoices", "inventory_counts"):
            def references(table):
                with (ROOT / "data" / f"{table}.csv").open(newline="") as stream:
                    return [r["internal_ref"] for r in csv.DictReader(stream)]
            for mode, key in [("exact", str), ("trim + casefold", lambda x: x.strip().casefold())]:
                master = references("products")
                size = sum(key(src) == key(dst) for src in references(name) for dst in master if dst)
                line = next(line for line in output.splitlines() if line.startswith(f"{name} -> products ({mode})"))
                self.assertTrue(line.endswith(f"inner rows={size}"))
        for fragment in [
            "inner=12, left=14", "conflicting UOM: P005", "P015 'RC-1000-2000-065-288' (lb",
            "S103: ordered=200, done=200, cancelled=0, posted=120",
            "S104: ordered=150, done=150, cancelled=0, posted=0, draft=150",
            "S106: ordered=80, done=80, cancelled=80, posted=80",
            "S107: ordered=2400, done=2400, cancelled=0, posted=0",
            "S110: ordered=120, done=120, cancelled=0, posted=0",
            "L5009: system=-30, counted=0, variance=+30 Units | ERP posting error | physically confirmed empty",
        ]:
            self.assertIn(fragment, output)
        self.assertEqual(output.count("variance="), 6)

    def test_repeated_order(self):
        with tempfile.TemporaryDirectory() as temp:
            data = Path(temp) / "data"
            shutil.copytree(ROOT / "data", data)
            orders = data / "sales_orders.csv"
            with orders.open(newline="") as stream:
                row = next(csv.DictReader(stream))
            row["qty_ordered"] = "15"
            with orders.open("a", newline="") as stream:
                csv.DictWriter(stream, fieldnames=list(row)).writerow(row)
            output = report(data)
        self.assertIn("repeated IDs {'S101': 2}", output)
        self.assertIn("S101: ordered=515, done=500, cancelled=0, posted=500", output)
        self.assertEqual(output.count("S101: ordered="), 1)
