# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""
Customers: dedicated pull (/customers) -> Customer + Address, complementing
the get-or-create-on-order-import path already in orders.py. That path only
ever sees a customer when they place an order and only captures email +
name; this pulls the full WooCommerce customer list (including anyone who
registered without ordering yet) and their real billing/shipping addresses.

Natural key is wc_customer_id (WooCommerce's own numeric id) -- more robust
than orders.py's email-only match, since email is a MANDATORY WooCommerce
field but this is the authoritative path for it. A Customer already created
by orders.py (identified by wc_customer_email, no wc_customer_id yet) is
adopted here rather than duplicated.

Billing/shipping go on real Address records (Dynamic Link to Customer),
not bespoke fields -- Alaiy OS's own convention (see products.py's Item
Price / Item Group usage).
"""

import frappe

from alaiy_os_connector_woocommerce.woocommerce.client import WooCommerceClient

_ADDRESS_FIELD_MAP = {
    "address_line1": "address_1",
    "address_line2": "address_2",
    "city": "city",
    "state": "state",
    "pincode": "postcode",
}


def _resolve_country(iso_code):
    """Address.country is a Link to the real Country doctype by full name
    (e.g. "United States"), not the ISO alpha-2 code WooCommerce sends --
    setting the raw code would throw a LinkValidationError. Country's own
    `code` field holds that same ISO code, so resolve through it rather
    than hand-maintaining a code->name table."""
    iso_code = (iso_code or "").strip().lower()
    if not iso_code:
        return None
    return frappe.db.get_value("Country", {"code": iso_code}, "name")


def _upsert_address(customer_name, address_type, data):
    """One real Address per (Customer, type) -- get-or-create, never
    duplicated on re-pull."""
    if not (data or {}).get("address_1") and not (data or {}).get("city"):
        return  # nothing real to store

    existing = frappe.db.get_value(
        "Address",
        {
            "address_type": address_type,
            "dynamic_link_type": "Customer",
            "dynamic_link_name": customer_name,
        },
        "name",
    )
    doc = frappe.get_doc("Address", existing) if existing else frappe.new_doc("Address")
    doc.address_title = customer_name
    doc.address_type = address_type
    for erp_field, wc_field in _ADDRESS_FIELD_MAP.items():
        value = data.get(wc_field)
        if value:
            doc.set(erp_field, value)
    # Address.country is mandatory in ERPNext core -- fall back to the
    # site's own default rather than leave it unresolved and fail insert.
    doc.country = (
        _resolve_country(data.get("country"))
        or frappe.db.get_single_value("Global Defaults", "country")
    )
    if not doc.get("address_line1"):
        doc.address_line1 = "Not Provided"
    doc.email_id = data.get("email") or None
    doc.phone = data.get("phone") or None
    doc.flags.ignore_permissions = True
    if not existing:
        doc.append("links", {"link_doctype": "Customer", "link_name": customer_name})
        doc.insert(ignore_permissions=True)
    else:
        doc.save(ignore_permissions=True)


def _upsert_customer(customer, territory):
    wc_id = str(customer["id"])
    email = (customer.get("email") or "").strip()
    first = (customer.get("first_name") or "").strip()
    last = (customer.get("last_name") or "").strip()
    full_name = f"{first} {last}".strip() or email or f"WooCommerce Customer {wc_id}"

    existing = frappe.db.get_value("Customer", {"wc_customer_id": wc_id}, "name")
    if not existing and email:
        # Adopt a Customer orders.py already created by email match, rather
        # than creating a duplicate with no wc_customer_id.
        existing = frappe.db.get_value("Customer", {"wc_customer_email": email}, "name")

    is_new = not existing
    if is_new:
        doc = frappe.new_doc("Customer")
        doc.customer_name = full_name
        doc.customer_type = "Individual"
        doc.customer_group = "All Customer Groups"
        doc.territory = territory
    else:
        doc = frappe.get_doc("Customer", existing)

    doc.wc_customer_id = wc_id
    if email:
        doc.wc_customer_email = email
    doc.flags.ignore_permissions = True
    if is_new:
        doc.insert(ignore_permissions=True)
    else:
        doc.save(ignore_permissions=True)

    _upsert_address(doc.name, "Billing", customer.get("billing") or {})
    _upsert_address(doc.name, "Shipping", customer.get("shipping") or {})
    return is_new


def _resolve_default_territory(settings):
    if getattr(settings, "wc_default_territory", None):
        return settings.wc_default_territory
    if frappe.db.exists("Territory", "All Territories"):
        return "All Territories"
    fallback = frappe.db.get_value("Territory", {}, "name")
    return fallback or "All Territories"


def pull_customers(log):
    settings = frappe.get_single("WooCommerce Connector Settings")
    territory = _resolve_default_territory(settings)
    client = WooCommerceClient()

    processed = created = updated = failed = 0
    pages_done = 0

    for page_rows in client.get_all_pages("customers"):
        pages_done += 1
        for customer in page_rows:
            processed += 1
            try:
                if _upsert_customer(customer, territory):
                    created += 1
                else:
                    updated += 1
            except Exception:
                failed += 1
                frappe.log_error(
                    title=f"WooCommerce customer pull failed: {customer.get('id')}",
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
        log.error_message = f"{failed} customer(s) failed -- see Error Log."[:2000]
