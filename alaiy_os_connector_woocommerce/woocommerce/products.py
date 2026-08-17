# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""
Product IMPORT: pull WooCommerce's products into Alaiy OS as Items.

Get-or-create Item on item_code = SKU, isolated try/except per row so one bad
record doesn't roll back the whole run, incremental log counters. Every
WooCommerce field pulled maps onto a real, existing ERPNext field or
doctype -- nothing bespoke invented for what already has a proper home:
  price               -> Item Price, "Standard Selling" (rate = WooCommerce's
                          `price`, the current effective price -- already
                          accounts for an active sale, so it's what a
                          customer actually pays, not regular_price)
  image               -> Item.image (WooCommerce's first product image)
  category (1st only) -> Item.item_group (a Link field -- WooCommerce's own
                          multi-category model doesn't fit a single Link, so
                          only the first category is used; the rest are
                          still available on the source product if needed
                          later)
  tags                -> Frappe's own generic tagging system (add_tag),
                          not a bespoke field
  brand               -> Item.brand (Link to Brand, created on first use)
  weight              -> Item.weight_per_unit
  virtual/downloadable -> Item.is_stock_item = 0 (nothing to stock)
  stock_quantity      -> a real Stock Reconciliation against the connector's
                          configured warehouse, only when WooCommerce itself
                          has manage_stock on -- an audited stock movement,
                          not a raw field write
  identity            -> wc_product_id / wc_variation_id custom fields (no
                          ERPNext equivalent exists for these)

Deliberately NOT mapped -- no real ERPNext equivalent exists and inventing
one isn't warranted for a first pass: dimensions (length/width/height),
tax_status/tax_class, meta_data, menu_order, featured, catalog_visibility,
grouped_products, external_url/button_text (non-physical product types).

A `variable` product has no sellable SKU of its own -- WooCommerce's own docs
list `sku`/`price` as blank on the parent (see the "Ship Your Idea" example
in products.mdx). Its variations are the real SKUs, fetched separately and
each becomes its own flat Item rather than building out ERPNext's own Item
Attribute/Template variant machinery.
"""

import frappe
from frappe.utils import flt

from alaiy_os_connector_woocommerce.woocommerce.client import WooCommerceClient

_DEFAULT_ITEM_GROUP = "All Item Groups"
_DEFAULT_STOCK_UOM = "Nos"


def _stock_uom():
    return frappe.db.get_single_value("Stock Settings", "stock_uom") or _DEFAULT_STOCK_UOM


def _ensure_root_item_group():
    """The standard ERPNext fixture creates "All Item Groups" as the one
    root (parent_item_group blank, is_group=1) automatically -- but a site
    where the Selling/Stock module was never fully onboarded can be missing
    it entirely (confirmed live: a real site had a single leaf Item Group
    and no root at all, so creating a child under "All Item Groups"
    without checking first threw a real LinkValidationError). Create the
    root ourselves if one doesn't already exist, rather than assuming it."""
    if frappe.db.exists("Item Group", _DEFAULT_ITEM_GROUP):
        return _DEFAULT_ITEM_GROUP
    existing_root = frappe.db.get_value(
        "Item Group", {"is_group": 1, "parent_item_group": ["in", ("", None)]}, "name"
    )
    if existing_root:
        return existing_root
    doc = frappe.new_doc("Item Group")
    doc.item_group_name = _DEFAULT_ITEM_GROUP
    doc.is_group = 1
    doc.flags.ignore_permissions = True
    doc.insert()
    return doc.name


def _ensure_item_group(name):
    """Item.item_group is a mandatory Link, not free text -- a WooCommerce
    category name fails outright if no Item Group of that exact name exists
    yet. Creates a flat group under the root if needed."""
    root = _ensure_root_item_group()
    name = (name or "").strip()
    if not name:
        return root
    if frappe.db.exists("Item Group", name):
        return name
    try:
        doc = frappe.new_doc("Item Group")
        doc.item_group_name = name
        doc.parent_item_group = root
        doc.is_group = 0
        doc.flags.ignore_permissions = True
        doc.insert()
        return name
    except Exception:
        frappe.log_error(
            title=f"WooCommerce import: failed to create Item Group {name}",
            message=frappe.get_traceback(),
        )
        return root


def _ensure_brand(name):
    """Item.brand is also a mandatory-shaped Link (to Brand), not free text."""
    name = (name or "").strip()
    if not name:
        return None
    if frappe.db.exists("Brand", name):
        return name
    try:
        doc = frappe.new_doc("Brand")
        doc.brand = name
        doc.flags.ignore_permissions = True
        doc.insert()
        return name
    except Exception:
        frappe.log_error(
            title=f"WooCommerce import: failed to create Brand {name}",
            message=frappe.get_traceback(),
        )
        return None


def _apply_tags(item_code, tags):
    from frappe.desk.doctype.tag.tag import add_tag
    for tag in tags or []:
        name = (tag.get("name") or "").strip()
        if name:
            add_tag(name, "Item", item_code)


def _reconcile_stock(item_code, warehouse, company, qty):
    """A real, audited stock movement -- not a raw Bin write. Only called
    when WooCommerce reports manage_stock on for this product/variation."""
    if not warehouse or not company:
        return
    current = flt(frappe.db.get_value(
        "Bin", {"item_code": item_code, "warehouse": warehouse}, "actual_qty"
    ) or 0)
    if current == qty:
        return
    doc = frappe.new_doc("Stock Reconciliation")
    doc.company = company
    doc.purpose = "Stock Reconciliation"
    doc.append("items", {
        "item_code": item_code,
        "warehouse": warehouse,
        "qty": qty,
    })
    doc.flags.ignore_permissions = True
    doc.insert(ignore_permissions=True)
    doc.submit()


def _item_code_for(sku, wc_id, wc_variation_id=None):
    """SKU is the natural key when WooCommerce has one; not every store sets
    one, so fall back to a WooCommerce-ID-derived code rather than skip the
    row entirely."""
    if sku:
        return sku
    if wc_variation_id:
        return f"WC-{wc_id}-{wc_variation_id}"
    return f"WC-{wc_id}"


def _set_standard_selling_price(item_code, price_list, rate):
    """Upsert Item Price the same way every other connector in this codebase
    does it -- no bespoke price field on Item."""
    if rate is None:
        return
    name = frappe.db.get_value(
        "Item Price", {"item_code": item_code, "price_list": price_list}, "name"
    )
    if name:
        frappe.db.set_value("Item Price", name, "price_list_rate", rate)
        return
    frappe.get_doc({
        "doctype": "Item Price",
        "item_code": item_code,
        "price_list": price_list,
        "price_list_rate": rate,
    }).insert(ignore_permissions=True)


def _upsert_item(item_code, item_name, description, image_url, disabled,
                  wc_product_id, wc_variation_id, item_group, brand,
                  weight, not_stocked):
    is_new = not frappe.db.exists("Item", item_code)
    if is_new:
        item = frappe.new_doc("Item")
        item.item_code = item_code
        item.stock_uom = _stock_uom()
    else:
        item = frappe.get_doc("Item", item_code)

    item.item_name = (item_name or item_code)[:140]
    item.description = description or item.item_name
    item.disabled = 0 if not disabled else 1
    item.item_group = item_group
    item.is_stock_item = 0 if not_stocked else 1
    if brand:
        item.brand = brand
    if weight:
        item.weight_per_unit = weight
    if image_url:
        item.image = image_url
    item.wc_product_id = str(wc_product_id)
    item.wc_variation_id = str(wc_variation_id) if wc_variation_id else ""
    item.flags.ignore_permissions = True

    if is_new:
        item.insert(ignore_permissions=True)
    else:
        item.save(ignore_permissions=True)

    return item.item_code, is_new


def _upsert_simple_product(product, price_list, warehouse, company):
    sku = (product.get("sku") or "").strip()
    item_code = _item_code_for(sku, product["id"])
    images = product.get("images") or []
    image_url = images[0]["src"] if images else None
    categories = product.get("categories") or []
    item_group = _ensure_item_group(categories[0]["name"] if categories else None)
    brands = product.get("brands") or []
    brand = _ensure_brand(brands[0]["name"]) if brands else None

    item_code, is_new = _upsert_item(
        item_code=item_code,
        item_name=product.get("name"),
        description=product.get("short_description") or product.get("description"),
        image_url=image_url,
        disabled=product.get("status") != "publish",
        wc_product_id=product["id"],
        wc_variation_id=None,
        item_group=item_group,
        brand=brand,
        weight=flt(product.get("weight")) if product.get("weight") else None,
        not_stocked=product.get("virtual") or product.get("downloadable"),
    )
    price = product.get("price") or product.get("regular_price")
    _set_standard_selling_price(item_code, price_list, flt(price) if price not in (None, "") else None)
    _apply_tags(item_code, product.get("tags"))

    if product.get("manage_stock") and product.get("stock_quantity") is not None:
        _reconcile_stock(item_code, warehouse, company, flt(product["stock_quantity"]))

    return is_new


def _upsert_variation(product, variation, price_list, warehouse, company):
    sku = (variation.get("sku") or "").strip()
    item_code = _item_code_for(sku, product["id"], variation["id"])
    variation_image = variation.get("image") or {}
    parent_images = product.get("images") or []
    image_url = variation_image.get("src") or (parent_images[0]["src"] if parent_images else None)
    categories = product.get("categories") or []
    item_group = _ensure_item_group(categories[0]["name"] if categories else None)
    brands = product.get("brands") or []
    brand = _ensure_brand(brands[0]["name"]) if brands else None

    # A variation's own name isn't in its payload -- attributes describe what
    # makes it distinct (e.g. Color: Black, Size: S), appended to the parent
    # product's name so the Item is identifiable on its own.
    attrs = ", ".join(
        f"{a.get('name')}: {a.get('option')}" for a in variation.get("attributes") or [] if a.get("option")
    )
    item_name = f"{product.get('name')} - {attrs}" if attrs else product.get("name")

    item_code, is_new = _upsert_item(
        item_code=item_code,
        item_name=item_name,
        description=variation.get("description") or product.get("short_description"),
        image_url=image_url,
        disabled=variation.get("status") != "publish",
        wc_product_id=product["id"],
        wc_variation_id=variation["id"],
        item_group=item_group,
        brand=brand,
        weight=flt(variation.get("weight")) if variation.get("weight") else None,
        not_stocked=variation.get("virtual") or variation.get("downloadable"),
    )
    price = variation.get("price") or variation.get("regular_price")
    _set_standard_selling_price(item_code, price_list, flt(price) if price not in (None, "") else None)
    _apply_tags(item_code, product.get("tags"))

    manage_stock = variation.get("manage_stock")
    if manage_stock is True and variation.get("stock_quantity") is not None:
        _reconcile_stock(item_code, warehouse, company, flt(variation["stock_quantity"]))

    return is_new


def pull_products(log):
    """
    Full product import: page through /products (status=any -- draft/private
    products still get an Item, just disabled=1, matching how disabled
    already means "not currently sellable" on every other connector here),
    fetching each variable product's /products/{id}/variations separately.
    Each row is isolated so one bad product/variation doesn't roll back the
    whole run; counters update incrementally and the log is saved after every
    page so progress is visible on a long-running catalogue.
    """
    settings = frappe.get_single("WooCommerce Connector Settings")
    price_list = settings.wc_price_list or "Standard Selling"
    warehouse = settings.wc_default_warehouse
    company = settings.wc_company
    client = WooCommerceClient()

    processed = created = updated = failed = 0
    pages_done = 0

    for page_rows in client.get_all_pages("products", params={"status": "any"}):
        pages_done += 1
        for product in page_rows:
            processed += 1
            try:
                if product.get("type") == "variable":
                    variations = []
                    for var_page in client.get_all_pages(f"products/{product['id']}/variations"):
                        variations.extend(var_page)
                    if not variations:
                        # A variable product with no variations yet has no
                        # sellable SKU at all -- nothing to create.
                        continue
                    any_new = False
                    for variation in variations:
                        is_new = _upsert_variation(product, variation, price_list, warehouse, company)
                        any_new = any_new or is_new
                    if any_new:
                        created += 1
                    else:
                        updated += 1
                else:
                    is_new = _upsert_simple_product(product, price_list, warehouse, company)
                    if is_new:
                        created += 1
                    else:
                        updated += 1
            except Exception:
                failed += 1
                frappe.log_error(
                    title=f"WooCommerce product pull failed: {product.get('id')}",
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
        log.error_message = f"{failed} product(s) failed -- see Error Log."[:2000]
