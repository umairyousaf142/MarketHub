from types import SimpleNamespace
from uuid import uuid4

from core.events import cache_invalidation


def test_product_save_receiver_invalidates_product_detail_cache(monkeypatch):
    calls = []

    monkeypatch.setattr(
        cache_invalidation,
        "invalidate_product_detail_cache",
        lambda product_id: calls.append(product_id),
    )

    product_id = uuid4()
    instance = SimpleNamespace(id=product_id)

    cache_invalidation.invalidate_product_cache_on_save(
        sender=None,
        instance=instance,
    )

    assert calls == [product_id]


def test_category_save_and_delete_receivers_invalidate_category_tree_cache(monkeypatch):
    calls = []

    monkeypatch.setattr(
        cache_invalidation,
        "invalidate_category_tree_cache",
        lambda: calls.append("category-tree"),
    )

    instance = SimpleNamespace(id=uuid4())

    cache_invalidation.invalidate_category_cache_on_save(
        sender=None,
        instance=instance,
    )
    cache_invalidation.invalidate_category_cache_on_delete(
        sender=None,
        instance=instance,
    )

    assert calls == [
        "category-tree",
        "category-tree",
    ]


def test_vendor_save_receiver_invalidates_vendor_profile_cache(monkeypatch):
    calls = []

    monkeypatch.setattr(
        cache_invalidation,
        "invalidate_vendor_profile_cache",
        lambda vendor_id: calls.append(vendor_id),
    )

    vendor_id = uuid4()
    instance = SimpleNamespace(id=vendor_id)

    cache_invalidation.invalidate_vendor_cache_on_save(
        sender=None,
        instance=instance,
    )

    assert calls == [vendor_id]


def test_order_save_receiver_invalidates_bestsellers_only_when_created(monkeypatch):
    calls = []

    monkeypatch.setattr(
        cache_invalidation,
        "invalidate_bestsellers_global_cache",
        lambda: calls.append("bestsellers"),
    )

    instance = SimpleNamespace(id=uuid4())

    cache_invalidation.invalidate_bestsellers_cache_on_order_save(
        sender=None,
        instance=instance,
        created=True,
    )
    cache_invalidation.invalidate_bestsellers_cache_on_order_save(
        sender=None,
        instance=instance,
        created=False,
    )

    assert calls == ["bestsellers"]


def test_cart_item_save_and_delete_receivers_invalidate_session_cart_cache(monkeypatch):
    calls = []

    monkeypatch.setattr(
        cache_invalidation,
        "invalidate_cart_cache",
        lambda session_key: calls.append(session_key),
    )

    instance = SimpleNamespace(
        cart=SimpleNamespace(session_key="session-123")
    )

    cache_invalidation.invalidate_cart_cache_on_cart_item_save(
        sender=None,
        instance=instance,
    )
    cache_invalidation.invalidate_cart_cache_on_cart_item_delete(
        sender=None,
        instance=instance,
    )

    assert calls == [
        "session-123",
        "session-123",
    ]


def test_cart_item_receivers_skip_missing_session_key(monkeypatch):
    calls = []

    monkeypatch.setattr(
        cache_invalidation,
        "invalidate_cart_cache",
        lambda session_key: calls.append(session_key),
    )

    instance_without_cart = SimpleNamespace(cart=None)
    instance_without_session = SimpleNamespace(
        cart=SimpleNamespace(session_key="")
    )

    cache_invalidation.invalidate_cart_cache_on_cart_item_save(
        sender=None,
        instance=instance_without_cart,
    )
    cache_invalidation.invalidate_cart_cache_on_cart_item_delete(
        sender=None,
        instance=instance_without_session,
    )

    assert calls == []