# Manager note — product, billing and inventory review

The review identified seven possible duplicate product pairs and several billing differences that warrant follow-up. One pair, P005 and P015, has conflicting units of measure. Confirm specifications and units before combining any product records.

**Potential underbilling — $17,135.** This excludes the draft invoice and uncertain delivery below. For example, S103 shows 200 units delivered and 120 invoiced, a $2,760 difference. S109 shows a $800 price difference. S107 and S110 have no posted invoices, with respective differences of $7,680 and $4,920. S105 accounts for the remaining $975.

**Potential overbilling — $6,330.** S102 has two posted invoices, I302 and I309, for the same quantity and price. Check whether both are valid before making an adjustment.

**Draft invoice — $6,150.** S104 has a draft invoice I304 for the delivered quantity. This amount is excluded from the underbilling subtotal above.

**Uncertain delivery discrepancy — $4,600.** S108 has two matching delivery records, D210 and D211, each for 250 units. The recorded total exceeds the order by 250 units, while 250 units were invoiced. Confirm whether both shipments occurred before treating the difference as billable.

These amounts compare completed deliveries with posted invoices at the order price. They are potential discrepancies, subject to review of supporting documents and terms. The categories above do not overlap.

Inventory counts also need review. L5002 has 150 fewer units counted than recorded, while L5005 has 400 more units counted than recorded. These comparisons come from the supplied inventory counts. No inventory value has been assigned.

## Questions for shipping and accounting

1. Do shipping documents and customer receipt evidence confirm both S108 deliveries, and do they explain the inventory count differences?
2. Are both S102 invoices valid, and is the S104 draft ready to post?
3. Was the lower invoice price on S109 authorized, and are there credits or other terms that explain the outstanding differences?

## Preventive controls in Odoo

1. **Native configuration:** Set applicable products to invoice delivered quantities, and review delivered and invoiced quantities after partial shipments. Existing products need their settings checked individually. [Odoo invoicing policies](https://www.odoo.com/documentation/19.0/applications/sales/sales/invoicing/invoicing_policy.html)
2. **Native configuration:** Enable barcode processing and scan products and quantities against delivery orders before validating shipments. Reconcile physical counts regularly. [Odoo barcode deliveries](https://www.odoo.com/documentation/19.0/applications/inventory_and_mrp/barcode/operations/receipts_deliveries.html)
3. **Custom validation:** Flag matching delivery and invoice details for review, and require review of product records with matching references or conflicting units before consolidation. Matching details are a prompt to investigate, since legitimate repeat transactions can occur.
