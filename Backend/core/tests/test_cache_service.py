from datetime import date
from uuid import uuid4

import pytest
from django.core.cache import cache

from core.services import cache_service
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


@pytest.fixture(autouse=True)
def clear_cache():
    cache.clear()
    yield
    cache.clear()


def test_cache_set_get_delete_roundtrip():
    cache_service.cache_set("test:key", {"value": 1}, timeout=60)

    assert cache_service.cache_get("test:key") == {"value": 1}

    deleted = cache_service.cache_delete("test:key")

    assert deleted in [True, False]
    assert cache_service.cache_get("test:key") is None


def test_cache_get_or_set_uses_cached_value():
    cache_service.cache_set("existing:key", "cached-value", timeout=60)

    def producer():
        raise AssertionError("Producer should not be called when cache exists.")

    result = cache_service.cache_get_or_set(
        "existing:key",
        producer,
        timeout=60,
    )

    assert result == "cached-value"


def test_cache_get_or_set_calls_producer_on_miss_and_caches_value():
    calls = []

    def producer():
        calls.append("called")
        return {"fresh": True}

    result = cache_service.cache_get_or_set(
        "missing:key",
        producer,
        timeout=60,
    )

    assert result == {"fresh": True}
    assert calls == ["called"]
    assert cache_service.cache_get("missing:key") == {"fresh": True}


def test_cache_delete_many_handles_empty_key_list():
    assert cache_service.cache_delete_many([]) is None
    assert cache_service.cache_delete_many([None, ""]) is None


def test_product_detail_helpers_use_expected_key_and_ttl(monkeypatch):
    product_id = uuid4()
    calls = []

    def fake_cache_set(key, value, timeout):
        calls.append((key, value, timeout))
        return value

    monkeypatch.setattr(cache_service, "cache_set", fake_cache_set)

    value = {"id": str(product_id)}

    result = cache_service.set_product_detail_cache(product_id, value)

    assert result == value
    assert calls == [
        (
            product_detail_key(product_id),
            value,
            PRODUCT_DETAIL_TTL,
        )
    ]


def test_category_tree_helpers_use_expected_key_and_ttl(monkeypatch):
    calls = []

    def fake_cache_set(key, value, timeout):
        calls.append((key, value, timeout))
        return value

    monkeypatch.setattr(cache_service, "cache_set", fake_cache_set)

    value = [{"name": "Electronics"}]

    result = cache_service.set_category_tree_cache(value)

    assert result == value
    assert calls == [
        (
            category_tree_key(),
            value,
            CATEGORY_TREE_TTL,
        )
    ]


def test_vendor_profile_helpers_use_expected_key_and_ttl(monkeypatch):
    vendor_id = uuid4()
    calls = []

    def fake_cache_set(key, value, timeout):
        calls.append((key, value, timeout))
        return value

    monkeypatch.setattr(cache_service, "cache_set", fake_cache_set)

    value = {"store_name": "Test Store"}

    result = cache_service.set_vendor_profile_cache(vendor_id, value)

    assert result == value
    assert calls == [
        (
            vendor_profile_key(vendor_id),
            value,
            VENDOR_PROFILE_TTL,
        )
    ]


def test_bestsellers_helpers_use_expected_key_and_ttl(monkeypatch):
    calls = []

    def fake_cache_set(key, value, timeout):
        calls.append((key, value, timeout))
        return value

    monkeypatch.setattr(cache_service, "cache_set", fake_cache_set)

    value = [{"product_id": "abc"}]

    result = cache_service.set_bestsellers_global_cache(value)

    assert result == value
    assert calls == [
        (
            bestsellers_global_key(),
            value,
            BESTSELLERS_GLOBAL_TTL,
        )
    ]


def test_cart_helpers_ignore_empty_session_key():
    assert cache_service.set_cart_cache("", {"items": []}) is None
    assert cache_service.get_cart_cache("", default={"empty": True}) == {"empty": True}
    assert cache_service.invalidate_cart_cache("") is None


def test_analytics_snapshot_helpers_use_expected_key_and_ttl(monkeypatch):
    snapshot_date = date(2026, 6, 24)
    calls = []

    def fake_cache_set(key, value, timeout):
        calls.append((key, value, timeout))
        return value

    monkeypatch.setattr(cache_service, "cache_set", fake_cache_set)

    value = {"orders": 10}

    result = cache_service.set_analytics_snapshot_cache(snapshot_date, value)

    assert result == value
    assert calls == [
        (
            analytics_snapshot_key(snapshot_date),
            value,
            ANALYTICS_SNAPSHOT_TTL,
        )
    ]


def test_cache_core_functions_are_fail_safe_when_backend_raises(monkeypatch):
    class BrokenCache:
        def get(self, *args, **kwargs):
            raise RuntimeError("cache get failed")

        def set(self, *args, **kwargs):
            raise RuntimeError("cache set failed")

        def delete(self, *args, **kwargs):
            raise RuntimeError("cache delete failed")

        def delete_many(self, *args, **kwargs):
            raise RuntimeError("cache delete many failed")

    monkeypatch.setattr(cache_service, "cache", BrokenCache())

    assert cache_service.cache_get("broken:key", default="fallback") == "fallback"
    assert cache_service.cache_set("broken:key", "value", timeout=60) == "value"
    assert cache_service.cache_delete("broken:key") is False
    assert cache_service.cache_delete_many(["broken:key"]) is None

    calls = []

    def producer():
        calls.append("called")
        return "fresh"

    assert cache_service.cache_get_or_set("broken:key", producer, timeout=60) == "fresh"
    assert calls == ["called"]