# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""
Inbound WooCommerce webhook receiver -- real-time pull to complement the
polling-based run_pull_sync/run_order_pull_sync in woocommerce/sync.py.
Same HMAC-over-raw-body pattern as alaiy_os_connector_shopify's
api/webhooks.py, adapted to WooCommerce's own headers/algorithm
(X-WC-Webhook-Signature, base64 HMAC-SHA256 -- WooCommerce's own webhook
docs, not Shopify's header names).
"""

import base64
import hashlib
import hmac
import json

import frappe

_ORDER_TOPICS = {"order.created", "order.updated", "order.deleted"}
_PRODUCT_TOPICS = {"product.created", "product.updated", "product.deleted"}


@frappe.whitelist(allow_guest=True)
def handle_webhook():
    request = frappe.request
    topic = (request.headers.get("X-WC-Webhook-Topic") or "").strip()
    signature = request.headers.get("X-WC-Webhook-Signature") or ""
    raw_body = request.data

    settings = frappe.get_single("WooCommerce Connector Settings")
    if not settings.is_enabled:
        frappe.response.status_code = 200
        return {"ok": False, "reason": "connector disabled"}

    # Fail CLOSED: no secret configured means every request is rejected,
    # never silently accepted (same convention as Shopify's receiver).
    secret = settings.get_password("wc_webhook_secret", raise_exception=False)
    if not secret:
        frappe.log_error(title="WooCommerce webhook rejected: no secret configured")
        frappe.response.status_code = 401
        return {"ok": False, "reason": "no secret configured"}

    computed = base64.b64encode(
        hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).digest()
    ).decode("utf-8")
    if not signature or not hmac.compare_digest(computed, signature):
        frappe.log_error(
            title="WooCommerce webhook rejected: signature mismatch (diagnostic)",
            message=f"topic={topic!r}",
        )
        frappe.response.status_code = 401
        return {"ok": False, "reason": "signature validation failed"}

    # WooCommerce sends a blank-body ping when a webhook is first created --
    # a real delivery, not an error, just nothing to dispatch yet.
    if not raw_body:
        frappe.response.status_code = 200
        return {"ok": True, "reason": "ping"}

    try:
        payload = json.loads(raw_body)
    except Exception:
        frappe.log_error(
            title="WooCommerce webhook rejected: invalid JSON (diagnostic)",
            message=f"topic={topic!r} raw_body[:200]={raw_body[:200]!r}",
        )
        frappe.response.status_code = 400
        return {"ok": False, "reason": "invalid JSON"}

    _dispatch(topic, payload)
    frappe.response.status_code = 200
    return {"ok": True}


def _dispatch(topic, payload):
    if topic in _ORDER_TOPICS:
        frappe.enqueue(
            "alaiy_os_connector_woocommerce.woocommerce.webhook.handle_order_webhook",
            queue="short",
            timeout=300,
            topic=topic,
            payload=payload,
        )
    elif topic in _PRODUCT_TOPICS:
        frappe.enqueue(
            "alaiy_os_connector_woocommerce.woocommerce.webhook.handle_product_webhook",
            queue="short",
            timeout=300,
            topic=topic,
            payload=payload,
        )
