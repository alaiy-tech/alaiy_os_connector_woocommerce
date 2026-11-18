# Orders — WooCommerce → Sales Order

`woocommerce/orders.py::pull_orders` pages through `/orders`
(`status=any`, skipping `trash`/`failed` — they were never real sales),
matches or creates a **Customer** by billing email, resolves each line item
to an existing **Item**, and creates + submits a **Sales Order**.

**This code is real and correct, but nothing on `main` currently calls
it.** `run_order_pull_sync` exists in `sync.py` and is fully wired to the
Sync Log lifecycle, but the scheduler (`sync_jobs.py`) only ever enqueues
`run_pull_sync` (products) and `run_push_sync` — there is no order
`sync_type`, no interval setting, and no button on the connector card that
invokes order pull. It only runs if triggered by hand, e.g.
`bench execute alaiy_os_connector_woocommerce.woocommerce.sync.run_order_pull_sync`.

## Field mapping

Every WooCommerce order field maps onto a real, existing ERPNext field —
the only bespoke field is `wc_order_id` (identity, no ERPNext equivalent).
`Sales Order.sales_channel` is Alaiy OS's own generic "which channel did
this order come from" field, set to `"WooCommerce"`.

WooCommerce's own order status
(pending/processing/on-hold/completed/cancelled/refunded) is **not stored**
anywhere on the Sales Order — nothing here reports on it yet. Every
non-trash/failed status is imported and submitted the same way.

## Customer matching

Matched by billing email against `Customer.wc_customer_email` first. No
match → a new Customer is created, named from billing first+last name,
falling back to the email, falling back to `WooCommerce Guest <order_id>`
if both are blank.

## Line-item matching

Resolved in this order:
1. `variation_id` → `Item.wc_variation_id`
2. `product_id` → `Item.wc_product_id` (only where `wc_variation_id` is
   blank, i.e. a simple product's own Item row)
3. the order line's own `sku`, if an Item with that exact code exists

A line that matches nothing is skipped and logged (`unmatched line item`)
— an order can reference a product that predates this connector's first
product import. An order where every line fails to match creates no Sales
Order at all (`no mappable line items`).

## What's not built

- No refund/return pull — WooCommerce orders don't get an Alaiy OS invoice
  at all yet, so there's nothing to credit back against.
- No order-status sync in either direction.
- No push of anything back to WooCommerce (see
  [architecture.md](architecture.md) — `run_push_sync` is an empty stub).
