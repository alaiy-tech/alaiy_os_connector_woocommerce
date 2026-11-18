# WooCommerce Connector — what it actually does

WooCommerce is the store's e-commerce platform (a WordPress plugin exposing
a REST API). Alaiy OS is the ERPNext-based back office. This connector pulls
WooCommerce's product catalog and orders into Alaiy OS as Items and Sales
Orders. This page describes what is actually wired up on `main` — see
[architecture.md](architecture.md) for a note on unmerged work that adds
more pull flows and a webhook receiver.

---

## The short version

| | Direction | Automatic? |
|---|---|---|
| Products (incl. variations) | WooCommerce → Alaiy OS | yes, on the configured Pull Sync Interval, or on demand via the connector card's Pull button |
| Orders | WooCommerce → Alaiy OS | **no** — the code exists (`run_order_pull_sync`) but nothing schedules it and no button calls it; it only runs if invoked by hand (e.g. `bench execute`) |
| Anything | Alaiy OS → WooCommerce | **no** — `run_push_sync` is an empty stub. The connector card's Push button and the Push Sync Interval setting exist, but push does nothing |

**Nothing writes to WooCommerce, ever, on `main`.** There is no code path
that sends a product, price, stock level, or order status back out — the
Push button and Push Sync Interval are wired up in the UI but the worker
behind them is empty. Order import into Alaiy OS also does not happen
automatically today, even though the import logic itself is fully written —
it is simply never called by the scheduler or by any API endpoint.

---

## Coming IN from WooCommerce

### Products
Every `bench migrate` provisions this connector; once enabled with valid
credentials, the scheduler (`sync_jobs.check_and_enqueue`, runs every
minute) enqueues a product pull whenever the configured **Pull Sync
Interval** has elapsed. The same pull also runs immediately, once, when you
press **Pull** on the Alaiy OS connector card. It pages through every
WooCommerce product (published, draft, and private), creates or updates one
Item per simple product or per variation of a variable product, sets its
price on the configured Price List, applies tags, and — only when
WooCommerce itself reports `manage_stock` on for that product/variation —
reconciles stock via a real Stock Reconciliation against the configured
warehouse.

### Orders
`pull_orders` pages through every WooCommerce order (skipping `trash` and
`failed`), matches or creates a Customer by billing email, matches each line
item to an existing Item by WooCommerce product/variation ID (falling back
to SKU), and creates a submitted Sales Order. This is real, working code —
but as noted above, nothing on `main` currently triggers it.

---

## Going OUT to WooCommerce

Nothing. `run_push_sync` has no implementation. No inventory, price, or
order-status update is ever sent to WooCommerce from `main`.
