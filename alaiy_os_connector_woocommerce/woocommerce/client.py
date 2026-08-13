# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""
HTTP client for the WooCommerce REST API v3.

Auth: HTTP Basic Auth with the Consumer Key as username and Consumer Secret
as password -- the documented, secure method for an HTTPS store (every real
deployment). WooCommerce also supports passing consumer_key/consumer_secret
as query-string params for non-SSL sites, but that's deliberately not
supported here: it puts real credentials in plaintext URLs/server logs, and
every genuine WooCommerce install should be on HTTPS.

Retry policy mirrors alaiy_os_connector_fedex's client.py (fixed max
retries, linear backoff, honors Retry-After) -- WooCommerce's own REST API
docs don't specify a rate-limit contract the way Shopify's does, so this is
the same conservative default already proven in this codebase rather than
no retry at all (confirmed gap in alaiy_os_connector_flipkart/cloudstore,
which have none).
"""

import time

import frappe
import requests
from requests.auth import HTTPBasicAuth

API_PREFIX = "wp-json/wc/v3"

# (connect, read) tuple, not a single value -- a stalled response raises
# requests.Timeout instead of blocking the RQ job's own death-penalty
# timeout for the whole worker (same convention as Shopify's graphql_client).
_DEFAULT_TIMEOUT = (10, 60)

_RETRYABLE_STATUS = (429, 500, 502, 503, 504)
_MAX_RETRIES = 3
_DEFAULT_RETRY_AFTER_SECONDS = 2


class WooCommerceAPIError(Exception):
    """Raised with the response body preserved (WooCommerce error bodies are
    {"code": "...", "message": "...", "data": {"status": ...}})."""

    def __init__(self, message, status_code=None, wc_code=None, retryable=False):
        super().__init__(message)
        self.status_code = status_code
        self.wc_code = wc_code
        self.retryable = retryable


def _parse_wc_error(resp):
    try:
        body = resp.json()
    except ValueError:
        return None, resp.text[:300]
    return body.get("code"), body.get("message") or resp.text[:300]


class WooCommerceClient:
    def __init__(self):
        settings = frappe.get_single("WooCommerce Connector Settings")
        store_url = (settings.wc_store_url or "").strip().rstrip("/")
        consumer_key = (settings.wc_consumer_key or "").strip()
        consumer_secret = settings.get_password("wc_consumer_secret") if settings.wc_consumer_secret else None

        if not store_url or not consumer_key or not consumer_secret:
            raise RuntimeError(
                "WooCommerce connector is not configured (Store URL / Consumer Key / Consumer Secret missing)."
            )
        if not store_url.startswith("https://"):
            frappe.log_error(
                title="WooCommerce connector: store URL is not HTTPS",
                message=f"{store_url} -- Basic Auth credentials will be sent in plaintext over the network.",
            )

        self.base_url = f"{store_url}/{API_PREFIX}"
        self._auth = HTTPBasicAuth(consumer_key, consumer_secret)

    def _request(self, method, path, params=None, json=None, timeout=_DEFAULT_TIMEOUT):
        url = f"{self.base_url}/{path.lstrip('/')}"
        last_resp = None
        for attempt in range(_MAX_RETRIES + 1):
            resp = requests.request(
                method, url, auth=self._auth, params=params, json=json, timeout=timeout,
            )
            if resp.status_code < 400:
                return resp

            last_resp = resp
            if resp.status_code not in _RETRYABLE_STATUS or attempt == _MAX_RETRIES:
                break

            retry_after = resp.headers.get("Retry-After")
            wait = float(retry_after) if retry_after and retry_after.isdigit() else _DEFAULT_RETRY_AFTER_SECONDS
            time.sleep(wait * (attempt + 1))

        wc_code, message = _parse_wc_error(last_resp)
        raise WooCommerceAPIError(
            f"{wc_code or last_resp.status_code}: {message}",
            status_code=last_resp.status_code,
            wc_code=wc_code,
            retryable=last_resp.status_code in _RETRYABLE_STATUS,
        )

    def get(self, path, params=None, timeout=_DEFAULT_TIMEOUT):
        return self._request("GET", path, params=params, timeout=timeout).json()

    def post(self, path, json=None, timeout=_DEFAULT_TIMEOUT):
        return self._request("POST", path, json=json, timeout=timeout).json()

    def put(self, path, json=None, timeout=_DEFAULT_TIMEOUT):
        return self._request("PUT", path, json=json, timeout=timeout).json()

    def delete(self, path, params=None, timeout=_DEFAULT_TIMEOUT):
        return self._request("DELETE", path, params=params, timeout=timeout).json()

    def get_all_pages(self, path, params=None, per_page=100, timeout=_DEFAULT_TIMEOUT):
        """Paginates a WooCommerce list endpoint (products, orders, ...) using
        its page/per_page params and X-WP-TotalPages response header.
        Yields each page's list of rows."""
        page = 1
        page_params = dict(params or {})
        page_params["per_page"] = per_page
        while True:
            page_params["page"] = page
            resp = self._request("GET", path, params=page_params, timeout=timeout)
            rows = resp.json()
            if not rows:
                return
            yield rows

            total_pages = int(resp.headers.get("X-WP-TotalPages") or 1)
            if page >= total_pages:
                return
            page += 1
