from datetime import date
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.analytics.models import AnalyticsSnapshot
from apps.analytics.tests.factories import AnalyticsSnapshotFactory
from apps.catalog.tests.factories import ApprovedVendorFactory, ProductFactory


pytestmark = pytest.mark.django_db


def test_analytics_snapshot_factory_creates_valid_snapshot():
    snapshot = AnalyticsSnapshotFactory(
        date=date(2026, 6, 24),
        total_revenue=Decimal("1500.50"),
        total_orders=12,
        new_customers=5,
    )

    assert snapshot.id is not None
    assert snapshot.date == date(2026, 6, 24)
    assert snapshot.total_revenue == Decimal("1500.50")
    assert snapshot.total_orders == 12
    assert snapshot.new_customers == 5
    assert snapshot.top_vendor is None
    assert snapshot.top_product is None


def test_analytics_snapshot_can_be_created_with_default_metrics():
    snapshot = AnalyticsSnapshot.objects.create(
        date=date(2026, 6, 24),
    )

    assert snapshot.total_revenue == Decimal("0.00")
    assert snapshot.total_orders == 0
    assert snapshot.new_customers == 0
    assert snapshot.top_vendor is None
    assert snapshot.top_product is None


def test_analytics_snapshot_str_returns_snapshot_date():
    snapshot = AnalyticsSnapshotFactory(
        date=date(2026, 6, 24),
    )

    assert str(snapshot) == "Analytics Snapshot - 2026-06-24"


def test_analytics_snapshot_accepts_top_vendor():
    vendor = ApprovedVendorFactory()

    snapshot = AnalyticsSnapshotFactory(
        date=date(2026, 6, 24),
        top_vendor=vendor,
    )

    assert snapshot.top_vendor == vendor


def test_analytics_snapshot_accepts_top_product():
    product = ProductFactory()

    snapshot = AnalyticsSnapshotFactory(
        date=date(2026, 6, 24),
        top_product=product,
    )

    assert snapshot.top_product == product


def test_analytics_snapshot_accepts_top_vendor_and_top_product_together():
    vendor = ApprovedVendorFactory()
    product = ProductFactory(vendor=vendor)

    snapshot = AnalyticsSnapshotFactory(
        date=date(2026, 6, 24),
        top_vendor=vendor,
        top_product=product,
        total_revenue=Decimal("999.99"),
        total_orders=7,
        new_customers=3,
    )

    assert snapshot.top_vendor == vendor
    assert snapshot.top_product == product
    assert snapshot.total_revenue == Decimal("999.99")
    assert snapshot.total_orders == 7
    assert snapshot.new_customers == 3


def test_total_revenue_cannot_be_negative_on_full_clean():
    snapshot = AnalyticsSnapshot(
        date=date(2026, 6, 24),
        total_revenue=Decimal("-0.01"),
        total_orders=0,
        new_customers=0,
    )

    with pytest.raises(ValidationError):
        snapshot.full_clean()


def test_total_orders_cannot_be_negative_on_full_clean():
    snapshot = AnalyticsSnapshot(
        date=date(2026, 6, 24),
        total_revenue=Decimal("0.00"),
        total_orders=-1,
        new_customers=0,
    )

    with pytest.raises(ValidationError):
        snapshot.full_clean()


def test_new_customers_cannot_be_negative_on_full_clean():
    snapshot = AnalyticsSnapshot(
        date=date(2026, 6, 24),
        total_revenue=Decimal("0.00"),
        total_orders=0,
        new_customers=-1,
    )

    with pytest.raises(ValidationError):
        snapshot.full_clean()


def test_save_runs_validation_for_negative_total_revenue():
    snapshot = AnalyticsSnapshot(
        date=date(2026, 6, 24),
        total_revenue=Decimal("-10.00"),
        total_orders=0,
        new_customers=0,
    )

    with pytest.raises(ValidationError):
        snapshot.save()


def test_save_runs_validation_for_negative_total_orders():
    snapshot = AnalyticsSnapshot(
        date=date(2026, 6, 24),
        total_revenue=Decimal("0.00"),
        total_orders=-5,
        new_customers=0,
    )

    with pytest.raises(ValidationError):
        snapshot.save()


def test_save_runs_validation_for_negative_new_customers():
    snapshot = AnalyticsSnapshot(
        date=date(2026, 6, 24),
        total_revenue=Decimal("0.00"),
        total_orders=0,
        new_customers=-2,
    )

    with pytest.raises(ValidationError):
        snapshot.save()


def test_existing_snapshot_cannot_be_updated_to_negative_revenue():
    snapshot = AnalyticsSnapshotFactory(
        date=date(2026, 6, 24),
        total_revenue=Decimal("100.00"),
    )

    snapshot.total_revenue = Decimal("-1.00")

    with pytest.raises(ValidationError):
        snapshot.save()


def test_existing_snapshot_cannot_be_updated_to_negative_orders():
    snapshot = AnalyticsSnapshotFactory(
        date=date(2026, 6, 24),
        total_orders=10,
    )

    snapshot.total_orders = -1

    with pytest.raises(ValidationError):
        snapshot.save()


def test_existing_snapshot_cannot_be_updated_to_negative_new_customers():
    snapshot = AnalyticsSnapshotFactory(
        date=date(2026, 6, 24),
        new_customers=10,
    )

    snapshot.new_customers = -1

    with pytest.raises(ValidationError):
        snapshot.save()


def test_analytics_snapshots_are_ordered_newest_first():
    older_snapshot = AnalyticsSnapshotFactory(
        date=date(2026, 6, 23),
    )
    newer_snapshot = AnalyticsSnapshotFactory(
        date=date(2026, 6, 24),
    )

    snapshots = list(AnalyticsSnapshot.objects.all()[:2])

    assert snapshots[0] == newer_snapshot
    assert snapshots[1] == older_snapshot


def test_multiple_snapshots_can_store_different_daily_metrics():
    first_snapshot = AnalyticsSnapshotFactory(
        date=date(2026, 6, 23),
        total_revenue=Decimal("100.00"),
        total_orders=2,
        new_customers=1,
    )
    second_snapshot = AnalyticsSnapshotFactory(
        date=date(2026, 6, 24),
        total_revenue=Decimal("250.75"),
        total_orders=5,
        new_customers=3,
    )

    first_snapshot.refresh_from_db()
    second_snapshot.refresh_from_db()

    assert first_snapshot.total_revenue == Decimal("100.00")
    assert first_snapshot.total_orders == 2
    assert first_snapshot.new_customers == 1

    assert second_snapshot.total_revenue == Decimal("250.75")
    assert second_snapshot.total_orders == 5
    assert second_snapshot.new_customers == 3