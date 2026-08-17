# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""
Order IMPORT: pull WooCommerce's orders into Alaiy OS as Sales Orders.

Every WooCommerce order field maps onto a real, existing ERPNext field --
the only bespoke field is wc_order_id (identity, no ERPNext equivalent).
Sales Order.sales_channel is alaiy_os's own generic "which channel did this
order come from" field, so it's set to "WooCommerce" rather than inventing a
connector-specific one.

trash/failed orders are skipped entirely -- they were never real sales.
Every other status is imported and submitted; WooCommerce's own status
(pending/processing/on-hold/completed/cancelled/refunded) isn't stored
separately since nothing here reports on it yet.

Line items are matched to an Item by WooCommerce's own product_id/
variation_id (set during product import via wc_product_id/wc_variation_id),
falling back to the order line's own SKU if a matching Item was never
pulled -- an order can reference a product that predates this connector's
first product import.
"""

import frappe
from frappe.utils import flt, getdate

from alaiy_os_connector_woocommerce.woocommerce.client import WooCommerceClient

_SKIP_STATUSES = {"trash", "failed"}


def _resolve_default_territory(settings):
    """Same self-heal pattern as every other connector's order import here:
    a configured territory, else the conventional root name, else any
    existing Territory, else create the root ourselves -- a missing master
    record shouldn't hard-fail an order import."""
    if getattr(settings, "wc_default_territory", None):
        return settings.wc_default_territory
    if frappe.db.exists("Territory", "All Territories"):
        return "All Territories"
    fallback = frappe.db.get_value("Territory", {}, "name")
    if fallback:
        return fallback
    doc = frappe.new_doc("Territory")
    doc.territory_name = "All Territories"
    doc.is_group = 1
    doc.flags.ignore_permissions = True
    doc.insert()
    return doc.name


def _get_or_create_customer(billing, wc_order_id, territory):
    email = (billing.get("email") or "").strip()
    if email:
        existing = frappe.db.get_value("Customer", {"wc_customer_email": email}, "name")
        if existing:
            return existing

    first = (billing.get("first_name") or "").strip()
    last = (billing.get("last_name") or "").strip()
    full_name = f"{first} {last}".strip() or email or f"WooCommerce Guest {wc_order_id}"

    if frappe.db.exists("Customer", full_name):
        return full_name

    c = frappe.new_doc("Customer")
    c.customer_name = full_name
    c.customer_type = "Individual"
    c.customer_group = "All Customer Groups"
    c.territory = territory
    if email:
        c.wc_customer_email = email
    c.flags.ignore_permissions = True
    c.insert()
    return c.name


def _resolve_item_code(line_item):
    product_id = line_item.get("product_id")
    variation_id = line_item.get("variation_id")
    if variation_id:
        code = frappe.db.get_value("Item", {"wc_variation_id": str(variation_id)}, "item_code")
        if code:
            return code
    if product_id:
        code = frappe.db.get_value(
            "Item", {"wc_product_id": str(product_id), "wc_variation_id": ""}, "item_code"
        )
        if code:
            return code
    sku = (line_item.get("sku") or "").strip()
    if sku and frappe.db.exists("Item", sku):
        return sku
    return None


def _upsert_order(order, warehouse, company, price_list, territory):
    wc_order_id = str(order["id"])
    existing = frappe.db.get_value("Sales Order", {"wc_order_id": wc_order_id, "docstatus": ["!=", 2]}, "name")
    if existing:
        return False

    billing = order.get("billing") or {}
    customer = _get_or_create_customer(billing, wc_order_id, territory)
    order_date = getdate(order["date_created"]) if order.get("date_created") else frappe.utils.today()

    line_items = []
    for li in order.get("line_items") or []:
        item_code = _resolve_item_code(li)
        if not item_code:
            frappe.log_error(
                title=f"WooCommerce order {wc_order_id}: unmatched line item",
                message=str(li),
            )
            continue
        qty = flt(li.get("quantity") or 0)
        if qty <= 0:
            continue
        total = flt(li.get("total") or 0)
        line_items.append({
            "item_code": item_code,
            "qty": qty,
            "rate": total / qty if qty else 0,
            "warehouse": warehouse,
            "delivery_date": order_date,
        })

    if not line_items:
        frappe.log_error(
            title=f"WooCommerce order {wc_order_id}: no mappable line items",
            message=str(order.get("line_items")),
        )
        return False

    so = frappe.new_doc("Sales Order")
    so.customer = customer
    so.company = company
    so.transaction_date = order_date
    so.delivery_date = order_date
    so.selling_price_list = price_list
    so.set_warehouse = warehouse
    so.sales_channel = "WooCommerce"
    so.wc_order_id = wc_order_id
    for li in line_items:
        so.append("items", li)
    so.flags.ignore_permissions = True
    so.insert()
    so.submit()
    _pull_order_notes(so.name, wc_order_id)
    return True


def _pull_order_notes(so_name, wc_order_id):
    """Order Notes have no bulk/global endpoint -- only per-order
    (/orders/<id>/notes) -- so this only runs once, on first import of the
    order, rather than re-fetching notes for every already-pulled order on
    every run. A note added to WooCommerce after that point (e.g. a later
    refund note) won't retroactively appear -- a real, accepted gap, not a
    bug: re-fetching notes for the whole order history on every pull would
    turn one API call per page into one per order, every run."""
    from alaiy_os_connector_woocommerce.woocommerce.client import WooCommerceClient

    try:
        client = WooCommerceClient()
        for page in client.get_all_pages(f"orders/{wc_order_id}/notes"):
            for note in page:
                text = (note.get("note") or "").strip()
                if not text:
                    continue
                comment = frappe.new_doc("Comment")
                comment.comment_type = "Comment"
                comment.reference_doctype = "Sales Order"
                comment.reference_name = so_name
                comment.content = text
                comment.comment_email = note.get("author") or "WooCommerce"
                comment.flags.ignore_permissions = True
                comment.insert(ignore_permissions=True)
    except Exception:
        frappe.log_error(
            title=f"WooCommerce order pull: failed to fetch notes for order {wc_order_id}",
            message=frappe.get_traceback(),
        )


def pull_orders(log):
    """Pages through /orders (skipping trash/failed), matching each
    order's status is left to WooCommerce -- everything importable is
    imported and submitted as a real Sales Order."""
    settings = frappe.get_single("WooCommerce Connector Settings")
    warehouse = settings.wc_default_warehouse
    company = settings.wc_company
    price_list = settings.wc_price_list or "Standard Selling"
    territory = _resolve_default_territory(settings)
    client = WooCommerceClient()

    processed = created = updated = failed = 0
    pages_done = 0

    for page_rows in client.get_all_pages("orders", params={"status": "any"}):
        pages_done += 1
        for order in page_rows:
            if order.get("status") in _SKIP_STATUSES:
                continue
            processed += 1
            try:
                is_new = _upsert_order(order, warehouse, company, price_list, territory)
                if is_new:
                    created += 1
                else:
                    updated += 1
            except Exception:
                failed += 1
                frappe.log_error(
                    title=f"WooCommerce order pull failed: {order.get('id')}",
                    message=frappe.get_traceback(),
                )

        log.items_processed = processed
        log.items_created = created
        log.items_updated = updated
        log.items_failed = failed
        log.pages_done = pages_done
        log.save(ignore_permissions=True)
        frappe.db.commit()

    if failed:
        log.error_message = f"{failed} order(s) failed -- see Error Log."[:2000]
