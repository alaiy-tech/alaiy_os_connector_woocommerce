# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""
Product Categories: dedicated pull (/products/categories) -> full Item Group
tree, not just the single first-category flattening products.py already does
inline for the Item.item_group Link. WooCommerce categories are themselves a
real parent/child tree (category.parent is another category's id), so this
mirrors that shape onto Item Group's own tree fields instead of leaving
every category flat under the root.

Two passes, since WooCommerce can return a child category before its parent
within the same page: pass 1 upserts every category flat (parent unset),
pass 2 fixes parent_item_group now that every wc_category_id is resolvable.
"""

import frappe

from alaiy_os_connector_woocommerce.woocommerce.client import WooCommerceClient

_ROOT = "All Item Groups"


def _ensure_root():
    if frappe.db.exists("Item Group", _ROOT):
        return _ROOT
    existing_root = frappe.db.get_value(
        "Item Group", {"is_group": 1, "parent_item_group": ["in", ("", None)]}, "name"
    )
    if existing_root:
        return existing_root
    doc = frappe.new_doc("Item Group")
    doc.item_group_name = _ROOT
    doc.is_group = 1
    doc.flags.ignore_permissions = True
    doc.insert()
    return doc.name


def _upsert_category(category, root):
    name = (category.get("name") or "").strip()
    if not name:
        return None, False
    wc_id = str(category["id"])

    existing = frappe.db.get_value("Item Group", {"wc_category_id": wc_id}, "name")
    if not existing and frappe.db.exists("Item Group", name):
        # A category sharing its name with an already-existing group (e.g.
        # the store's own root) is adopted rather than duplicated.
        existing = name

    is_new = not existing
    if is_new:
        doc = frappe.new_doc("Item Group")
        doc.item_group_name = name
        doc.parent_item_group = root
    else:
        doc = frappe.get_doc("Item Group", existing)

    doc.is_group = 1
    doc.wc_category_id = wc_id
    doc.flags.ignore_permissions = True
    if is_new:
        doc.insert(ignore_permissions=True)
    else:
        doc.save(ignore_permissions=True)
    return doc.name, is_new


def pull_categories(log):
    client = WooCommerceClient()
    root = _ensure_root()

    id_to_group = {}
    id_to_parent = {}
    processed = created = updated = failed = 0
    pages_done = 0

    for page_rows in client.get_all_pages("products/categories"):
        pages_done += 1
        for category in page_rows:
            processed += 1
            try:
                group_name, is_new = _upsert_category(category, root)
                if not group_name:
                    continue
                id_to_group[str(category["id"])] = group_name
                id_to_parent[str(category["id"])] = str(category.get("parent") or "0")
                if is_new:
                    created += 1
                else:
                    updated += 1
            except Exception:
                failed += 1
                frappe.log_error(
                    title=f"WooCommerce category pull failed: {category.get('id')}",
                    message=frappe.get_traceback(),
                )

        log.items_processed = processed
        log.items_created = created
        log.items_updated = updated
        log.items_failed = failed
        log.pages_done = pages_done
        log.save(ignore_permissions=True)
        frappe.db.commit()

    # Pass 2: wire up the tree now that every id in this run has a group.
    for wc_id, group_name in id_to_group.items():
        parent_wc_id = id_to_parent.get(wc_id)
        parent_group = id_to_group.get(parent_wc_id) if parent_wc_id and parent_wc_id != "0" else root
        if not parent_group or parent_group == group_name:
            continue
        current_parent = frappe.db.get_value("Item Group", group_name, "parent_item_group")
        if current_parent != parent_group:
            try:
                frappe.db.set_value("Item Group", group_name, "parent_item_group", parent_group)
            except Exception:
                frappe.log_error(
                    title=f"WooCommerce category pull: failed to re-parent {group_name}",
                    message=frappe.get_traceback(),
                )
    frappe.db.commit()

    if failed:
        log.error_message = f"{failed} categor(y/ies) failed -- see Error Log."[:2000]
