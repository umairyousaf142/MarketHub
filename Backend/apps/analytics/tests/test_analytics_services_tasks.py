from datetime import date, datetime, time, timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.utils import timezone

from apps.accounts.tests.factories import CustomerUserFactory
from apps.analytics.models import AnalyticsSnapshot
from apps.analytics.services import (
    build_daily_snapshot_metrics,
    calculate_new_customers,
    calculate_total_orders,
    calculate_total_revenue,
    compute_daily_analytics_snapshot,
    get_analytics_snapshot_for_date,
    get_paid_orders_queryset,
    get_top_product,
    get_top_vendor,
    get_vendor_dashboard_metrics,
    normalize_money,
    resolve_snapshot_date,
)
from apps.analytics.tasks import compute_daily_analytics_snapshot_task
from apps.cart.tests.factories import CartFactory, CartItemFactory
from apps.catalog.models import Product
from apps.catalog.tests.factories import ApprovedVendorFactory, ProductFactory
from apps.inventory.tests.factories import InventoryRecordFactory
from apps.orders.models import Order, OrderItem


pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def clear_cache():
    cache.clear()
    yield
    cache.clear()


def make_day_datetime(snapshot_date, hour=12):
    return timezone.make_aware(
        datetime.combine(snapshot_date, time(hour=hour)),
        timezone.get_current_timezone(),
    )


def order_field_names():
    return {field.name for field in Order._meta.get_fields()}


def create_active_product_with_inventory(
    *,
    vendor=None,
    base_price=Decimal("50.00"),
    quantity_on_hand=100,
):
    product = ProductFactory(
        vendor=vendor or ApprovedVendorFactory(),
        base_price=base_price,
        status=Product.Status.ACTIVE,
    )

    InventoryRecordFactory(
        product=product,
        variant=None,
        quantity_on_hand=quantity_on_hand,
        quantity_reserved=0,
        track_inventory=True,
        allow_backorder=False,
    )

    return product


def mark_order_paid_for_date(order, snapshot_date):
    paid_at = make_day_datetime(snapshot_date)

    updates = {}

    if "payment_status" in order_field_names():
        updates["payment_status"] = Order.PaymentStatus.PAID

    if "paid_at" in order_field_names():
        updates["paid_at"] = paid_at

    if "created_at" in order_field_names():
        updates["created_at"] = paid_at

    Order.objects.filter(pk=order.pk).update(**updates)
    order.refresh_from_db()

    return order


def create_order_with_product(
    *,
    customer=None,
    product=None,
    vendor=None,
    snapshot_date=None,
    base_price=Decimal("50.00"),
    quantity=1,
    paid=True,
):
    customer = customer or CustomerUserFactory()
    product = product or create_active_product_with_inventory(
        vendor=vendor,
        base_price=base_price,
    )

    cart = CartFactory(customer=customer)

    CartItemFactory(
        cart=cart,
        product=product,
        quantity=quantity,
    )

    order = Order.create_from_cart(cart)

    if paid:
        order = mark_order_paid_for_date(
            order,
            snapshot_date or timezone.localdate(),
        )

    order_item = OrderItem.objects.filter(order=order).first()

    return order, order_item, product, customer


def test_resolve_snapshot_date_handles_none_date_datetime_and_string():
    today = timezone.localdate()

    assert resolve_snapshot_date() == today
    assert resolve_snapshot_date(date(2026, 6, 24)) == date(2026, 6, 24)
    assert resolve_snapshot_date(datetime(2026, 6, 24, 10, 30)) == date(2026, 6, 24)
    assert resolve_snapshot_date("2026-06-24") == date(2026, 6, 24)


def test_normalize_money_handles_none_and_rounding():
    assert normalize_money(None) == Decimal("0.00")
    assert normalize_money(Decimal("10")) == Decimal("10.00")
    assert normalize_money(Decimal("10.555")) == Decimal("10.56")


def test_calculate_total_revenue_returns_zero_when_no_paid_orders():
    assert calculate_total_revenue(date(2026, 6, 24)) == Decimal("0.00")
    assert calculate_total_orders(date(2026, 6, 24)) == 0


def test_paid_orders_queryset_counts_only_paid_orders_for_snapshot_day():
    target_date = date(2026, 6, 24)

    paid_order, _, _, _ = create_order_with_product(
        snapshot_date=target_date,
        base_price=Decimal("100.00"),
        quantity=1,
        paid=True,
    )

    create_order_with_product(
        snapshot_date=target_date + timedelta(days=1),
        base_price=Decimal("200.00"),
        quantity=1,
        paid=True,
    )

    create_order_with_product(
        snapshot_date=target_date,
        base_price=Decimal("300.00"),
        quantity=1,
        paid=False,
    )

    queryset = get_paid_orders_queryset(target_date)

    assert list(queryset) == [paid_order]


def test_calculate_total_revenue_and_total_orders_for_paid_orders():
    target_date = date(2026, 6, 24)

    create_order_with_product(
        snapshot_date=target_date,
        base_price=Decimal("100.00"),
        quantity=2,
        paid=True,
    )
    create_order_with_product(
        snapshot_date=target_date,
        base_price=Decimal("50.00"),
        quantity=1,
        paid=True,
    )

    assert calculate_total_revenue(target_date) == Decimal("250.00")
    assert calculate_total_orders(target_date) == 2


def test_calculate_new_customers_counts_customers_created_on_snapshot_day():
    target_date = date(2026, 1, 15)
    target_datetime = make_day_datetime(target_date)
    other_datetime = make_day_datetime(target_date + timedelta(days=1))

    first_customer = CustomerUserFactory()
    second_customer = CustomerUserFactory()
    other_customer = CustomerUserFactory()

    User = get_user_model()

    User.objects.filter(pk=first_customer.pk).update(created_at=target_datetime)
    User.objects.filter(pk=second_customer.pk).update(created_at=target_datetime)
    User.objects.filter(pk=other_customer.pk).update(created_at=other_datetime)

    assert calculate_new_customers(target_date) == 2


def test_get_top_vendor_returns_vendor_with_highest_revenue():
    target_date = date(2026, 6, 24)

    low_vendor = ApprovedVendorFactory()
    high_vendor = ApprovedVendorFactory()

    create_order_with_product(
        vendor=low_vendor,
        snapshot_date=target_date,
        base_price=Decimal("50.00"),
        quantity=1,
        paid=True,
    )
    create_order_with_product(
        vendor=high_vendor,
        snapshot_date=target_date,
        base_price=Decimal("100.00"),
        quantity=3,
        paid=True,
    )

    assert get_top_vendor(target_date) == high_vendor


def test_get_top_product_returns_product_with_highest_revenue():
    target_date = date(2026, 6, 24)

    vendor = ApprovedVendorFactory()

    low_product = create_active_product_with_inventory(
        vendor=vendor,
        base_price=Decimal("20.00"),
    )
    high_product = create_active_product_with_inventory(
        vendor=vendor,
        base_price=Decimal("90.00"),
    )

    create_order_with_product(
        product=low_product,
        snapshot_date=target_date,
        quantity=2,
        paid=True,
    )
    create_order_with_product(
        product=high_product,
        snapshot_date=target_date,
        quantity=3,
        paid=True,
    )

    assert get_top_product(target_date) == high_product


def test_build_daily_snapshot_metrics_returns_all_metrics():
    target_date = date(2026, 6, 24)

    vendor = ApprovedVendorFactory()
    product = create_active_product_with_inventory(
        vendor=vendor,
        base_price=Decimal("75.00"),
    )

    customer = CustomerUserFactory()
    User = get_user_model()
    User.objects.filter(pk=customer.pk).update(
        created_at=make_day_datetime(target_date)
    )

    create_order_with_product(
        customer=customer,
        product=product,
        snapshot_date=target_date,
        quantity=2,
        paid=True,
    )

    metrics = build_daily_snapshot_metrics(target_date)

    assert metrics["date"] == target_date
    assert metrics["total_revenue"] == Decimal("150.00")
    assert metrics["total_orders"] == 1
    assert metrics["new_customers"] == 1
    assert metrics["top_vendor"] == vendor
    assert metrics["top_product"] == product


def test_compute_daily_analytics_snapshot_creates_snapshot_and_cache():
    target_date = date(2026, 6, 24)

    create_order_with_product(
        snapshot_date=target_date,
        base_price=Decimal("120.00"),
        quantity=1,
        paid=True,
    )

    snapshot = compute_daily_analytics_snapshot(target_date)

    assert snapshot.date == target_date
    assert snapshot.total_revenue == Decimal("120.00")
    assert snapshot.total_orders == 1

    assert AnalyticsSnapshot.objects.filter(date=target_date).count() == 1

    cached_snapshot = get_analytics_snapshot_for_date(target_date)

    assert cached_snapshot["id"] == str(snapshot.id)
    assert cached_snapshot["total_revenue"] == "120.00"
    assert cached_snapshot["total_orders"] == 1


def test_compute_daily_analytics_snapshot_updates_existing_snapshot():
    target_date = date(2026, 6, 24)

    existing_snapshot = AnalyticsSnapshot.objects.create(
        date=target_date,
        total_revenue=Decimal("0.00"),
        total_orders=0,
        new_customers=0,
    )

    create_order_with_product(
        snapshot_date=target_date,
        base_price=Decimal("80.00"),
        quantity=2,
        paid=True,
    )

    snapshot = compute_daily_analytics_snapshot(target_date)

    assert snapshot.id == existing_snapshot.id
    assert snapshot.total_revenue == Decimal("160.00")
    assert snapshot.total_orders == 1


def test_get_analytics_snapshot_for_date_returns_cached_snapshot():
    target_date = date(2026, 6, 24)

    cached_payload = {
        "id": "cached-id",
        "date": "2026-06-24",
        "total_revenue": "99.99",
        "total_orders": 3,
        "new_customers": 2,
        "top_vendor_id": None,
        "top_product_id": None,
    }

    from core.services.cache_service import set_analytics_snapshot_cache

    set_analytics_snapshot_cache(target_date, cached_payload)

    assert get_analytics_snapshot_for_date(target_date) == cached_payload


def test_get_analytics_snapshot_for_date_serializes_database_snapshot():
    target_date = date(2026, 6, 24)

    snapshot = AnalyticsSnapshot.objects.create(
        date=target_date,
        total_revenue=Decimal("250.75"),
        total_orders=5,
        new_customers=2,
    )

    serialized_snapshot = get_analytics_snapshot_for_date(target_date)

    assert serialized_snapshot["id"] == str(snapshot.id)
    assert serialized_snapshot["date"] == "2026-06-24"
    assert serialized_snapshot["total_revenue"] == "250.75"
    assert serialized_snapshot["total_orders"] == 5
    assert serialized_snapshot["new_customers"] == 2


def test_get_vendor_dashboard_metrics_returns_vendor_revenue_orders_and_items():
    target_date = date(2026, 6, 24)

    vendor = ApprovedVendorFactory()
    other_vendor = ApprovedVendorFactory()

    create_order_with_product(
        vendor=vendor,
        snapshot_date=target_date,
        base_price=Decimal("50.00"),
        quantity=2,
        paid=True,
    )
    create_order_with_product(
        vendor=vendor,
        snapshot_date=target_date,
        base_price=Decimal("25.00"),
        quantity=4,
        paid=True,
    )
    create_order_with_product(
        vendor=other_vendor,
        snapshot_date=target_date,
        base_price=Decimal("500.00"),
        quantity=1,
        paid=True,
    )

    metrics = get_vendor_dashboard_metrics(
        vendor=vendor,
        start_date=target_date,
        end_date=target_date,
    )

    assert metrics["vendor_id"] == str(vendor.id)
    assert metrics["total_revenue"] == Decimal("200.00")
    assert metrics["total_orders"] == 2
    assert metrics["total_items_sold"] == 6


def test_compute_daily_analytics_snapshot_task_returns_serialized_snapshot():
    target_date = date(2026, 6, 24)

    create_order_with_product(
        snapshot_date=target_date,
        base_price=Decimal("33.33"),
        quantity=3,
        paid=True,
    )

    result = compute_daily_analytics_snapshot_task(
        snapshot_date=target_date.isoformat(),
    )

    assert result["date"] == "2026-06-24"
    assert result["total_revenue"] == "99.99"
    assert result["total_orders"] == 1
    assert result["id"] is not None