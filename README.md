# Alaiy OS Connector: WooCommerce

Connects a WooCommerce store to [Alaiy OS](https://alaiy.com), syncing
products, orders, and inventory through WooCommerce's REST API v3.

## Features

- **Product import** — pulls the full catalog, including variable products
  and their variations, and keeps price, images, category, brand, tags,
  weight, and stock in sync.
- **Secure authentication** — HTTP Basic Auth over HTTPS using a WooCommerce
  REST API key (Consumer Key/Secret), with a live Test Connection check.
- **Resilient sync** — automatic retry with backoff on rate limits and
  transient errors, paginated fetches, and a full sync log with per-run
  counts and failure detail.
- **Scheduled or on-demand** — configurable pull/push intervals, with a
  guard against a crashed run blocking future syncs.

## Setup

1. In WooCommerce: **Settings → Advanced → REST API**, create a key with
   **Read/Write** permission.
2. In Alaiy OS: open **WooCommerce Connector Settings** and fill in:
   - **Store URL** — e.g. `https://example.com` (HTTPS required, no
     trailing slash or `/wp-json` suffix).
   - **Consumer Key** / **Consumer Secret** — from step 1.
   - **Company** / **Default Warehouse** / **Price List** — where synced
     data lands in Alaiy OS.
3. Click **Test Connection** to confirm the credentials work.
4. Enable the connector and save.

## Roadmap

Order and customer sync, and pushing inventory/price updates back to
WooCommerce, are planned next.

## License

AGPL-3.0
