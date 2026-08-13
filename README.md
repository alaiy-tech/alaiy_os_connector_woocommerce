# Alaiy OS Connector: WooCommerce

Syncs orders, products, and inventory between Alaiy OS and a WooCommerce
store via WooCommerce's REST API v3.

## Setup

1. In the WooCommerce store's WordPress admin: **WooCommerce > Settings >
   Advanced > REST API**, create a key with **Read/Write** permission.
2. In Alaiy OS: **WooCommerce Connector Settings**, fill in:
   - **Store URL** — the site's own URL, e.g. `https://example.com` (no
     trailing slash, no `/wp-json` suffix — the client appends
     `/wp-json/wc/v3` itself). Must be HTTPS.
   - **Consumer Key** / **Consumer Secret** — from step 1.
   - **Company** / **Default Warehouse** / **Price List** — where synced
     data lands in Alaiy OS.
3. Click **Test Connection** to confirm the credentials work.
4. Check **Enable WooCommerce**, save.

## What's implemented

- Registry registration, settings form with a live connector status card,
  Test Connection, and a `WooCommerce Sync Log` doctype with scheduler
  support (pull/push interval Selects, staleness guard against a crashed
  job blocking the schedule forever).
- `WooCommerceClient` (`woocommerce/client.py`): HTTP Basic Auth (Consumer
  Key/Secret), retry with backoff on `429/500/502/503/504` (honors
  `Retry-After`), and a paginated-GET helper for list endpoints
  (products/orders).
- `Item.wc_product_id` / `Item.sync_to_woocommerce` custom fields,
  provisioned unconditionally on every `bench migrate` (not gated behind
  enabling the connector first).

## Still to build

`run_pull_sync` / `run_push_sync` (`woocommerce/sync.py`) are stubs —
the actual product/order/inventory sync logic against WooCommerce's REST
API isn't implemented yet. The queued → running → success/failed log
bookkeeping around them already works; only the `worker(log)` bodies need
real logic.
