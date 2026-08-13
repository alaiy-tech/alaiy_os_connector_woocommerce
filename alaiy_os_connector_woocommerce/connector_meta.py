"""
Single source of truth for this connector's registration metadata.
Consumed by setup/install.py → upserted into alaiy_os's OS Connector Registry.
"""

connector_meta = {
    "connector_id": "woocommerce",
    "connector_name": "WooCommerce",
    "connector_app": "alaiy_os_connector_woocommerce",
    # "channel" (sell TO — e.g. Shopify) or "supplier" (buy FROM — e.g. Cloudstore)
    "connector_type": "channel",
    "description": "Syncs orders, products, and inventory with a WooCommerce store via its REST API.",
    "icon": "box",
    "icon_url": "",
    "settings_doctype": "WooCommerce Connector Settings",
    "test_method": "alaiy_os_connector_woocommerce.api.test_connection.test_connection",
    "sync_categories_method": "alaiy_os_connector_woocommerce.api.sync.trigger_pull_sync",
    "sync_items_method": "alaiy_os_connector_woocommerce.api.sync.trigger_push_sync",
    "sync_status_method": "alaiy_os_connector_woocommerce.api.sync.get_sync_status",
    "sync_categories_label": "Pull",
    "sync_items_label": "Push",
    "is_enabled": 0,
    "connection_status": "untested",
}
