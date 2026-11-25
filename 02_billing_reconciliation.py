"""Reconcile delivered quantities with posted invoices using the current CSV exports."""
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
ORDER_COLUMNS = ['so', 'internal_ref', 'original_refs', 'customer', 'ordered_qty', 'order_price', 'delivered_qty', 'cancelled_qty', 'posted_qty', 'draft_qty', 'expected_value', 'posted_value', 'draft_value', 'quantity_impact', 'price_impact', 'billing_gap', 'review_status', 'flags', 'delivery_ids', 'cancelled_ids', 'posted_ids', 'draft_ids']
ISSUE_COLUMNS = ['review_status', 'so', 'internal_ref', 'issue_type', 'source', 'record_ids', 'source_rows', 'evidence']
ZERO = Decimal(0)


def read_inputs(data_dir):
    tables = {}
    for name, required in SCHEMAS.items():
        path = data_dir / (name + '.csv')
        with path.open(newline='', encoding='utf-8-sig') as handle:
            reader = csv.DictReader(handle)
            if not reader.fieldnames or len(reader.fieldnames) != len(set(reader.fieldnames)) or not set(required).issubset(reader.fieldnames):
                raise ValueError(f'{path}: missing or duplicate required columns')
            tables[name] = []
            for line, row in enumerate(reader, 2):
                row['_line'] = line
                tables[name].append(row)
    return tables


def number(value):
    try:
        result = Decimal((value or '').strip())
        if not result.is_finite() or result < 0:
            raise ValueError
        return result
    except (InvalidOperation, ValueError):
        raise ValueError('expected a finite nonnegative number') from None


def key_for(row):
    return ((row.get('so') or '').strip(), (row.get('internal_ref') or '').strip().upper())


def reconcile(tables):
    issues, orders = [], defaultdict(list)
    transactions = {'deliveries': defaultdict(list), 'invoices': defaultdict(list)}
    invalid = set()

    def issue(key, kind, source, rows, evidence, status='review'):
        id_field = {'sales_orders': 'so', 'deliveries': 'delivery', 'invoices': 'invoice'}[source]
        issues.append({'review_status': status, 'so': key[0], 'internal_ref': key[1], 'issue_type': kind, 'source': source, 'record_ids': '|'.join(str(r.get(id_field) or '').strip() for r in rows), 'source_rows': '|'.join(str(r['_line']) for r in rows), 'evidence': evidence})

    for row in tables['sales_orders']:
        key = key_for(row)
        orders[key].append(row)
    for key, rows in orders.items():
        try:
            if not all(key) or any(not (r.get('customer') or '').strip() for r in rows):
                raise ValueError('missing order identifier, reference, or customer')
            terms = {((r.get('customer') or '').strip(), number(r.get('unit_price'))) for r in rows}
            if len(terms) != 1:
                raise ValueError('conflicting customer or order price')
            for row in rows:
                number(row.get('qty_ordered'))
        except ValueError as exc:
            invalid.add(key)
            issue(key, 'invalid order', 'sales_orders', rows, str(exc))

    for table, id_field, qty_field, states in [('deliveries', 'delivery', 'qty_shipped', {'done', 'cancelled'}), ('invoices', 'invoice', 'qty_invoiced', {'posted', 'draft'})]:
        counts = Counter((r.get(id_field) or '').strip() for r in tables[table])
        for row in tables[table]:
            key = key_for(row)
            record_id = (row.get(id_field) or '').strip()
            errors = []
            if not all(key) or not record_id or counts[record_id] != 1:
                errors.append('missing key or missing/repeated transaction ID')
            if (row.get('state') or '').strip() not in states:
                errors.append('unknown state')
            try:
                number(row.get(qty_field))
                if table == 'invoices':
                    number(row.get('unit_price'))
            except ValueError:
                errors.append('invalid quantity or price')
            if key not in orders:
                reason = 'product mismatch on known order' if any(k[0] == key[0] for k in orders) else 'unknown order'
                issue(key, 'orphan record', table, [row], reason)
            if errors:
                issue(key, 'invalid transaction', table, [row], '; '.join(errors))
                if key in orders:
                    invalid.add(key)
            if key in orders and not errors:
                transactions[table][key].append(row)

    suspect_keys = set()
    for table, state, fields, id_field, date_field in [
        ('deliveries', 'done', ('ship_date', 'qty_shipped'), 'delivery', 'ship_date'),
        ('invoices', 'posted', ('qty_invoiced', 'unit_price'), 'invoice', 'invoice_date')]:
        for key, rows in transactions[table].items():
            groups = defaultdict(list)
            for row in rows:
                if row['state'].strip() == state:
                    signature = tuple(number(row[f]) if f in ('qty_shipped', 'qty_invoiced', 'unit_price') else (row.get(f) or '').strip() for f in fields)
                    groups[signature].append(row)
            for group in groups.values():
                if len(group) > 1:
                    suspect_keys.add(key)
                    evidence = '|'.join(f"{r[id_field]}:{r.get(date_field, '')}" for r in group)
                    issue(key, 'suspected duplicate ' + ('delivery' if table == 'deliveries' else 'invoice'), table, group, evidence)

    results = []
    for key, rows in sorted(orders.items()):
        ds, ins = transactions['deliveries'][key], transactions['invoices'][key]
        done = [r for r in ds if r['state'].strip() == 'done']
        cancelled = [r for r in ds if r['state'].strip() == 'cancelled']
        posted = [r for r in ins if r['state'].strip() == 'posted']
        drafts = [r for r in ins if r['state'].strip() == 'draft']
        def qty(records, field):
            return sum((number(r[field]) for r in records), ZERO)
        def value(records):
            return sum((number(r['qty_invoiced']) * number(r['unit_price']) for r in records), ZERO)
        def ids(records, field):
            return '|'.join(sorted((r[field] or '').strip() for r in records))
        result = {'so': key[0], 'internal_ref': key[1], 'original_refs': '|'.join(sorted({(r.get('internal_ref') or '').strip() for r in rows + ds + ins})), 'customer': '|'.join(sorted({(r.get('customer') or '').strip() for r in rows})), 'delivered_qty': qty(done, 'qty_shipped'), 'cancelled_qty': qty(cancelled, 'qty_shipped'), 'posted_qty': qty(posted, 'qty_invoiced'), 'draft_qty': qty(drafts, 'qty_invoiced'), 'posted_value': value(posted), 'draft_value': value(drafts), 'delivery_ids': ids(done, 'delivery'), 'cancelled_ids': ids(cancelled, 'delivery'), 'posted_ids': ids(posted, 'invoice'), 'draft_ids': ids(drafts, 'invoice')}
        flags = []
        if key not in invalid:
            ordered = qty(rows, 'qty_ordered')
            price = number(rows[0]['unit_price'])
            delivered, invoiced = result['delivered_qty'], result['posted_qty']
            quantity_impact = (invoiced - delivered) * price
            price_impact = sum((number(r['qty_invoiced']) * (number(r['unit_price']) - price) for r in posted), ZERO)
            result.update(ordered_qty=ordered, order_price=price, expected_value=delivered * price, quantity_impact=quantity_impact, price_impact=price_impact, billing_gap=quantity_impact + price_impact)
            checks = []
            if delivered > 0 and not posted:
                checks.append(('missing posted invoice', ins, 'draft invoice exists' if drafts else 'no invoice record', 'invoices'))
            if invoiced != delivered:
                checks.append(('quantity discrepancy', done + posted, f'delivered={delivered}, posted={invoiced}', 'sales_orders'))
            differing = [r for r in posted if number(r['unit_price']) != price]
            if differing:
                checks.append(('price discrepancy', differing, f'order price={price}', 'invoices'))
            if delivered > ordered:
                suspect_keys.add(key)
                checks.append(('overshipment', done, f'ordered={ordered}, delivered={delivered}', 'deliveries'))
            for kind, evidence_rows, evidence, source in checks:
                flags.append(kind)
                if kind == 'quantity discrepancy':
                    issue(key, kind, 'sales_orders', rows, evidence + f"; delivery IDs={result['delivery_ids']}; invoice IDs={result['posted_ids']}", 'ordinary')
                else:
                    issue(key, kind, source, evidence_rows, evidence, 'review' if kind == 'overshipment' else 'ordinary')
        result['review_status'] = 'unquantified' if key in invalid else ('review' if key in suspect_keys else 'ordinary')
        if key in suspect_keys:
            flags.append('suspected duplicate or overshipment')
        if key in invalid:
            flags.append('invalid source data')
        result['flags'] = '|'.join(flags)
        results.append(result)
    statuses = { (r['so'], r['internal_ref']): r['review_status'] for r in results }
    for item in issues:
        if item['review_status'] == 'ordinary':
            item['review_status'] = statuses.get((item['so'], item['internal_ref']), 'review')
    issues.sort(key=lambda r: (r['review_status'], r['so'], r['internal_ref'], r['issue_type'], r['source'], r['record_ids'], r['source_rows']))
    return results, issues


def write_csv(path, rows, columns):
    with path.open('w', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)


def main():
    tables = read_inputs(ROOT / 'data')
    results, issues = reconcile(tables)
    output = ROOT / 'reports'
    output.mkdir(parents=True, exist_ok=True)
    write_csv(output / 'order_reconciliation.csv', results, ORDER_COLUMNS)
    write_csv(output / 'billing_issues.csv', issues, ISSUE_COLUMNS)
    print(f'{len(results)} order keys, {len(issues)} issues')
    for status in ('ordinary', 'review'):
        gaps = [r['billing_gap'] for r in results if r['review_status'] == status]
        print(f'{status}: shortfall {sum((-g for g in gaps if g < 0), ZERO)}, excess {sum((g for g in gaps if g > 0), ZERO)}')
    print(f"unquantified order keys: {sum(r['review_status'] == 'unquantified' for r in results)}")


if __name__ == '__main__':
    main()
