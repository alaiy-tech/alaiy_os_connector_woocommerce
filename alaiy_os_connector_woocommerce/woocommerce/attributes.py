# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""
Product Attributes + Attribute Terms: dedicated pull
(/products/attributes, /products/attributes/{id}/terms) -> ERPNext's own
Item Attribute doctype (attribute_name + child table item_attribute_values
of attribute_value rows) -- the real, existing home for "Color: Black/White/
Blue"-shaped data, not a bespoke doctype. Today products.py only reads a
variation's attributes inline to build its item_name; this gives every
attribute + its full term list a standalone master record, independent of
whether any pulled product/variation currently uses it.

Natural key is the attribute's own name (Item Attribute.name), same as
Brand/Item Group elsewhere in this connector -- no wc id custom field
needed since WooCommerce attribute names are already unique per store.
"""

import frappe

from alaiy_os_connector_woocommerce.woocommerce.client import WooCommerceClient


def _upsert_attribute(attribute, terms):
    name = (attribute.get("name") or "").strip()
    if not name:
        return False

    is_new = not frappe.db.exists("Item Attribute", name)
    if is_new:
        doc = frappe.new_doc("Item Attribute")
        doc.attribute_name = name
    else:
        doc = frappe.get_doc("Item Attribute", name)

    existing_values = {row.attribute_value for row in doc.get("item_attribute_values") or []}
    for term in terms:
        value = (term.get("name") or "").strip()
        if value and value not in existing_values:
            doc.append("item_attribute_values", {"attribute_value": value, "abbr": value[:15]})
            existing_values.add(value)

    doc.flags.ignore_permissions = True
    if is_new:
        doc.insert(ignore_permissions=True)
    else:
        doc.save(ignore_permissions=True)
    return is_new


def pull_attributes(log):
    client = WooCommerceClient()
    processed = created = updated = failed = 0
    pages_done = 0

    for page_rows in client.get_all_pages("products/attributes"):
        pages_done += 1
        for attribute in page_rows:
            processed += 1
            try:
                terms = []
                for term_page in client.get_all_pages(f"products/attributes/{attribute['id']}/terms"):
                    terms.extend(term_page)
                if _upsert_attribute(attribute, terms):
                    created += 1
                else:
                    updated += 1
            except Exception:
                failed += 1
                frappe.log_error(
                    title=f"WooCommerce attribute pull failed: {attribute.get('id')}",
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
        log.error_message = f"{failed} attribute(s) failed -- see Error Log."[:2000]
