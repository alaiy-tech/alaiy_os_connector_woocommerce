# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""
Webhook handlers -- same per-row upsert functions run_pull_sync/
run_order_pull_sync already use, just called for one row instead of a full
page. Real-time pull only; nothing here is pushed back out to WooCommerce.
"""

import frappe

from alaiy_os_connector_woocommerce.woocommerce.client import WooCommerceClient
from alaiy_os_connector_woocommerce.woocommerce.orders import _upsert_order, _resolve_default_territory
from alaiy_os_connector_woocommerce.woocommerce.products import _upsert_simple_product, _upsert_variation


def handle_order_webhook(topic, payload):
    try:
        settings = frappe.get_single("WooCommerce Connector Settings")
        if topic == "order.deleted":
            _cancel_order(payload)
            return
        _upsert_order(
            payload,
            warehouse=settings.wc_default_warehouse,
            company=settings.wc_company,
            price_list=settings.wc_price_list or "Standard Selling",
            territory=_resolve_default_territory(settings),
        )
    except Exception:
        frappe.log_error(
            title=f"WooCommerce order webhook {topic} failed: {payload.get('id')}",
            message=frappe.get_traceback(),
        )


def _cancel_order(payload):
    """order.deleted means removed from WooCommerce, not necessarily a real
    cancellation -- same "never hard-delete, always docstatus-cancel"
    convention as every other connector here."""
    wc_order_id = str(payload.get("id"))
    name = frappe.db.get_value(
        "Sales Order", {"wc_order_id": wc_order_id, "docstatus": 1}, "name"
    )
    if not name:
        return
    so = frappe.get_doc("Sales Order", name)
    so.flags.ignore_permissions = True
    so.cancel()


def handle_product_webhook(topic, payload):
    try:
        settings = frappe.get_single("WooCommerce Connector Settings")
        price_list = settings.wc_price_list or "Standard Selling"
        warehouse = settings.wc_default_warehouse
        company = settings.wc_company

        if topic == "product.deleted":
            _disable_product(payload)
            return

        if payload.get("type") == "variable":
            client = WooCommerceClient()
            for var_page in client.get_all_pages(f"products/{payload['id']}/variations"):
                for variation in var_page:
                    _upsert_variation(payload, variation, price_list, warehouse, company)
        else:
            _upsert_simple_product(payload, price_list, warehouse, company)
    except Exception:
        frappe.log_error(
            title=f"WooCommerce product webhook {topic} failed: {payload.get('id')}",
            message=frappe.get_traceback(),
        )


def _disable_product(payload):
    """product.deleted -- disable every Item tied to this WooCommerce
    product (the parent and any variations), never hard-delete an Item
    with real stock/order history against it."""
    wc_product_id = str(payload.get("id"))
    for item_code in frappe.db.get_all(
        "Item", {"wc_product_id": wc_product_id}, pluck="item_code"
    ):
        frappe.db.set_value("Item", item_code, "disabled", 1)
