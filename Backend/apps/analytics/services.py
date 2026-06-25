from datetime import date, datetime, time, timedelta
from decimal import Decimal, ROUND_HALF_UP

from django.contrib.auth import get_user_model
from django.db.models import DecimalField, ExpressionWrapper, F, Sum
from django.utils import timezone

from apps.analytics.models import AnalyticsSnapshot
from apps.catalog.models import Product
from apps.orders.models import Order, OrderItem
from apps.vendors.models import Vendor
from core.services.cache_service import (
    get_analytics_snapshot_cache,
    set_analytics_snapshot_cache,
)


MONEY_ZERO = Decimal("0.00")


def normalize_money(value):
    if value is None:
        value = MONEY_ZERO

    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def resolve_snapshot_date(snapshot_date=None):
    if snapshot_date is None:
        return timezone.localdate()

    if isinstance(snapshot_date, datetime):
        return snapshot_date.date()

    if isinstance(snapshot_date, date):
        return snapshot_date

    return date.fromisoformat(str(snapshot_date))


def get_day_bounds(snapshot_date=None):
    snapshot_date = resolve_snapshot_date(snapshot_date)
    current_timezone = timezone.get_current_timezone()

    start_at = timezone.make_aware(
        datetime.combine(snapshot_date, time.min),
        current_timezone,
    )
    end_at = start_at + timedelta(days=1)

    return start_at, end_at


def get_order_date_filter(start_at, end_at):
    order_field_names = {
        field.name
        for field in Order._meta.get_fields()
    }

    if "paid_at" in order_field_names:
        return {
            "paid_at__gte": start_at,
            "paid_at__lt": end_at,
        }

    return {
        "created_at__gte": start_at,
        "created_at__lt": end_at,
    }


def get_paid_orders_queryset(snapshot_date=None):
    start_at, end_at = get_day_bounds(snapshot_date)

    queryset = Order.objects.all()

    payment_status_value = getattr(
        getattr(Order, "PaymentStatus", None),
        "PAID",
        "PAID",
    )

    order_field_names = {
        field.name
        for field in Order._meta.get_fields()
    }

    if "payment_status" in order_field_names:
        queryset = queryset.filter(payment_status=payment_status_value)
    elif "paid_at" in order_field_names:
        queryset = queryset.filter(paid_at__isnull=False)

    return queryset.filter(
        **get_order_date_filter(start_at, end_at)
    )


def calculate_total_revenue(snapshot_date=None):
    result = get_paid_orders_queryset(snapshot_date).aggregate(
        total_revenue=Sum("total_amount")
    )

    return normalize_money(result["total_revenue"])


def calculate_total_orders(snapshot_date=None):
    return get_paid_orders_queryset(snapshot_date).count()


def calculate_new_customers(snapshot_date=None):
    User = get_user_model()
    start_at, end_at = get_day_bounds(snapshot_date)

    queryset = User.objects.filter(
        created_at__gte=start_at,
        created_at__lt=end_at,
    )

    user_field_names = {
        field.name
        for field in User._meta.get_fields()
    }

    if "role" in user_field_names:
        queryset = queryset.filter(role="CUSTOMER")

    return queryset.count()


def get_paid_order_items_queryset(snapshot_date=None):
    paid_orders = get_paid_orders_queryset(snapshot_date)

    return OrderItem.objects.filter(
        order__in=paid_orders,
    ).select_related(
        "vendor",
        "product",
    )


def get_line_revenue_expression():
    return ExpressionWrapper(
        F("quantity") * F("unit_price"),
        output_field=DecimalField(max_digits=14, decimal_places=2),
    )


def get_top_vendor(snapshot_date=None):
    result = (
        get_paid_order_items_queryset(snapshot_date)
        .exclude(vendor__isnull=True)
        .values("vendor")
        .annotate(revenue=Sum(get_line_revenue_expression()))
        .order_by("-revenue")
        .first()
    )

    if not result:
        return None

    return Vendor.objects.filter(id=result["vendor"]).first()


def get_top_product(snapshot_date=None):
    result = (
        get_paid_order_items_queryset(snapshot_date)
        .exclude(product__isnull=True)
        .values("product")
        .annotate(revenue=Sum(get_line_revenue_expression()))
        .order_by("-revenue")
        .first()
    )

    if not result:
        return None

    return Product.objects.filter(id=result["product"]).first()


def build_daily_snapshot_metrics(snapshot_date=None):
    snapshot_date = resolve_snapshot_date(snapshot_date)

    return {
        "date": snapshot_date,
        "total_revenue": calculate_total_revenue(snapshot_date),
        "total_orders": calculate_total_orders(snapshot_date),
        "new_customers": calculate_new_customers(snapshot_date),
        "top_vendor": get_top_vendor(snapshot_date),
        "top_product": get_top_product(snapshot_date),
    }


def serialize_analytics_snapshot(snapshot):
    if snapshot is None:
        return None

    return {
        "id": str(snapshot.id),
        "date": snapshot.date.isoformat(),
        "total_revenue": str(normalize_money(snapshot.total_revenue)),
        "total_orders": snapshot.total_orders,
        "new_customers": snapshot.new_customers,
        "top_vendor_id": str(snapshot.top_vendor_id) if snapshot.top_vendor_id else None,
        "top_product_id": str(snapshot.top_product_id) if snapshot.top_product_id else None,
    }


def compute_daily_analytics_snapshot(snapshot_date=None):
    metrics = build_daily_snapshot_metrics(snapshot_date)
    snapshot_date = metrics.pop("date")

    snapshot = AnalyticsSnapshot.objects.filter(
        date=snapshot_date,
    ).order_by("-date").first()

    if snapshot is None:
        snapshot = AnalyticsSnapshot.objects.create(
            date=snapshot_date,
            **metrics,
        )
    else:
        for field_name, value in metrics.items():
            setattr(snapshot, field_name, value)

        snapshot.save()

    set_analytics_snapshot_cache(
        snapshot.date,
        serialize_analytics_snapshot(snapshot),
    )

    return snapshot


def get_analytics_snapshot_for_date(snapshot_date=None):
    snapshot_date = resolve_snapshot_date(snapshot_date)

    cached_snapshot = get_analytics_snapshot_cache(snapshot_date)

    if cached_snapshot is not None:
        return cached_snapshot

    snapshot = AnalyticsSnapshot.objects.filter(
        date=snapshot_date,
    ).select_related(
        "top_vendor",
        "top_product",
    ).first()

    serialized_snapshot = serialize_analytics_snapshot(snapshot)

    if serialized_snapshot is not None:
        set_analytics_snapshot_cache(snapshot_date, serialized_snapshot)

    return serialized_snapshot


def get_vendor_dashboard_metrics(
    *,
    vendor,
    start_date=None,
    end_date=None,
):
    vendor_id = getattr(vendor, "id", vendor)

    start_date = resolve_snapshot_date(start_date) if start_date else None
    end_date = resolve_snapshot_date(end_date) if end_date else None

    order_items = OrderItem.objects.filter(
        vendor_id=vendor_id,
    )

    if start_date:
        start_at, _ = get_day_bounds(start_date)
        order_items = order_items.filter(order__created_at__gte=start_at)

    if end_date:
        _, end_at = get_day_bounds(end_date)
        order_items = order_items.filter(order__created_at__lt=end_at)

    paid_payment_status = getattr(
        getattr(Order, "PaymentStatus", None),
        "PAID",
        "PAID",
    )

    order_field_names = {
        field.name
        for field in Order._meta.get_fields()
    }

    if "payment_status" in order_field_names:
        order_items = order_items.filter(order__payment_status=paid_payment_status)

    revenue_result = order_items.aggregate(
        total_revenue=Sum(get_line_revenue_expression())
    )

    total_orders = order_items.values("order_id").distinct().count()
    total_items_sold = order_items.aggregate(
        total_items=Sum("quantity")
    )["total_items"] or 0

    return {
        "vendor_id": str(vendor_id),
        "total_revenue": normalize_money(revenue_result["total_revenue"]),
        "total_orders": total_orders,
        "total_items_sold": total_items_sold,
    }