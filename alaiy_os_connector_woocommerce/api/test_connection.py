# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""
Reachability check for the saved credentials. Wired into the registry via
connector_meta["test_method"] and called by the "Test Connection" button.
Always returns {"success": bool, "message": str} — never raises to the caller.
"""

import frappe

from alaiy_os_connector_woocommerce.woocommerce.client import WooCommerceAPIError, WooCommerceClient


@frappe.whitelist()
def test_connection():
    settings = frappe.get_single("WooCommerce Connector Settings")
    if not settings.wc_store_url:
        return {"success": False, "message": "Store URL is not set."}
    if not settings.wc_consumer_key:
        return {"success": False, "message": "Consumer Key is not set."}
    if not settings.wc_consumer_secret:
        return {"success": False, "message": "Consumer Secret is not set."}

    try:
        client = WooCommerceClient()
    except RuntimeError as e:
        return {"success": False, "message": str(e)}

    # Cheapest real read that both proves auth works and that this is
    # actually a WooCommerce store, not just any WordPress site.
    try:
        client.get("products", params={"per_page": 1})
        return {"success": True, "message": "Connected successfully."}
    except WooCommerceAPIError as e:
        if e.status_code == 401:
            return {"success": False, "message": "Authentication failed — check your Consumer Key/Secret."}
        if e.status_code == 404:
            return {"success": False, "message": "WooCommerce REST API not found at this Store URL — check it's correct and WooCommerce is active."}
        return {"success": False, "message": str(e)}
    except Exception as e:
        return {"success": False, "message": str(e)[:200]}
