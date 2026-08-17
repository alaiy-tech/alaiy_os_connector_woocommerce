# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""
The actual sync work + the WooCommerce Sync Log lifecycle helpers every sync
shares. run_pull_sync / run_push_sync are the two example jobs; replace their
bodies with real logic but keep the log-create → running → success/failed
bookkeeping so the connector card and Logs list stay accurate.
"""

import frappe
from frappe.utils import now_datetime


def get_or_create_log(sync_type, trigger, log_name=None):
    """
    Return the Sync Log to use for this run. If log_name is given (the API
    layer pre-created it so it shows as 'queued' immediately) reuse it;
    otherwise create a fresh one. Newly created logs start as 'queued'.
    """
    if log_name and frappe.db.exists("WooCommerce Sync Log", log_name):
        return frappe.get_doc("WooCommerce Sync Log", log_name)

    log = frappe.new_doc("WooCommerce Sync Log")
    log.sync_type = sync_type
    log.trigger = trigger
    log.status = "queued"
    log.insert(ignore_permissions=True)
    frappe.db.commit()
    return log


def _mark_running(log):
    log.status = "running"
    log.started_at = now_datetime()
    log.save(ignore_permissions=True)
    frappe.db.commit()


def _mark_finished(log, status, error_message=None):
    log.status = status
    log.finished_at = now_datetime()
    if error_message:
        log.error_message = error_message[:2000]
    log.save(ignore_permissions=True)
    frappe.db.commit()


def _run(sync_type, trigger, log_name, worker):
    log = get_or_create_log(sync_type, trigger, log_name)
    _mark_running(log)
    try:
        worker(log)
        # A worker that isolates per-row failures (rather than raising) never
        # hits the except below, so a run with real failures would otherwise
        # still be marked "success" here -- check the counter the worker
        # itself already saved, same convention as alaiy_os_connector_
        # flipkart's pull_all_listings.
        if log.items_failed:
            _mark_finished(log, "failed", log.error_message)
        else:
            _mark_finished(log, "success")
    except Exception:
        _mark_finished(log, "failed", frappe.get_traceback())
        frappe.log_error(
            title=f"WooCommerce connector: {sync_type} sync failed",
            message=frappe.get_traceback(),
        )
        raise


def run_pull_sync(trigger="scheduled", log_name=None):
    """Pull products from WooCommerce into Alaiy OS. Kept separate from
    run_order_pull_sync -- each is its own Sync Log row with its own
    processed/created/updated/failed counts, rather than conflating two
    different kinds of record into one count."""
    from alaiy_os_connector_woocommerce.woocommerce.products import pull_products

    def worker(log):
        pull_products(log)

    _run("pull", trigger, log_name, worker)


def run_order_pull_sync(trigger="scheduled", log_name=None):
    """Pull orders from WooCommerce into Alaiy OS as Sales Orders."""
    from alaiy_os_connector_woocommerce.woocommerce.orders import pull_orders

    def worker(log):
        pull_orders(log)

    _run("pull", trigger, log_name, worker)


def run_customer_pull_sync(trigger="scheduled", log_name=None):
    """Pull the full WooCommerce customer list + addresses into Customer."""
    from alaiy_os_connector_woocommerce.woocommerce.customers import pull_customers

    def worker(log):
        pull_customers(log)

    _run("pull", trigger, log_name, worker)


def run_category_pull_sync(trigger="scheduled", log_name=None):
    """Pull the product category tree from WooCommerce into Item Group."""
    from alaiy_os_connector_woocommerce.woocommerce.categories import pull_categories

    def worker(log):
        pull_categories(log)

    _run("pull", trigger, log_name, worker)


def run_tag_pull_sync(trigger="scheduled", log_name=None):
    """Pull the product tag master list from WooCommerce into Tag."""
    from alaiy_os_connector_woocommerce.woocommerce.tags import pull_tags

    def worker(log):
        pull_tags(log)

    _run("pull", trigger, log_name, worker)


def run_attribute_pull_sync(trigger="scheduled", log_name=None):
    """Pull product attributes + their terms into Item Attribute."""
    from alaiy_os_connector_woocommerce.woocommerce.attributes import pull_attributes

    def worker(log):
        pull_attributes(log)

    _run("pull", trigger, log_name, worker)


def run_push_sync(trigger="scheduled", log_name=None):
    """Push Alaiy OS data out to the external API. TODO: implement."""
    def worker(log):
        pass

    _run("push", trigger, log_name, worker)
