from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.utils import timezone

from apps.accounts.tests.factories import CustomerUserFactory
from apps.cart.tests.factories import CartFactory, CartItemFactory
from apps.catalog.models import Product
from apps.catalog.tests.factories import (
    ApprovedVendorFactory,
    CategoryFactory,
    ProductFactory,
)
from apps.coupons.models import Coupon, CouponUsage
from apps.coupons.tests.factories import CouponFactory
from apps.inventory.tests.factories import InventoryRecordFactory
from apps.orders.models import Order


pytestmark = pytest.mark.django_db


def create_active_product_with_inventory(
    *,
    vendor=None,
    category=None,
    name="Coupon Test Product",
    base_price=Decimal("50.00"),
    quantity_on_hand=100,
    quantity_reserved=0,
    track_inventory=True,
    allow_backorder=False,
    **overrides,
):
    product = ProductFactory(
        vendor=vendor or ApprovedVendorFactory(),
        category=category or CategoryFactory(),
        name=name,
        base_price=base_price,
        status=Product.Status.ACTIVE,
        **overrides,
    )

    inventory_record = InventoryRecordFactory(
        product=product,
        variant=None,
        quantity_on_hand=quantity_on_hand,
        quantity_reserved=quantity_reserved,
        track_inventory=track_inventory,
        allow_backorder=allow_backorder,
    )

    return product, inventory_record


def create_order_from_cart(
    *,
    customer=None,
    vendor=None,
    category=None,
    product_name="Coupon Test Product",
    base_price=Decimal("50.00"),
    quantity=2,
    quantity_on_hand=100,
):
    customer = customer or CustomerUserFactory()
    cart = CartFactory(customer=customer)

    product, inventory_record = create_active_product_with_inventory(
        vendor=vendor,
        category=category,
        name=product_name,
        base_price=base_price,
        quantity_on_hand=quantity_on_hand,
    )

    CartItemFactory(
        cart=cart,
        product=product,
        quantity=quantity,
    )

    order = Order.create_from_cart(cart)

    order.refresh_from_db()
    inventory_record.refresh_from_db()

    return order, product, inventory_record, cart


def test_coupon_factory_creates_valid_global_coupon():
    coupon = CouponFactory()

    assert coupon.id is not None
    assert coupon.code.startswith("COUPON")
    assert coupon.type == Coupon.Type.FIXED
    assert coupon.scope == Coupon.Scope.GLOBAL
    assert coupon.vendor is None
    assert coupon.category is None
    assert coupon.value == Decimal("10.00")
    assert coupon.per_user_limit == 1
    assert coupon.is_active is True


def test_coupon_code_is_normalized_on_save():
    coupon = CouponFactory(code="  summer10  ")

    assert coupon.code == "SUMMER10"


def test_coupon_code_is_case_insensitive_unique():
    CouponFactory(code="summer10")

    with pytest.raises((ValidationError, IntegrityError)):
        CouponFactory(code="SUMMER10")


def test_fixed_coupon_discount_caps_at_order_total():
    coupon = CouponFactory(
        type=Coupon.Type.FIXED,
        value=Decimal("100.00"),
    )

    discount = coupon.calculate_discount(Decimal("40.00"))

    assert discount == Decimal("40.00")


def test_percentage_coupon_discount_is_calculated_from_order_total():
    coupon = CouponFactory(
        type=Coupon.Type.PERCENTAGE,
        value=Decimal("10.00"),
    )

    discount = coupon.calculate_discount(Decimal("200.00"))

    assert discount == Decimal("20.00")


def test_percentage_coupon_uses_max_discount_cap():
    coupon = CouponFactory(
        type=Coupon.Type.PERCENTAGE,
        value=Decimal("50.00"),
        max_discount=Decimal("30.00"),
    )

    discount = coupon.calculate_discount(Decimal("200.00"))

    assert discount == Decimal("30.00")


def test_zero_order_total_discount_is_zero():
    coupon = CouponFactory(
        type=Coupon.Type.FIXED,
        value=Decimal("10.00"),
    )

    discount = coupon.calculate_discount(Decimal("0.00"))

    assert discount == Decimal("0.00")


def test_is_currently_valid_returns_true_for_active_coupon_in_window():
    coupon = CouponFactory(
        is_active=True,
        valid_from=timezone.now() - timedelta(days=1),
        valid_until=timezone.now() + timedelta(days=1),
    )

    assert coupon.is_currently_valid() is True


def test_inactive_coupon_is_not_currently_valid():
    coupon = CouponFactory(is_active=False)

    assert coupon.is_currently_valid() is False


def test_validate_for_order_rejects_inactive_coupon():
    customer = CustomerUserFactory()
    coupon = CouponFactory(is_active=False)

    with pytest.raises(ValidationError):
        coupon.validate_for_order(
            user=customer,
            order_total=Decimal("100.00"),
        )


def test_validate_for_order_rejects_coupon_before_valid_from():
    customer = CustomerUserFactory()

    coupon = CouponFactory(
        valid_from=timezone.now() + timedelta(days=1),
        valid_until=timezone.now() + timedelta(days=10),
    )

    with pytest.raises(ValidationError):
        coupon.validate_for_order(
            user=customer,
            order_total=Decimal("100.00"),
        )


def test_validate_for_order_rejects_coupon_after_valid_until():
    customer = CustomerUserFactory()

    coupon = CouponFactory(
        valid_from=timezone.now() - timedelta(days=10),
        valid_until=timezone.now() - timedelta(days=1),
    )

    with pytest.raises(ValidationError):
        coupon.validate_for_order(
            user=customer,
            order_total=Decimal("100.00"),
        )


def test_validate_for_order_rejects_min_order_not_met():
    customer = CustomerUserFactory()

    coupon = CouponFactory(
        min_order_value=Decimal("200.00"),
    )

    with pytest.raises(ValidationError):
        coupon.validate_for_order(
            user=customer,
            order_total=Decimal("100.00"),
        )


def test_validate_for_order_rejects_usage_limit_reached():
    customer = CustomerUserFactory()
    order, _, _, _ = create_order_from_cart(customer=customer)

    coupon = CouponFactory(
        usage_limit=1,
        per_user_limit=10,
    )

    CouponUsage.objects.create(
        coupon=coupon,
        user=customer,
        order=order,
    )

    another_customer = CustomerUserFactory()

    with pytest.raises(ValidationError):
        coupon.validate_for_order(
            user=another_customer,
            order_total=Decimal("100.00"),
        )


def test_validate_for_order_rejects_per_user_limit_reached():
    customer = CustomerUserFactory()
    order, _, _, _ = create_order_from_cart(customer=customer)

    coupon = CouponFactory(
        usage_limit=None,
        per_user_limit=1,
    )

    CouponUsage.objects.create(
        coupon=coupon,
        user=customer,
        order=order,
    )

    with pytest.raises(ValidationError):
        coupon.validate_for_order(
            user=customer,
            order_total=Decimal("100.00"),
        )


def test_global_coupon_rejects_vendor_scope_field():
    vendor = ApprovedVendorFactory()

    coupon = CouponFactory.build(
        scope=Coupon.Scope.GLOBAL,
        vendor=vendor,
    )

    with pytest.raises(ValidationError):
        coupon.full_clean()


def test_global_coupon_rejects_category_scope_field():
    category = CategoryFactory()

    coupon = CouponFactory.build(
        scope=Coupon.Scope.GLOBAL,
        category=category,
    )

    with pytest.raises(ValidationError):
        coupon.full_clean()


def test_vendor_coupon_requires_vendor():
    coupon = CouponFactory.build(
        scope=Coupon.Scope.VENDOR,
        vendor=None,
    )

    with pytest.raises(ValidationError):
        coupon.full_clean()


def test_vendor_coupon_rejects_category():
    vendor = ApprovedVendorFactory()
    category = CategoryFactory()

    coupon = CouponFactory.build(
        scope=Coupon.Scope.VENDOR,
        vendor=vendor,
        category=category,
    )

    with pytest.raises(ValidationError):
        coupon.full_clean()


def test_vendor_coupon_accepts_matching_vendor():
    customer = CustomerUserFactory()
    vendor = ApprovedVendorFactory()

    coupon = CouponFactory(
        scope=Coupon.Scope.VENDOR,
        vendor=vendor,
    )

    result = coupon.validate_for_order(
        user=customer,
        order_total=Decimal("100.00"),
        vendor=vendor,
    )

    assert result is True


def test_vendor_coupon_rejects_non_matching_vendor():
    customer = CustomerUserFactory()
    vendor = ApprovedVendorFactory()
    other_vendor = ApprovedVendorFactory()

    coupon = CouponFactory(
        scope=Coupon.Scope.VENDOR,
        vendor=vendor,
    )

    with pytest.raises(ValidationError):
        coupon.validate_for_order(
            user=customer,
            order_total=Decimal("100.00"),
            vendor=other_vendor,
        )


def test_category_coupon_requires_category():
    coupon = CouponFactory.build(
        scope=Coupon.Scope.CATEGORY,
        category=None,
    )

    with pytest.raises(ValidationError):
        coupon.full_clean()


def test_category_coupon_rejects_vendor():
    vendor = ApprovedVendorFactory()
    category = CategoryFactory()

    coupon = CouponFactory.build(
        scope=Coupon.Scope.CATEGORY,
        vendor=vendor,
        category=category,
    )

    with pytest.raises(ValidationError):
        coupon.full_clean()


def test_category_coupon_accepts_matching_category():
    customer = CustomerUserFactory()
    category = CategoryFactory()

    coupon = CouponFactory(
        scope=Coupon.Scope.CATEGORY,
        category=category,
    )

    result = coupon.validate_for_order(
        user=customer,
        order_total=Decimal("100.00"),
        category=category,
    )

    assert result is True


def test_category_coupon_rejects_non_matching_category():
    customer = CustomerUserFactory()
    category = CategoryFactory()
    other_category = CategoryFactory()

    coupon = CouponFactory(
        scope=Coupon.Scope.CATEGORY,
        category=category,
    )

    with pytest.raises(ValidationError):
        coupon.validate_for_order(
            user=customer,
            order_total=Decimal("100.00"),
            category=other_category,
        )


def test_coupon_value_must_be_positive():
    coupon = CouponFactory.build(
        value=Decimal("0.00"),
    )

    with pytest.raises(ValidationError):
        coupon.full_clean()


def test_coupon_max_discount_must_be_positive_when_present():
    coupon = CouponFactory.build(
        type=Coupon.Type.PERCENTAGE,
        value=Decimal("10.00"),
        max_discount=Decimal("0.00"),
    )

    with pytest.raises(ValidationError):
        coupon.full_clean()


def test_coupon_min_order_value_cannot_be_negative():
    coupon = CouponFactory.build(
        min_order_value=Decimal("-1.00"),
    )

    with pytest.raises(ValidationError):
        coupon.full_clean()


def test_coupon_usage_limit_must_be_positive_when_present():
    coupon = CouponFactory.build(
        usage_limit=0,
    )

    with pytest.raises(ValidationError):
        coupon.full_clean()


def test_coupon_per_user_limit_must_be_positive():
    coupon = CouponFactory.build(
        per_user_limit=0,
    )

    with pytest.raises(ValidationError):
        coupon.full_clean()


def test_coupon_valid_until_must_be_after_valid_from():
    now = timezone.now()

    coupon = CouponFactory.build(
        valid_from=now,
        valid_until=now,
    )

    with pytest.raises(ValidationError):
        coupon.full_clean()


def test_record_usage_creates_coupon_usage_for_order_customer():
    customer = CustomerUserFactory()
    order, _, _, _ = create_order_from_cart(customer=customer)

    coupon = CouponFactory(
        usage_limit=10,
        per_user_limit=2,
    )

    usage = coupon.record_usage(
        user=customer,
        order=order,
    )

    assert usage.id is not None
    assert usage.coupon == coupon
    assert usage.user == customer
    assert usage.order == order

    assert CouponUsage.objects.filter(
        coupon=coupon,
        user=customer,
        order=order,
    ).exists()


def test_record_usage_rejects_user_that_is_not_order_customer():
    customer = CustomerUserFactory()
    other_customer = CustomerUserFactory()

    order, _, _, _ = create_order_from_cart(customer=customer)

    coupon = CouponFactory()

    with pytest.raises(ValidationError):
        coupon.record_usage(
            user=other_customer,
            order=order,
        )


def test_coupon_usage_direct_save_rejects_user_that_is_not_order_customer():
    customer = CustomerUserFactory()
    other_customer = CustomerUserFactory()

    order, _, _, _ = create_order_from_cart(customer=customer)

    coupon = CouponFactory()

    usage = CouponUsage(
        coupon=coupon,
        user=other_customer,
        order=order,
    )

    with pytest.raises(ValidationError):
        usage.full_clean()


def test_usage_count_and_user_usage_count_return_correct_values():
    customer = CustomerUserFactory()
    order, _, _, _ = create_order_from_cart(customer=customer)

    other_customer = CustomerUserFactory()
    other_order, _, _, _ = create_order_from_cart(customer=other_customer)

    coupon = CouponFactory(
        usage_limit=10,
        per_user_limit=10,
    )

    CouponUsage.objects.create(
        coupon=coupon,
        user=customer,
        order=order,
    )
    CouponUsage.objects.create(
        coupon=coupon,
        user=other_customer,
        order=other_order,
    )

    assert coupon.usage_count == 2
    assert coupon.user_usage_count(customer) == 1
    assert coupon.user_usage_count(other_customer) == 1