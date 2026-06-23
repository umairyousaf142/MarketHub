from datetime import date, datetime


PRODUCT_DETAIL_TTL = 60 * 10
CATEGORY_TREE_TTL = 60 * 60
VENDOR_PROFILE_TTL = 60 * 15
BESTSELLERS_GLOBAL_TTL = 60 * 30
CART_TTL = 60 * 60 * 24
ANALYTICS_SNAPSHOT_TTL = 60 * 60 * 24


def normalize_cache_identifier(value):
    if isinstance(value, datetime):
        return value.date().isoformat()

    if isinstance(value, date):
        return value.isoformat()

    return str(value)


def product_detail_key(product_id):
    return f"product:{normalize_cache_identifier(product_id)}:detail"


def category_tree_key():
    return "category:tree"


def vendor_profile_key(vendor_id):
    return f"vendor:{normalize_cache_identifier(vendor_id)}:profile"


def bestsellers_global_key():
    return "bestsellers:global"


def cart_key(session_key):
    return f"cart:{normalize_cache_identifier(session_key)}"


def analytics_snapshot_key(snapshot_date):
    return f"analytics:snapshot:{normalize_cache_identifier(snapshot_date)}"