# Architecture

> **Unmerged work exists that this page does not describe.** PR #3
> (`feat/pull-extensions`, "Add webhook receiver, category/tag/attribute/
> customer pull, order notes") shows as GitHub-merged, but its base branch
> was `feat/product-import`, not `main` — its merge commit is **not** an
> ancestor of `main`. That work (a webhook receiver, plus pulls for
> categories, tags, attributes, full customer list, and order notes) is
> real and written, but does not run on `main` today. Everything below
> describes `main` only.

## Client (`woocommerce/client.py`)

`WooCommerceClient` wraps the WooCommerce REST API v3 (`wp-json/wc/v3`).

- **Auth**: HTTP Basic Auth, Consumer Key as username, Consumer Secret as
  password. WooCommerce's query-string auth fallback for non-HTTPS stores
  is deliberately not supported — logs a warning if the configured Store
  URL isn't `https://`.
- **Retry**: up to 3 retries on `429/500/502/503/504`, honoring
  `Retry-After` when present, linear backoff otherwise (same policy as
  `alaiy_os_connector_fedex`'s client — a real gap in Cloudstore/Flipkart's
  clients, which have no retry at all).
- **Timeout**: `(10, 60)` connect/read tuple, so a stalled response raises
  `requests.Timeout` instead of blocking the whole RQ worker.
- `get_all_pages(path, params)` — generator over WooCommerce's
  `page`/`per_page` pagination, stopping via the `X-WP-TotalPages` response
  header.

## Sync engine (`woocommerce/sync.py`)

`_run(sync_type, trigger, log_name, worker)` is the shared lifecycle every
sync goes through: create/reuse a **WooCommerce Sync Log** row → mark
`running` → call `worker(log)` → mark `success` or `failed`.

**The worker owns its own failure counting.** `pull_products`/`pull_orders`
isolate each row in its own try/except so one bad product/order doesn't
abort the whole page — they increment `log.items_failed` instead of
raising. Because of that, `_run` checks `log.items_failed` itself after the
worker returns cleanly: a run where every row individually failed would
otherwise still fall through to `success` in the `try` block with nothing
ever raised. Same shape as `alaiy_os_connector_flipkart`'s
`pull_all_listings` — described there as "never report a batch successful
if any row in it failed."

Three entry points: `run_pull_sync` (products), `run_order_pull_sync`
(orders — see [what-it-does.md](what-it-does.md), nothing on `main` calls
this today), `run_push_sync` (empty stub, `def worker(log): pass`).

## Scheduler (`woocommerce/sync_jobs.py`)

`hooks.py` runs `check_and_enqueue()` every minute via `scheduler_events`.
It reads `wc_pull_sync_interval`/`wc_push_sync_interval` from Settings and
enqueues `run_pull_sync`/`run_push_sync` respectively when:
- the connector is `is_enabled`,
- the configured interval has actually elapsed since the last **success**,
- no job of that `sync_type` is already `running` (a job stuck `running`
  for more than 30 minutes is treated as dead and no longer blocks).

There is no `sync_type` for orders in this scheduler at all — `wc_pull_sync_interval`
only ever triggers `run_pull_sync` (products). This is the concrete reason
order import never runs unattended on `main`.

## Settings (`WooCommerceConnectorSettings`, Single DocType)

See [setup.md](setup.md) for every field. `is_enabled` gates the scheduler
only — `test_connection` and manual pull/push still work with it off, as
long as credentials are filled in.

## Provisioning (`setup/install.py`)

`after_install` (once, on `bench install-app`) clears any stale encrypted
Consumer Secret and forces the Settings DocType to `issingle`.
`after_migrate` → `sync_connector_registry` (every `bench migrate`,
regardless of `is_enabled`) registers the connector in Alaiy OS's **OS
Connector Registry**, provisions the custom fields (`wc_product_id`,
`wc_variation_id`, `wc_order_id`, `wc_customer_email`) idempotently via
`create_custom_fields(..., update=True)`, and refreshes the Alaiy OS
sidebar.
