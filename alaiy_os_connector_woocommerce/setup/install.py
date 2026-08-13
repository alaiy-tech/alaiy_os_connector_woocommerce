# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""
Install / migrate plumbing shared by every Alaiy OS connector:

  after_install            -> one-time cleanup on `bench install-app`
  sync_connector_registry  -> (re)register in OS Connector Registry AND
                               provision custom fields, every bench migrate

setup_custom_fields runs unconditionally on every migrate (same pattern as
alaiy_os_connector_shopify/alaiy_os_connector_unicommerce), not gated behind
a first-enable step. Confirmed real bug class in other Alaiy OS connectors
that gated it: any page assuming these fields exist (e.g. a dashboard
reading a synced field) crashes with a raw OperationalError on a site where
the connector is installed but never enabled -- hit independently on
multiple real sites, not a one-off.
"""

import json

import frappe


def after_install():
    """
    Called once after `bench install-app`. Clear any stale encrypted Password
    field that may have been written under a different site encryption key
    (e.g. from a prior failed install), which otherwise surfaces as a
    'Failed to decrypt key' error on first load.
    """
    # Must run first: install-app syncs the doctype but never calls
    # after_migrate, so the settings doctype is still issingle=0 at this
    # point -- set_single_value below would write to tabSingles for a
    # doctype Frappe doesn't yet treat as a Single (confirmed real bug in
    # alaiy_os_connector_unicommerce's own after_install before it fixed
    # the same ordering).
    _fix_settings_as_single()

    frappe.db.set_single_value(
        "WooCommerce Connector Settings", "wc_consumer_secret", ""
    )
    frappe.db.commit()


def sync_connector_registry():
    """
    Register or update this connector's row in alaiy_os's OS Connector Registry,
    and provision custom fields. Called from hooks.py -> after_migrate on every
    bench migrate. Idempotent.
    """
    _fix_settings_as_single()
    setup_custom_fields()

    if not frappe.db.exists("DocType", "OS Connector Registry"):
        return

    from alaiy_os_connector_woocommerce.connector_meta import connector_meta

    connector_id = connector_meta["connector_id"]

    if frappe.db.exists("OS Connector Registry", connector_id):
        doc = frappe.get_doc("OS Connector Registry", connector_id)
    else:
        doc = frappe.new_doc("OS Connector Registry")

    # Fields owned by the running system, never overwritten from static meta.
    RUNTIME_FIELDS = {"connection_status", "last_tested_at"}

    if doc.is_new():
        for key, val in connector_meta.items():
            if hasattr(doc, key):
                doc.set(key, val)
        doc.insert(ignore_permissions=True)
    else:
        for key, val in connector_meta.items():
            if key not in RUNTIME_FIELDS and hasattr(doc, key):
                doc.set(key, val)
        doc.save(ignore_permissions=True)

    frappe.db.commit()
    _update_alaiy_os_sidebar()


def _update_alaiy_os_sidebar():
    """
    Re-run alaiy_os's workspace/sidebar provisioning so this connector's Logs
    link and Connectors entry (settings button + card) appear right after it
    registers, instead of waiting for the next full bench migrate.
    """
    try:
        from alaiy_os.setup.install import (
            create_or_update_workspace_sidebar,
            create_or_update_os_settings_workspace,
            create_or_update_os_settings_workspace_sidebar,
        )
        create_or_update_workspace_sidebar()
        create_or_update_os_settings_workspace()
        create_or_update_os_settings_workspace_sidebar()
        frappe.db.commit()
    except Exception:
        frappe.log_error(
            title="WooCommerce connector: sidebar update failed",
            message=frappe.get_traceback(),
        )


def _fix_settings_as_single():
    """
    Force issingle=1 on the settings doctype. Frappe does not auto-convert an
    existing DocType from table-based to Single via bench migrate, so patch it
    directly every deploy.
    """
    frappe.db.sql(
        "UPDATE `tabDocType` SET issingle=1 "
        "WHERE name='WooCommerce Connector Settings' AND issingle=0"
    )
    frappe.db.commit()


def setup_custom_fields():
    """
    Add this connector's custom fields to ERPNext doctypes. Idempotent — safe
    to call on every migrate. Uses Frappe's own create_custom_fields(...,
    update=True) rather than a hand-rolled upsert -- matches
    alaiy_os_connector_shopify's current approach (its own install.py notes
    it moved off a hand-rolled upsert to this, since update=True already
    re-syncs properties like description/read_only on existing fields for
    free, which a hand-rolled version has to reimplement itself).
    """
    item_fields = [
        {
            "fieldname": "wc_product_id",
            "label": "WooCommerce Product ID",
            "fieldtype": "Data",
            "search_index": 1,
            "insert_after": "item_code",
            "description": "The WooCommerce product's own numeric ID -- not the SKU.",
        },
        {
            "fieldname": "sync_to_woocommerce",
            "label": "Sync to WooCommerce",
            "fieldtype": "Check",
            "default": "0",
            "in_list_view": 1,
            "insert_after": "disabled",
            "description": "Include this Item in WooCommerce syncs.",
        },
    ]

    custom_fields = {"Item": item_fields}
    for fields in custom_fields.values():
        for f in fields:
            f.setdefault("module", "Alaiy Os Connector WooCommerce")

    from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
    create_custom_fields(custom_fields, update=True)
    frappe.db.commit()


# ---------------------------------------------------------------------------
# Reusable migration utilities (not called by default — here because every
# connector eventually needs them; wire them into sync_connector_registry as
# your schema evolves).
# ---------------------------------------------------------------------------
def _backfill_singles_defaults(doctype, fieldnames):
    """
    A field's `default` only applies to NEW documents. For a Single doctype's
    one pre-existing row, adding a field with a default later does not populate
    it — it reads back empty forever unless someone opens and saves the form.
    Backfill it here, once, idempotently.

    Checks row EXISTENCE in tabSingles rather than the value, because for a
    Check field "never set" and "explicitly 0" both read back as 0.
    """
    meta = frappe.get_meta(doctype)
    for fieldname in fieldnames:
        already_set = frappe.db.sql(
            "SELECT 1 FROM `tabSingles` WHERE doctype=%s AND field=%s LIMIT 1",
            (doctype, fieldname),
        )
        if already_set:
            continue
        field = meta.get_field(fieldname)
        if not field or field.default in (None, ""):
            continue
        frappe.db.set_single_value(doctype, fieldname, field.default)
    frappe.db.commit()


def _drop_orphaned_singles_value(doctype, fieldname):
    """
    Removing a field from a DocType's JSON doesn't clean up its old stored
    value on a site that already had one — it becomes an orphaned, invisible
    row in tabSingles. Delete it explicitly.
    """
    frappe.db.sql(
        "DELETE FROM `tabSingles` WHERE doctype=%s AND field=%s",
        (doctype, fieldname),
    )
    frappe.db.commit()


def _ensure_list_view_column(doctype, fieldname, label):
    """
    Once a doctype's `List View Settings` row exists (created the first time
    anyone customizes columns), it overrides the "show every in_list_view
    field automatically" default — a newly added in_list_view field then never
    appears until re-added by hand. Append our field to the customized set.
    """
    if not frappe.db.exists("List View Settings", doctype):
        return  # no customization yet — in_list_view alone is enough
    settings = frappe.get_doc("List View Settings", doctype)
    fields = json.loads(settings.fields or "[]")
    if any(f.get("fieldname") == fieldname for f in fields):
        return
    fields.append({"fieldname": fieldname, "label": label})
    settings.fields = json.dumps(fields)
    settings.save(ignore_permissions=True)
    frappe.db.commit()
