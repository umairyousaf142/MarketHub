from datetime import date, datetime
from uuid import uuid4

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
    normalize_cache_identifier,
    product_detail_key,
    vendor_profile_key,
)


def test_normalize_cache_identifier_handles_date_datetime_and_raw_values():
    assert normalize_cache_identifier(date(2026, 6, 24)) == "2026-06-24"
    assert normalize_cache_identifier(datetime(2026, 6, 24, 10, 30)) == "2026-06-24"
    assert normalize_cache_identifier(123) == "123"

    raw_id = uuid4()

    assert normalize_cache_identifier(raw_id) == str(raw_id)


def test_cache_key_formats_match_phase_11_strategy():
    product_id = uuid4()
    vendor_id = uuid4()

    assert product_detail_key(product_id) == f"product:{product_id}:detail"
    assert category_tree_key() == "category:tree"
    assert vendor_profile_key(vendor_id) == f"vendor:{vendor_id}:profile"
    assert bestsellers_global_key() == "bestsellers:global"
    assert cart_key("session-123") == "cart:session-123"
    assert analytics_snapshot_key(date(2026, 6, 24)) == "analytics:snapshot:2026-06-24"


def test_ttl_constants_are_positive_integers():
    ttl_values = [
        PRODUCT_DETAIL_TTL,
        CATEGORY_TREE_TTL,
        VENDOR_PROFILE_TTL,
        BESTSELLERS_GLOBAL_TTL,
        CART_TTL,
        ANALYTICS_SNAPSHOT_TTL,
    ]

    for ttl in ttl_values:
        assert isinstance(ttl, int)
        assert ttl > 0