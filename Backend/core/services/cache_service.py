import logging

from django.core.cache import cache

from core.services.cache_keys import (
    ANALYTICS_SNAPSHOT_TTL,
    BESTSELLERS_GLOBAL_TTL,
    CART_TTL,
    CATEGORY_TREE_TTL,
    PRODUCT_DETAIL_TTL,
    VENDOR_PROFILE_TTL,
    analytics_snapshot_key,
    bestsellers_global_key,
    cart_key,
    category_tree_key,
    product_detail_key,
    vendor_profile_key,
)


logger = logging.getLogger(__name__)


def cache_get(key, default=None):
    return cache.get(key, default)


def cache_set(key, value, timeout):
    cache.set(key, value, timeout=timeout)

    return value


def cache_get_or_set(key, producer, timeout):
    cached_value = cache.get(key)

    if cached_value is not None:
        return cached_value

    value = producer()
    cache.set(key, value, timeout=timeout)

    return value


def cache_delete(key):
    deleted = cache.delete(key)

    logger.debug(
        "Cache key deleted.",
        extra={
            "cache_key": key,
            "deleted": deleted,
        },
    )

    return deleted


def cache_delete_many(keys):
    keys = [key for key in keys if key]

    if not keys:
        return None

    return cache.delete_many(keys)


def set_product_detail_cache(product_id, value):
    return cache_set(
        product_detail_key(product_id),
        value,
        PRODUCT_DETAIL_TTL,
    )


def get_product_detail_cache(product_id, default=None):
    return cache_get(product_detail_key(product_id), default)


def invalidate_product_detail_cache(product_id):
    return cache_delete(product_detail_key(product_id))


def set_category_tree_cache(value):
    return cache_set(
        category_tree_key(),
        value,
        CATEGORY_TREE_TTL,
    )


def get_category_tree_cache(default=None):
    return cache_get(category_tree_key(), default)


def invalidate_category_tree_cache():
    return cache_delete(category_tree_key())


def set_vendor_profile_cache(vendor_id, value):
    return cache_set(
        vendor_profile_key(vendor_id),
        value,
        VENDOR_PROFILE_TTL,
    )


def get_vendor_profile_cache(vendor_id, default=None):
    return cache_get(vendor_profile_key(vendor_id), default)


def invalidate_vendor_profile_cache(vendor_id):
    return cache_delete(vendor_profile_key(vendor_id))


def set_bestsellers_global_cache(value):
    return cache_set(
        bestsellers_global_key(),
        value,
        BESTSELLERS_GLOBAL_TTL,
    )


def get_bestsellers_global_cache(default=None):
    return cache_get(bestsellers_global_key(), default)


def invalidate_bestsellers_global_cache():
    return cache_delete(bestsellers_global_key())


def set_cart_cache(session_key, value):
    if not session_key:
        return None

    return cache_set(
        cart_key(session_key),
        value,
        CART_TTL,
    )


def get_cart_cache(session_key, default=None):
    if not session_key:
        return default

    return cache_get(cart_key(session_key), default)


def invalidate_cart_cache(session_key):
    if not session_key:
        return None

    return cache_delete(cart_key(session_key))


def set_analytics_snapshot_cache(snapshot_date, value):
    return cache_set(
        analytics_snapshot_key(snapshot_date),
        value,
        ANALYTICS_SNAPSHOT_TTL,
    )


def get_analytics_snapshot_cache(snapshot_date, default=None):
    return cache_get(analytics_snapshot_key(snapshot_date), default)


def invalidate_analytics_snapshot_cache(snapshot_date):
    return cache_delete(analytics_snapshot_key(snapshot_date))