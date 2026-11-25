"""Reconcile completed deliveries and posted invoices to sales order lines."""
import argparse
import csv
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SCHEMAS = {
    'sales_orders': ('so', 'customer', 'internal_ref', 'qty_ordered', 'unit_price', 'order_date', 'due_date'),
    'deliveries': ('delivery', 'so', 'internal_ref', 'qty_shipped', 'ship_date', 'state'),
    'invoices': ('invoice', 'so', 'internal_ref', 'qty_invoiced', 'unit_price', 'invoice_date', 'state'),
}


def read_table(path, columns):
    with path.open(newline='', encoding='utf-8-sig') as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or not set(columns).issubset(reader.fieldnames):
            raise ValueError(f'{path}: missing required columns')
        return list(reader)


def write_table(path, rows, columns):
    with path.open('w', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)


def number(value):
    try:
        result = Decimal(value)
        if not result.is_finite() or result < 0:
            raise ValueError('must be finite and nonnegative')
        return result
    except (InvalidOperation, TypeError):
        raise ValueError('invalid number') from None


def reconcile(data):
    exceptions, candidates = [], []
    orders = defaultdict(list)
    transactions = {'deliveries': defaultdict(list), 'invoices': defaultdict(list)}
    invalid_keys = set()
    for row in data['sales_orders']:
        orders[(row['so'], row['internal_ref'])].append(row)
    id_counts = {table: Counter(row[id_field] for row in data[table]) for table, id_field in [('deliveries', 'delivery'), ('invoices', 'invoice')]}
    def exception(table, row, reason):
        exceptions.append({'source': table, 'record_id': row.get('delivery', row.get('invoice', row.get('so', ''))), 'so': row['so'], 'internal_ref': row['internal_ref'], 'reason': reason, 'state': row.get('state', ''), 'source_record': repr(row)})
    for key, rows in orders.items():
        if not all(key) or len(rows) != 1:
            invalid_keys.add(key)
            for row in rows:
                exception('sales_orders', row, 'missing or ambiguous order key')
            continue
        try:
            number(rows[0]['qty_ordered']); number(rows[0]['unit_price'])
        except ValueError:
            invalid_keys.add(key)
            exception('sales_orders', rows[0], 'invalid order quantity or price')
    for table, id_field, qty_field, allowed in [('deliveries', 'delivery', 'qty_shipped', {'done', 'cancelled'}), ('invoices', 'invoice', 'qty_invoiced', {'posted', 'draft'})]:
        for row in data[table]:
            key = (row['so'], row['internal_ref'])
            reason = ''
            if key not in orders:
                reason = 'unmatched product on known order' if any(k[0] == key[0] for k in orders) else 'unknown order'
            elif key in invalid_keys:
                reason = 'ambiguous or invalid order'
            elif not row[id_field] or id_counts[table][row[id_field]] != 1:
                reason = 'missing or repeated transaction ID'
            elif row['state'] not in allowed:
                reason = 'unknown state'
            else:
                try:
                    number(row[qty_field])
                    if table == 'invoices':
                        number(row['unit_price'])
                except ValueError:
                    reason = 'invalid quantity or price'
            if reason:
                exception(table, row, reason)
                if key in orders:
                    invalid_keys.add(key)
            else:
                transactions[table][key].append(row)
    # Candidate groups preserve every source row in financial totals.
    for table, fields, state, id_field in [('deliveries', ('so', 'internal_ref', 'ship_date', 'qty_shipped'), 'done', 'delivery'), ('invoices', ('so', 'internal_ref', 'qty_invoiced', 'unit_price'), 'posted', 'invoice')]:
        groups = defaultdict(list)
        for rows in transactions[table].values():
            for row in rows:
                if row['state'] == state:
                    signature = tuple(number(row[f]) if f in ('qty_shipped', 'qty_invoiced', 'unit_price')
                                      else row[f] for f in fields)
                    groups[signature].append(row)
        for group in groups.values():
            if len(group) > 1:
                for row in group:
                    candidates.append({'source': table, 'so': row['so'], 'internal_ref': row['internal_ref'], 'record_id': row[id_field], 'candidate_ids': '|'.join(r[id_field] for r in group if r is not row), 'date': row.get('ship_date', row.get('invoice_date')), 'reason': 'matching transaction attributes; verify independently'})
    results = []
    for key, rows in orders.items():
        if key in invalid_keys:
            continue
        order = rows[0]
        ds = transactions['deliveries'][key]
        ins = transactions['invoices'][key]
        done = [r for r in ds if r['state'] == 'done']
        cancelled = [r for r in ds if r['state'] == 'cancelled']
        posted = [r for r in ins if r['state'] == 'posted']
        drafts = [r for r in ins if r['state'] == 'draft']
        qty = lambda records, field: sum((number(r[field]) for r in records), Decimal(0))
        value = lambda records: sum((number(r['qty_invoiced']) * number(r['unit_price']) for r in records), Decimal(0))
        ordered, price = number(order['qty_ordered']), number(order['unit_price'])
        delivered, invoiced = qty(done, 'qty_shipped'), qty(posted, 'qty_invoiced')
        actual = value(posted)
        variance = actual - delivered * price
        flags = []
        if delivered and not ins: flags.append('missing invoice')
        if delivered and drafts and not posted: flags.append('draft only')
        if posted and invoiced < delivered: flags.append('quantity underbilling')
        if invoiced > delivered: flags.append('quantity overbilling')
        if delivered > ordered: flags.append('overshipment')
        if any(number(r['unit_price']) != price for r in posted): flags.append('price difference')
        results.append({'so': key[0], 'internal_ref': key[1], 'customer': order['customer'], 'ordered_qty': ordered, 'order_price': price, 'delivered_qty': delivered, 'cancelled_qty': qty(cancelled, 'qty_shipped'), 'posted_qty': invoiced, 'draft_qty': qty(drafts, 'qty_invoiced'), 'expected_value': delivered * price, 'posted_value': actual, 'draft_value': value(drafts), 'quantity_variance': (invoiced - delivered) * price, 'price_variance': sum((number(r['qty_invoiced']) * (number(r['unit_price']) - price) for r in posted), Decimal(0)), 'billing_variance': variance, 'shortfall': max(-variance, Decimal(0)), 'excess': max(variance, Decimal(0)), 'flags': '|'.join(flags), 'delivery_ids': '|'.join(r['delivery'] for r in done), 'cancelled_ids': '|'.join(r['delivery'] for r in cancelled), 'posted_ids': '|'.join(r['invoice'] for r in posted), 'draft_ids': '|'.join(r['invoice'] for r in drafts), 'price_difference_ids': '|'.join(r['invoice'] for r in posted if number(r['unit_price']) != price)})
    return results, exceptions, candidates


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, default=ROOT / 'data')
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'reports')
    args = parser.parse_args()
    data = {name: read_table(args.data_dir / f'{name}.csv', fields) for name, fields in SCHEMAS.items()}
    results, exceptions, candidates = reconcile(data)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    columns = ['so','internal_ref','customer','ordered_qty','order_price','delivered_qty','cancelled_qty','posted_qty','draft_qty','expected_value','posted_value','draft_value','quantity_variance','price_variance','billing_variance','shortfall','excess','flags','delivery_ids','cancelled_ids','posted_ids','draft_ids','price_difference_ids']
    write_table(args.output_dir / 'billing_reconciliation.csv', results, columns)
    write_table(args.output_dir / 'billing_exceptions.csv', exceptions, ['source','record_id','so','internal_ref','reason','state','source_record'])
    write_table(args.output_dir / 'billing_duplicate_candidates.csv', candidates, ['source','so','internal_ref','record_id','candidate_ids','date','reason'])
    print(f"Reconciled {len(results)} lines, {len(exceptions)} exceptions, {len(candidates)} duplicate candidate records")
    print(f"Shortfall: {sum((r['shortfall'] for r in results), Decimal(0))}; excess: {sum((r['excess'] for r in results), Decimal(0))}")


if __name__ == '__main__':
    main()
