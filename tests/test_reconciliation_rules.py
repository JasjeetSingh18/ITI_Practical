"""Common business rules for both billing report entry points."""
import csv
import runpy
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HEADERS = {
    'sales_orders': 'so,customer,internal_ref,qty_ordered,unit_price,order_date,due_date',
    'deliveries': 'delivery,so,internal_ref,qty_shipped,ship_date,state',
    'invoices': 'invoice,so,internal_ref,qty_invoiced,unit_price,invoice_date,state',
}


@pytest.fixture(params=['02_reconcile_billing.py', '02_billing_reconciliation.py'])
def script(request):
    return runpy.run_path(str(ROOT / request.param))


def read_export(script, directory):
    if 'read_inputs' in script:
        return script['read_inputs'](directory)
    return {name: script['read_table'](directory / f'{name}.csv', fields)
            for name, fields in script['SCHEMAS'].items()}


@pytest.fixture
def tables():
    order = dict(so='A', internal_ref='TUBE', customer='Shop', qty_ordered='12',
                 unit_price='2.50', order_date='2026-01-01', due_date='2026-01-15', _line=2)
    return {'sales_orders': [order], 'deliveries': [], 'invoices': []}


def delivery(identifier, qty, state='done', day='01'):
    return dict(delivery=f'D{identifier}', _line=identifier + 1, so='A', internal_ref='TUBE',
                qty_shipped=qty, state=state, ship_date=f'2026-01-{day}')


def invoice(identifier, qty, price='2.50', state='posted'):
    return dict(invoice=f'I{identifier}', _line=identifier + 1, so='A', internal_ref='TUBE',
                qty_invoiced=qty, unit_price=price, state=state, invoice_date=f'2026-01-0{identifier}')


def test_partial_shipments_and_multiple_invoices(script, tables):
    tables['deliveries'] = [delivery(1, '3'), delivery(2, '5', day='02')]
    tables['invoices'] = [invoice(1, '2'), invoice(2, '4')]
    (line,), *_ = script['reconcile'](tables)
    assert (line['ordered_qty'], line['delivered_qty'], line['posted_qty']) == (12, 8, 6)
    assert (line['expected_value'], line['posted_value']) == (20, 15)


def test_cancelled_delivery_and_draft_invoice(script, tables):
    tables['deliveries'] = [delivery(1, '3'), delivery(2, '7', 'cancelled')]
    tables['invoices'] = [invoice(1, '3', state='draft')]
    (line,), *_ = script['reconcile'](tables)
    assert (line['expected_value'], line['posted_value'], line['draft_value']) == (Decimal('7.50'), 0, Decimal('7.50'))
    assert (line['cancelled_qty'], line['draft_qty'], line['posted_qty']) == (7, 3, 0)
    assert (line['delivery_ids'], line['cancelled_ids'], line['draft_ids']) == ('D1', 'D2', 'I1')


def test_duplicate_candidates_remain_in_totals(script, tables):
    tables['deliveries'] = [delivery(1, '3'), delivery(2, '3.0'), delivery(3, '3', day='02')]
    tables['invoices'] = [invoice(1, '2'), invoice(2, '2.0', '2.5'), invoice(3, '2', state='draft')]
    (line,), issues, *candidate_reports = script['reconcile'](tables)
    assert (line['delivered_qty'], line['posted_qty']) == (9, 4)
    if candidate_reports:
        assert {(r['source'], r['record_id'], r['candidate_ids']) for r in candidate_reports[0]} == {
            ('deliveries', 'D1', 'D2'), ('deliveries', 'D2', 'D1'),
            ('invoices', 'I1', 'I2'), ('invoices', 'I2', 'I1')}
    else:
        groups = {r['issue_type']: set(r['record_ids'].split('|')) for r in issues
                  if r['issue_type'].startswith('suspected duplicate')}
        assert groups == {'suspected duplicate delivery': {'D1', 'D2'}, 'suspected duplicate invoice': {'I1', 'I2'}}
        assert line['review_status'] == 'review'


def test_incorrect_invoice_price(script, tables):
    tables['deliveries'] = [delivery(1, '5')]
    tables['invoices'] = [invoice(1, '2'), invoice(2, '3', '2.35')]
    (line,), issues, *_ = script['reconcile'](tables)
    assert line['expected_value'] == Decimal('12.50')
    assert line['posted_value'] == Decimal('12.05')
    if 'price_impact' in line:
        assert line['price_impact'] == line['billing_gap'] == Decimal('-0.45')
        assert [r['record_ids'] for r in issues if r['issue_type'] == 'price discrepancy'] == ['I2']
    else:
        assert line['price_variance'] == line['billing_variance'] == Decimal('-0.45')
        assert line['price_difference_ids'] == 'I2'


@pytest.mark.parametrize('invalid_table', HEADERS)
def test_missing_required_column(script, tmp_path, invalid_table):
    for name, header in HEADERS.items():
        if name == invalid_table:
            header = header.replace('internal_ref,', '')
        (tmp_path / f'{name}.csv').write_text(header + '\n')
    with pytest.raises(ValueError, match=invalid_table + r'\.csv.*missing'):
        read_export(script, tmp_path)


def test_header_only_inputs(script, tmp_path):
    for name, header in HEADERS.items():
        (tmp_path / f'{name}.csv').write_text(header + '\n')
    assert all(report == [] for report in script['reconcile'](read_export(script, tmp_path)))


def test_balances_from_supplied_csvs(script):
    directory = ROOT / 'data'
    raw = {}
    for name in HEADERS:
        with (directory / f'{name}.csv').open(newline='') as source:
            raw[name] = list(csv.DictReader(source))
    # Independently tally source documents for each order line without any joins.
    def key(row):
        return row['so'], row['internal_ref']

    lines, *_ = script['reconcile'](read_export(script, directory))
    actual = {key(line): line for line in lines}
    assert len(lines) == len(actual) == len(raw['sales_orders'])
    for order in raw['sales_orders']:
        line = actual[key(order)]
        done = [r for r in raw['deliveries'] if key(r) == key(order) and r['state'] == 'done']
        posted = [r for r in raw['invoices'] if key(r) == key(order) and r['state'] == 'posted']
        shipped = sum(Decimal(r['qty_shipped']) for r in done)
        billed = sum(Decimal(r['qty_invoiced']) for r in posted)
        due = shipped * Decimal(order['unit_price'])
        charged = sum(Decimal(r['qty_invoiced']) * Decimal(r['unit_price']) for r in posted)
        assert (line['delivered_qty'], line['posted_qty']) == (shipped, billed)
        assert (line['expected_value'], line['posted_value']) == (due, charged)
        assert line.get('billing_gap', line.get('billing_variance')) == charged - due
