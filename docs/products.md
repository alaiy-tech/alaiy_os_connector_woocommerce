# Products — WooCommerce → Item

`woocommerce/products.py::pull_products` pages through `/products`
(`status=any` — draft/private products still get an Item, just
`disabled=1`), fetching each `variable` product's `/products/{id}/variations`
separately since a variable product's own SKU/price are blank on the
parent — its variations are the real sellable SKUs. Each variation becomes
its own flat Item, not ERPNext's Item Attribute/Template variant machinery.

Every field maps onto a real, existing ERPNext field or doctype:

| WooCommerce field | Alaiy OS target |
|---|---|
| `price` (current effective price, already reflects an active sale) | Item Price, "Standard Selling" list — **not** `regular_price` |
| `images[0]` | `Item.image` |
| `categories[0]` (first only) | `Item.item_group` — WooCommerce's multi-category model doesn't fit a single Link field |
| `tags` | Frappe's generic tagging (`add_tag`), not a bespoke field |
| `brands[0]` | `Item.brand` (created on first use) |
| `weight` | `Item.weight_per_unit` |
| `virtual` / `downloadable` | `Item.is_stock_item = 0` |
| `stock_quantity` (only when `manage_stock` is on) | a real **Stock Reconciliation** against the configured warehouse — an audited movement, not a raw Bin write |
| `id` / variation `id` | `wc_product_id` / `wc_variation_id` custom fields — no ERPNext equivalent exists |

**Item code**: the WooCommerce SKU when set, else `WC-<product_id>` (or
`WC-<product_id>-<variation_id>` for a variation) — not every store sets a
SKU, so falling back to a WooCommerce-ID-derived code means the row still
imports instead of being skipped.

**Deliberately not mapped** — no real ERPNext equivalent, not worth
inventing one for a first pass: dimensions, `tax_status`/`tax_class`,
`meta_data`, `menu_order`, `featured`, `catalog_visibility`,
`grouped_products`, `external_url`/`button_text`.

Each row (product or variation) is isolated in its own try/except — one bad
row logs to Error Log and increments `items_failed`, the rest of the page
still imports. `_ensure_item_group`/`_ensure_brand` self-heal a missing
root Item Group before creating a category-derived child group (a site
whose Selling/Stock module was never fully onboarded can be missing the
standard "All Item Groups" root entirely).

Triggered by the scheduler (`wc_pull_sync_interval`, default Disabled) or
the connector card's **Pull** button. See [architecture.md](architecture.md)
for the Sync Log lifecycle and failure-counting rule.
