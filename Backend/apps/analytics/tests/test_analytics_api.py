from datetime import date, datetime, time
from decimal import Decimal

import pytest
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.tests.factories import (
    AdminUserFactory,
    CustomerUserFactory,
)
from apps.analytics.models import AnalyticsSnapshot
from apps.cart.tests.factories import CartFactory, CartItemFactory
from apps.catalog.models import Product
from apps.catalog.tests.factories import ApprovedVendorFactory, ProductFactory
from apps.inventory.tests.factories import InventoryRecordFactory
from apps.orders.models import Order, OrderItem


pytestmark = pytest.mark.django_db


ADMIN_SNAPSHOTS_URL = "/api/v1/analytics/admin/snapshots/"
ADMIN_COMPUTE_URL = "/api/v1/analytics/admin/snapshots/compute/"
VENDOR_DASHBOARD_URL = "/api/v1/analytics/vendor/dashboard/"


@pytest.fixture
def api_client():
    return APIClient()


def authenticate(api_client, user):
    api_client.force_authenticate(user=user)
    return api_client


def extract_results(response):
    if isinstance(response.data, dict) and "results" in response.data:
        return response.data["results"]

    return response.data


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


def test_admin_can_list_analytics_snapshots_ordered_newest_first(api_client):
    admin_user = AdminUserFactory()
    authenticate(api_client, admin_user)

    older_snapshot = AnalyticsSnapshot.objects.create(
        date=date(2026, 6, 23),
        total_revenue=Decimal("100.00"),
        total_orders=1,
        new_customers=1,
    )
    newer_snapshot = AnalyticsSnapshot.objects.create(
        date=date(2026, 6, 24),
        total_revenue=Decimal("200.00"),
        total_orders=2,
        new_customers=2,
    )

    response = api_client.get(ADMIN_SNAPSHOTS_URL)

    assert response.status_code == status.HTTP_200_OK

    results = extract_results(response)

    assert results[0]["id"] == str(newer_snapshot.id)
    assert results[1]["id"] == str(older_snapshot.id)


def test_admin_can_filter_snapshots_by_exact_date(api_client):
    admin_user = AdminUserFactory()
    authenticate(api_client, admin_user)

    matching_snapshot = AnalyticsSnapshot.objects.create(
        date=date(2026, 6, 24),
        total_revenue=Decimal("100.00"),
        total_orders=1,
        new_customers=1,
    )
    AnalyticsSnapshot.objects.create(
        date=date(2026, 6, 25),
        total_revenue=Decimal("200.00"),
        total_orders=2,
        new_customers=2,
    )

    response = api_client.get(
        ADMIN_SNAPSHOTS_URL,
        {"date": "2026-06-24"},
    )

    assert response.status_code == status.HTTP_200_OK

    results = extract_results(response)

    assert len(results) == 1
    assert results[0]["id"] == str(matching_snapshot.id)


def test_admin_can_filter_snapshots_by_date_range(api_client):
    admin_user = AdminUserFactory()
    authenticate(api_client, admin_user)

    AnalyticsSnapshot.objects.create(
        date=date(2026, 6, 20),
        total_revenue=Decimal("100.00"),
        total_orders=1,
        new_customers=1,
    )
    matching_snapshot = AnalyticsSnapshot.objects.create(
        date=date(2026, 6, 24),
        total_revenue=Decimal("200.00"),
        total_orders=2,
        new_customers=2,
    )
    AnalyticsSnapshot.objects.create(
        date=date(2026, 6, 30),
        total_revenue=Decimal("300.00"),
        total_orders=3,
        new_customers=3,
    )

    response = api_client.get(
        ADMIN_SNAPSHOTS_URL,
        {
            "start_date": "2026-06-23",
            "end_date": "2026-06-25",
        },
    )

    assert response.status_code == status.HTTP_200_OK

    results = extract_results(response)

    assert len(results) == 1
    assert results[0]["id"] == str(matching_snapshot.id)


def test_admin_can_filter_snapshots_by_top_vendor(api_client):
    admin_user = AdminUserFactory()
    authenticate(api_client, admin_user)

    matching_vendor = ApprovedVendorFactory()
    other_vendor = ApprovedVendorFactory()

    matching_snapshot = AnalyticsSnapshot.objects.create(
        date=date(2026, 6, 24),
        total_revenue=Decimal("100.00"),
        total_orders=1,
        new_customers=1,
        top_vendor=matching_vendor,
    )
    AnalyticsSnapshot.objects.create(
        date=date(2026, 6, 25),
        total_revenue=Decimal("200.00"),
        total_orders=2,
        new_customers=2,
        top_vendor=other_vendor,
    )

    response = api_client.get(
        ADMIN_SNAPSHOTS_URL,
        {"top_vendor_id": str(matching_vendor.id)},
    )

    assert response.status_code == status.HTTP_200_OK

    results = extract_results(response)

    assert len(results) == 1
    assert results[0]["id"] == str(matching_snapshot.id)


def test_admin_can_filter_snapshots_by_top_product(api_client):
    admin_user = AdminUserFactory()
    authenticate(api_client, admin_user)

    matching_product = ProductFactory()
    other_product = ProductFactory()

    matching_snapshot = AnalyticsSnapshot.objects.create(
        date=date(2026, 6, 24),
        total_revenue=Decimal("100.00"),
        total_orders=1,
        new_customers=1,
        top_product=matching_product,
    )
    AnalyticsSnapshot.objects.create(
        date=date(2026, 6, 25),
        total_revenue=Decimal("200.00"),
        total_orders=2,
        new_customers=2,
        top_product=other_product,
    )

    response = api_client.get(
        ADMIN_SNAPSHOTS_URL,
        {"top_product_id": str(matching_product.id)},
    )

    assert response.status_code == status.HTTP_200_OK

    results = extract_results(response)

    assert len(results) == 1
    assert results[0]["id"] == str(matching_snapshot.id)


def test_admin_can_retrieve_snapshot_detail(api_client):
    admin_user = AdminUserFactory()
    authenticate(api_client, admin_user)

    vendor = ApprovedVendorFactory()
    product = ProductFactory(vendor=vendor)

    snapshot = AnalyticsSnapshot.objects.create(
        date=date(2026, 6, 24),
        total_revenue=Decimal("500.00"),
        total_orders=5,
        new_customers=2,
        top_vendor=vendor,
        top_product=product,
    )

    response = api_client.get(f"{ADMIN_SNAPSHOTS_URL}{snapshot.id}/")

    assert response.status_code == status.HTTP_200_OK
    assert response.data["id"] == str(snapshot.id)
    assert response.data["date"] == "2026-06-24"
    assert Decimal(str(response.data["total_revenue"])) == Decimal("500.00")
    assert response.data["total_orders"] == 5
    assert response.data["new_customers"] == 2
    assert response.data["top_vendor_id"] == str(vendor.id)
    assert response.data["top_product_id"] == str(product.id)


def test_admin_snapshot_list_rejects_invalid_date_range(api_client):
    admin_user = AdminUserFactory()
    authenticate(api_client, admin_user)

    response = api_client.get(
        ADMIN_SNAPSHOTS_URL,
        {
            "start_date": "2026-06-25",
            "end_date": "2026-06-24",
        },
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST


def test_admin_compute_creates_daily_snapshot(api_client):
    admin_user = AdminUserFactory()
    authenticate(api_client, admin_user)

    target_date = date(2026, 6, 24)

    create_order_with_product(
        snapshot_date=target_date,
        base_price=Decimal("120.00"),
        quantity=2,
        paid=True,
    )

    response = api_client.post(
        ADMIN_COMPUTE_URL,
        {"date": target_date.isoformat()},
        format="json",
    )

    assert response.status_code == status.HTTP_201_CREATED
    assert response.data["date"] == "2026-06-24"
    assert Decimal(str(response.data["total_revenue"])) == Decimal("240.00")
    assert response.data["total_orders"] == 1

    assert AnalyticsSnapshot.objects.filter(date=target_date).count() == 1


def test_admin_compute_updates_existing_daily_snapshot(api_client):
    admin_user = AdminUserFactory()
    authenticate(api_client, admin_user)

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
        quantity=3,
        paid=True,
    )

    response = api_client.post(
        ADMIN_COMPUTE_URL,
        {"date": target_date.isoformat()},
        format="json",
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.data["id"] == str(existing_snapshot.id)
    assert Decimal(str(response.data["total_revenue"])) == Decimal("240.00")
    assert response.data["total_orders"] == 1

    assert AnalyticsSnapshot.objects.filter(date=target_date).count() == 1


def test_admin_compute_rejects_invalid_date(api_client):
    admin_user = AdminUserFactory()
    authenticate(api_client, admin_user)

    response = api_client.post(
        ADMIN_COMPUTE_URL,
        {"date": "invalid-date"},
        format="json",
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST


def test_unauthenticated_user_cannot_access_admin_snapshots(api_client):
    response = api_client.get(ADMIN_SNAPSHOTS_URL)

    assert response.status_code in [
        status.HTTP_401_UNAUTHORIZED,
        status.HTTP_403_FORBIDDEN,
    ]


def test_non_admin_user_cannot_access_admin_snapshots(api_client):
    customer_user = CustomerUserFactory()
    authenticate(api_client, customer_user)

    response = api_client.get(ADMIN_SNAPSHOTS_URL)

    assert response.status_code == status.HTTP_403_FORBIDDEN


def test_vendor_can_view_dashboard_metrics(api_client):
    target_date = date(2026, 6, 24)

    vendor = ApprovedVendorFactory()
    authenticate(api_client, vendor.user)

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

    response = api_client.get(
        VENDOR_DASHBOARD_URL,
        {
            "start_date": target_date.isoformat(),
            "end_date": target_date.isoformat(),
        },
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.data["vendor_id"] == str(vendor.id)
    assert Decimal(str(response.data["total_revenue"])) == Decimal("200.00")
    assert response.data["total_orders"] == 2
    assert response.data["total_items_sold"] == 6


def test_vendor_dashboard_counts_only_authenticated_vendor(api_client):
    target_date = date(2026, 6, 24)

    vendor = ApprovedVendorFactory()
    other_vendor = ApprovedVendorFactory()

    authenticate(api_client, vendor.user)

    create_order_with_product(
        vendor=vendor,
        snapshot_date=target_date,
        base_price=Decimal("40.00"),
        quantity=2,
        paid=True,
    )
    create_order_with_product(
        vendor=other_vendor,
        snapshot_date=target_date,
        base_price=Decimal("500.00"),
        quantity=1,
        paid=True,
    )

    response = api_client.get(
        VENDOR_DASHBOARD_URL,
        {
            "start_date": target_date.isoformat(),
            "end_date": target_date.isoformat(),
        },
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.data["vendor_id"] == str(vendor.id)
    assert Decimal(str(response.data["total_revenue"])) == Decimal("80.00")
    assert response.data["total_orders"] == 1
    assert response.data["total_items_sold"] == 2


def test_vendor_dashboard_returns_zero_metrics_when_vendor_has_no_orders(api_client):
    target_date = date(2026, 6, 24)

    vendor = ApprovedVendorFactory()
    authenticate(api_client, vendor.user)

    response = api_client.get(
        VENDOR_DASHBOARD_URL,
        {
            "start_date": target_date.isoformat(),
            "end_date": target_date.isoformat(),
        },
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.data["vendor_id"] == str(vendor.id)
    assert Decimal(str(response.data["total_revenue"])) == Decimal("0.00")
    assert response.data["total_orders"] == 0
    assert response.data["total_items_sold"] == 0


def test_vendor_dashboard_rejects_invalid_date_range(api_client):
    vendor = ApprovedVendorFactory()
    authenticate(api_client, vendor.user)

    response = api_client.get(
        VENDOR_DASHBOARD_URL,
        {
            "start_date": "2026-06-25",
            "end_date": "2026-06-24",
        },
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST


def test_customer_cannot_access_vendor_dashboard(api_client):
    customer_user = CustomerUserFactory()
    authenticate(api_client, customer_user)

    response = api_client.get(VENDOR_DASHBOARD_URL)

    assert response.status_code == status.HTTP_403_FORBIDDEN


def test_admin_cannot_access_vendor_dashboard_without_vendor_role(api_client):
    admin_user = AdminUserFactory()
    authenticate(api_client, admin_user)

    response = api_client.get(VENDOR_DASHBOARD_URL)

    assert response.status_code == status.HTTP_403_FORBIDDEN


def test_unauthenticated_user_cannot_access_vendor_dashboard(api_client):
    response = api_client.get(VENDOR_DASHBOARD_URL)

    assert response.status_code in [
        status.HTTP_401_UNAUTHORIZED,
        status.HTTP_403_FORBIDDEN,
    ]