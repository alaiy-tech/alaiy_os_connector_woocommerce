# WooCommerce Connector — Docs

- [What it does](what-it-does.md) — plain-English map of every flow
- [Setup](setup.md) — credentials, settings, enabling it
- [Architecture](architecture.md) — auth, client, sync engine, scheduler
- [Products](products.md) — product/variation import into Item
- [Orders](orders.md) — order import into Sales Order

These docs describe the `main` branch only. Two open branches
(`feat/pull-extensions`, and its unmerged commit on top of the merged
`feat/product-import`) add a webhook receiver and several more pull
flows (categories, tags, attributes, full customer list, order notes)
that are **not yet on `main`** — see the note at the top of
[architecture.md](architecture.md) for what that unmerged work covers.
