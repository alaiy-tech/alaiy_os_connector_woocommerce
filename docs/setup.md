# Setup & Configuration

This is a standalone Frappe app (`alaiy_os_connector_woocommerce`) that
ships disabled (`is_enabled = 0`). Installing it (`bench install-app`) and
running `bench migrate` registers it in Alaiy OS and provisions its custom
fields regardless of `is_enabled` — see [First enable](#4-first-enable)
below for exactly what that means. No webhooks are registered by this
connector on `main` — there is no webhook receiver on `main` at all (see
[architecture.md](architecture.md)).

---

## 1. Prerequisites
- A Frappe bench with `alaiy_os` and `erpnext` installed (`required_apps`
  in `hooks.py`).
- A WooCommerce store with the REST API enabled and a Consumer Key/Secret
  with **Read/Write** permission, created under WooCommerce →
  **Settings → Advanced → REST API** on the WordPress admin.
- The store must be reachable over HTTPS — the client does not support
  WooCommerce's query-string auth fallback for non-SSL stores.

## 2. WooCommerce credentials

| WooCommerce-side value | Settings field |
|---|---|
| Store's own site URL, e.g. `https://example.com` (no trailing slash, no `/wp-json` suffix) | Store URL |
| Consumer Key (from Settings → Advanced → REST API) | Consumer Key |
| Consumer Secret (same screen) | Consumer Secret |

These are pasted directly — there is no OAuth or client-credentials flow.
Consumer Secret is a Password field (encrypted at rest); Consumer Key is
plain Data.

## 3. WooCommerce Connector Settings — every field

Single DocType, grouped exactly as its JSON `field_order` groups them:

**(ungrouped, top)**

| Field | Type | Purpose |
|---|---|---|
| Enable WooCommerce (`is_enabled`) | Check | Master on/off switch. Default 0. The scheduler and both manual sync buttons no-op while this is off. |

**API Connection**

| Field | Type | Purpose |
|---|---|---|
| Store URL (`wc_store_url`) | Data, required | Base site URL, HTTPS. |
| Consumer Key (`wc_consumer_key`) | Data, required | REST API key. |
| Consumer Secret (`wc_consumer_secret`) | Password, required | REST API secret. |

**Alaiy OS Defaults**

| Field | Type | Purpose |
|---|---|---|
| Company (`wc_company`) | Link → Company, required | Company set on every Sales Order created from a WooCommerce order. |
| Default Warehouse (`wc_default_warehouse`) | Link → Warehouse, required | Warehouse used for stock reconciliation and Sales Order line items. |
| Price List (`wc_price_list`) | Link → Price List, required | Price List that pulled product/variation prices are written to. |

**Sync Schedule**

| Field | Type | Purpose |
|---|---|---|
| Pull Sync Interval (`wc_pull_sync_interval`) | Select: Disabled/5/15/30/60 min, default Disabled | How often the scheduler auto-enqueues a product pull. |
| Push Sync Interval (`wc_push_sync_interval`) | Select: same options, default Disabled | How often the scheduler would auto-enqueue a push — currently has no effect since the push worker is empty. |

There is no field for a webhook secret, order pull interval, or default
territory on `main` — order pull has no settings-driven schedule at all
today (see [what-it-does.md](what-it-does.md)).

## 4. First enable

Flipping `is_enabled` from 0 to 1 and saving does **not**, by itself,
provision anything — provisioning already happened on the last
`bench migrate`, independent of the flag:

- `after_install` (runs once, on `bench install-app`) clears any stale
  encrypted Consumer Secret value and forces the settings DocType to
  `issingle`.
- `after_migrate` → `sync_connector_registry` (runs on every
  `bench migrate`) registers/updates this connector's row in Alaiy OS's
  **OS Connector Registry**, re-provisions the Item/Sales Order/Customer
  custom fields below via `create_custom_fields(..., update=True)`, and
  refreshes the Alaiy OS sidebar (Connectors card + this connector's
  **WooCommerce Logs** entry).

Custom fields provisioned (idempotent, present whether or not the
connector is enabled):

| DocType | Field | Purpose |
|---|---|---|
| Item | `wc_product_id` | WooCommerce product's numeric ID. |
| Item | `wc_variation_id` | Set only for an Item pulled from a product variation; blank for a simple product. |
| Sales Order | `wc_order_id` | WooCommerce order's numeric ID. |
| Customer | `wc_customer_email` | Billing email from the order that created this Customer; used to match repeat customers. |

What `is_enabled = 1` actually gates: the per-minute scheduler
(`check_and_enqueue`) only enqueues pull/push jobs when this is on, and
`test_connection`/manual pull/push still work regardless of this flag as
long as credentials are filled in. Disabling the connector does not
unregister or remove anything already provisioned.
