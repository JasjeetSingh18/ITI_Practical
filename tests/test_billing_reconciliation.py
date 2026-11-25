import importlib.util
from decimal import Decimal
from pathlib import Path

spec = importlib.util.spec_from_file_location('billing', Path(__file__).resolve().parents[1] / '02_reconcile_billing.py')
billing = importlib.util.module_from_spec(spec)
spec.loader.exec_module(billing)


def test_full_export():
    data = {name: billing.read_table(billing.ROOT / 'data' / f'{name}.csv', fields) for name, fields in billing.SCHEMAS.items()}
    results, exceptions, candidates = billing.reconcile(data)
    lines = {r['so']: r for r in results}
    assert not exceptions
    assert sum(r['shortfall'] for r in results) == Decimal('27885')
    assert sum(r['excess'] for r in results) == Decimal('6330')
    assert lines['S103']['delivered_qty'] == 200
    assert lines['S106']['cancelled_qty'] == 80
    assert lines['S104']['draft_qty'] == 150
    assert lines['S109']['price_variance'] == -800
    assert lines['S108']['billing_variance'] == -4600
    assert {r['record_id'] for r in candidates} == {'D210', 'D211', 'I302', 'I309'}
    assert all(r['billing_variance'] == r['quantity_variance'] + r['price_variance'] for r in results)


def test_many_to_many_and_orphan():
    order = {'so': 'A', 'customer': 'C', 'internal_ref': 'X', 'qty_ordered': '2', 'unit_price': '10'}
    deliveries = [{'delivery': f'D{i}', 'so': 'A', 'internal_ref': 'X', 'qty_shipped': '1', 'ship_date': '2027-01-01', 'state': 'done'} for i in (1, 2)]
    invoices = [{'invoice': f'I{i}', 'so': 'A', 'internal_ref': 'X', 'qty_invoiced': '1', 'unit_price': '10', 'invoice_date': '2027-01-01', 'state': 'posted'} for i in (1, 2)]
    invoices.append({'invoice': 'orphan', 'so': 'missing', 'internal_ref': 'X', 'qty_invoiced': '1', 'unit_price': '10', 'invoice_date': '2027-01-01', 'state': 'posted'})
    results, exceptions, candidates = billing.reconcile({'sales_orders': [order], 'deliveries': deliveries, 'invoices': invoices})
    assert results[0]['delivered_qty'] == 2
    assert results[0]['posted_qty'] == 2
    assert results[0]['billing_variance'] == 0
    assert exceptions[0]['record_id'] == 'orphan'
    assert len(candidates) == 4
