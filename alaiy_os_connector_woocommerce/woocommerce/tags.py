# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""
Product Tags: dedicated pull (/products/tags) -> Frappe's own generic Tag
master list (the same tagging system products.py already attaches tags to
Items with via add_tag). This just guarantees every WooCommerce tag exists
as a real Tag up front, rather than only the ones some product happened to
reference during a product pull.
"""

import frappe

from alaiy_os_connector_woocommerce.woocommerce.client import WooCommerceClient


def _ensure_tag(name):
    name = (name or "").strip()
    if not name or frappe.db.exists("Tag", name):
        return False
    frappe.get_doc({"doctype": "Tag", "name": name}).insert(ignore_permissions=True)
    return True


def pull_tags(log):
    client = WooCommerceClient()
    processed = created = updated = failed = 0
    pages_done = 0

    for page_rows in client.get_all_pages("products/tags"):
        pages_done += 1
        for tag in page_rows:
            processed += 1
            try:
                if _ensure_tag(tag.get("name")):
                    created += 1
                else:
                    updated += 1
            except Exception:
                failed += 1
                frappe.log_error(
                    title=f"WooCommerce tag pull failed: {tag.get('id')}",
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
        log.error_message = f"{failed} tag(s) failed -- see Error Log."[:2000]
