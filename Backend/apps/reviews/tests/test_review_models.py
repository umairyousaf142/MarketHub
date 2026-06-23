from decimal import Decimal

import pytest
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import FieldError, ValidationError
from django.db import IntegrityError

from apps.accounts.tests.factories import CustomerUserFactory
from apps.cart.tests.factories import CartFactory, CartItemFactory
from apps.catalog.models import Product
from apps.catalog.tests.factories import (
    ApprovedVendorFactory,
    ProductFactory,
    ProductVariantFactory,
)
from apps.inventory.tests.factories import InventoryRecordFactory
from apps.orders.models import Order, OrderItem
from apps.reviews.models import Review
from apps.reviews.tests.factories import ReviewFactory


pytestmark = pytest.mark.django_db


def get_first_order_item(order):
    try:
        return OrderItem.objects.filter(order=order).first()
    except FieldError:
        return OrderItem.objects.filter(vendor_order__order=order).first()


def mark_order_completed(order):
    completed_status = Review.get_completed_status_value()

    Order.objects.filter(pk=order.pk).update(status=completed_status)
    order.refresh_from_db()

    return order


def create_active_product_variant_with_inventory(
    *,
    vendor=None,
    name="Review Test Product",
    base_price=Decimal("50.00"),
    quantity_on_hand=100,
    quantity_reserved=0,
):
    product = ProductFactory(
        vendor=vendor or ApprovedVendorFactory(),
        name=name,
        base_price=base_price,
        status=Product.Status.ACTIVE,
    )

    variant = ProductVariantFactory(
        product=product,
        price=base_price,
    )

    inventory_record = InventoryRecordFactory(
        product=product,
        variant=variant,
        quantity_on_hand=quantity_on_hand,
        quantity_reserved=quantity_reserved,
        track_inventory=True,
        allow_backorder=False,
    )

    return product, variant, inventory_record


def create_completed_order_with_variant_item(
    *,
    customer=None,
    product=None,
    variant=None,
    vendor=None,
    quantity=1,
    base_price=Decimal("50.00"),
):
    customer = customer or CustomerUserFactory()
    cart = CartFactory(customer=customer)

    if product is None or variant is None:
        product, variant, inventory_record = create_active_product_variant_with_inventory(
            vendor=vendor,
            base_price=base_price,
        )
    else:
        inventory_record = None

    CartItemFactory(
        cart=cart,
        product=product,
        variant=variant,
        quantity=quantity,
    )

    order = Order.create_from_cart(cart)
    order = mark_order_completed(order)

    order_item = get_first_order_item(order)

    if order_item.variant_id != variant.id:
        OrderItem.objects.filter(pk=order_item.pk).update(variant=variant)
        order_item.refresh_from_db()

    return order, order_item, product, variant, inventory_record, cart


def create_non_completed_order_with_variant_item(*, customer=None):
    customer = customer or CustomerUserFactory()
    cart = CartFactory(customer=customer)

    product, variant, inventory_record = create_active_product_variant_with_inventory()

    CartItemFactory(
        cart=cart,
        product=product,
        variant=variant,
        quantity=1,
    )

    order = Order.create_from_cart(cart)
    order.refresh_from_db()

    order_item = get_first_order_item(order)

    if order_item.variant_id != variant.id:
        OrderItem.objects.filter(pk=order_item.pk).update(variant=variant)
        order_item.refresh_from_db()

    return order, order_item, product, variant, inventory_record, cart


def create_completed_order_with_product_only_item(*, customer=None):
    customer = customer or CustomerUserFactory()
    cart = CartFactory(customer=customer)

    product = ProductFactory(
        vendor=ApprovedVendorFactory(),
        name="Review Product Without Variant",
        base_price=Decimal("50.00"),
        status=Product.Status.ACTIVE,
    )

    InventoryRecordFactory(
        product=product,
        variant=None,
        quantity_on_hand=100,
        quantity_reserved=0,
        track_inventory=True,
        allow_backorder=False,
    )

    CartItemFactory(
        cart=cart,
        product=product,
        quantity=1,
    )

    order = Order.create_from_cart(cart)
    order = mark_order_completed(order)

    order_item = get_first_order_item(order)

    if order_item.variant_id:
        OrderItem.objects.filter(pk=order_item.pk).update(variant=None)
        order_item.refresh_from_db()

    return order, order_item, product, cart


def test_review_factory_creates_valid_review():
    customer = CustomerUserFactory()
    order, order_item, _, variant, _, _ = create_completed_order_with_variant_item(
        customer=customer,
    )

    review = ReviewFactory(
        order_item=order_item,
        reviewer=customer,
        variant=variant,
        rating=5,
        body="Great product.",
    )

    assert review.id is not None
    assert review.order_item == order_item
    assert review.reviewer == customer
    assert review.variant == variant
    assert review.rating == 5
    assert review.body == "Great product."
    assert review.is_visible is True
    assert review.created_at is not None


def test_review_create_for_order_item_creates_review():
    customer = CustomerUserFactory()
    order, order_item, _, variant, _, _ = create_completed_order_with_variant_item(
        customer=customer,
    )

    review = Review.create_for_order_item(
        order_item=order_item,
        reviewer=customer,
        variant=variant,
        rating=4,
        body="Good quality.",
    )

    assert review.id is not None
    assert review.order_item == order_item
    assert review.reviewer == customer
    assert review.variant == variant
    assert review.rating == 4
    assert review.body == "Good quality."
    assert review.is_visible is True


def test_review_default_is_visible_true():
    customer = CustomerUserFactory()
    order, order_item, _, variant, _, _ = create_completed_order_with_variant_item(
        customer=customer,
    )

    review = Review.objects.create(
        order_item=order_item,
        reviewer=customer,
        variant=variant,
        rating=5,
        body="Visible by default.",
    )

    assert review.is_visible is True


def test_review_str_contains_variant_and_rating():
    customer = CustomerUserFactory()
    order, order_item, _, variant, _, _ = create_completed_order_with_variant_item(
        customer=customer,
    )

    review = ReviewFactory(
        order_item=order_item,
        reviewer=customer,
        variant=variant,
        rating=3,
    )

    text = str(review)

    assert str(variant.id) in text
    assert "3/5" in text


def test_only_order_customer_can_review():
    customer = CustomerUserFactory()
    other_customer = CustomerUserFactory()

    order, order_item, _, variant, _, _ = create_completed_order_with_variant_item(
        customer=customer,
    )

    with pytest.raises(ValidationError):
        Review.create_for_order_item(
            order_item=order_item,
            reviewer=other_customer,
            variant=variant,
            rating=5,
            body="Not allowed.",
        )


def test_anonymous_user_cannot_review():
    customer = CustomerUserFactory()
    order, order_item, _, variant, _, _ = create_completed_order_with_variant_item(
        customer=customer,
    )

    anonymous_user = AnonymousUser()

    with pytest.raises(ValidationError):
        Review.validate_order_item_review_rules(
            reviewer=anonymous_user,
            order_item=order_item,
            variant=variant,
        )


def test_non_completed_order_item_cannot_be_reviewed():
    customer = CustomerUserFactory()
    order, order_item, _, variant, _, _ = create_non_completed_order_with_variant_item(
        customer=customer,
    )

    with pytest.raises(ValidationError):
        Review.create_for_order_item(
            order_item=order_item,
            reviewer=customer,
            variant=variant,
            rating=5,
            body="Order is not completed yet.",
        )


def test_review_variant_must_match_order_item_variant():
    customer = CustomerUserFactory()
    order, order_item, product, variant, _, _ = create_completed_order_with_variant_item(
        customer=customer,
    )

    other_variant = ProductVariantFactory(
        product=product,
        price=Decimal("60.00"),
    )

    with pytest.raises(ValidationError):
        Review.create_for_order_item(
            order_item=order_item,
            reviewer=customer,
            variant=other_variant,
            rating=5,
            body="Wrong variant.",
        )


def test_rating_below_one_is_rejected():
    customer = CustomerUserFactory()
    order, order_item, _, variant, _, _ = create_completed_order_with_variant_item(
        customer=customer,
    )

    review = Review(
        order_item=order_item,
        reviewer=customer,
        variant=variant,
        rating=0,
        body="Invalid rating.",
    )

    with pytest.raises(ValidationError):
        review.full_clean()


def test_rating_above_five_is_rejected():
    customer = CustomerUserFactory()
    order, order_item, _, variant, _, _ = create_completed_order_with_variant_item(
        customer=customer,
    )

    review = Review(
        order_item=order_item,
        reviewer=customer,
        variant=variant,
        rating=6,
        body="Invalid rating.",
    )

    with pytest.raises(ValidationError):
        review.full_clean()


def test_review_body_cannot_be_blank():
    customer = CustomerUserFactory()
    order, order_item, _, variant, _, _ = create_completed_order_with_variant_item(
        customer=customer,
    )

    review = Review(
        order_item=order_item,
        reviewer=customer,
        variant=variant,
        rating=5,
        body="",
    )

    with pytest.raises(ValidationError):
        review.full_clean()


def test_one_review_per_order_item_prevents_duplicates():
    customer = CustomerUserFactory()
    order, order_item, _, variant, _, _ = create_completed_order_with_variant_item(
        customer=customer,
    )

    ReviewFactory(
        order_item=order_item,
        reviewer=customer,
        variant=variant,
        rating=5,
    )

    with pytest.raises((ValidationError, IntegrityError)):
        ReviewFactory(
            order_item=order_item,
            reviewer=customer,
            variant=variant,
            rating=4,
        )


def test_create_for_order_item_prevents_duplicate_review():
    customer = CustomerUserFactory()
    order, order_item, _, variant, _, _ = create_completed_order_with_variant_item(
        customer=customer,
    )

    Review.create_for_order_item(
        order_item=order_item,
        reviewer=customer,
        variant=variant,
        rating=5,
        body="First review.",
    )

    with pytest.raises((ValidationError, IntegrityError)):
        Review.create_for_order_item(
            order_item=order_item,
            reviewer=customer,
            variant=variant,
            rating=4,
            body="Duplicate review.",
        )


def test_rating_summary_counts_visible_reviews():
    first_customer = CustomerUserFactory()
    first_order, first_item, product, variant, _, _ = create_completed_order_with_variant_item(
        customer=first_customer,
    )

    second_customer = CustomerUserFactory()
    second_order, second_item, _, _, _, _ = create_completed_order_with_variant_item(
        customer=second_customer,
        product=product,
        variant=variant,
    )

    ReviewFactory(
        order_item=first_item,
        reviewer=first_customer,
        variant=variant,
        rating=5,
        is_visible=True,
    )
    ReviewFactory(
        order_item=second_item,
        reviewer=second_customer,
        variant=variant,
        rating=3,
        is_visible=True,
    )

    summary = Review.get_rating_summary_for_variant(variant)

    assert summary["review_count"] == 2
    assert summary["average_rating"] == Decimal("4")


def test_hidden_review_is_not_counted_in_summary():
    first_customer = CustomerUserFactory()
    first_order, first_item, product, variant, _, _ = create_completed_order_with_variant_item(
        customer=first_customer,
    )

    second_customer = CustomerUserFactory()
    second_order, second_item, _, _, _, _ = create_completed_order_with_variant_item(
        customer=second_customer,
        product=product,
        variant=variant,
    )

    ReviewFactory(
        order_item=first_item,
        reviewer=first_customer,
        variant=variant,
        rating=5,
        is_visible=True,
    )
    ReviewFactory(
        order_item=second_item,
        reviewer=second_customer,
        variant=variant,
        rating=1,
        is_visible=False,
    )

    summary = Review.get_rating_summary_for_variant(variant)

    assert summary["review_count"] == 1
    assert summary["average_rating"] == Decimal("5")


def test_rating_summary_returns_zero_for_variant_without_reviews():
    _, variant, _ = create_active_product_variant_with_inventory()

    summary = Review.get_rating_summary_for_variant(variant)

    assert summary["review_count"] == 0
    assert summary["average_rating"] is None


def test_validate_order_item_review_rules_returns_true_for_valid_data():
    customer = CustomerUserFactory()
    order, order_item, _, variant, _, _ = create_completed_order_with_variant_item(
        customer=customer,
    )

    result = Review.validate_order_item_review_rules(
        reviewer=customer,
        order_item=order_item,
        variant=variant,
    )

    assert result is True


def test_review_save_runs_validation():
    customer = CustomerUserFactory()
    other_customer = CustomerUserFactory()

    order, order_item, _, variant, _, _ = create_completed_order_with_variant_item(
        customer=customer,
    )

    review = Review(
        order_item=order_item,
        reviewer=other_customer,
        variant=variant,
        rating=5,
        body="Invalid reviewer.",
    )

    with pytest.raises(ValidationError):
        review.save()


def test_review_can_be_hidden_with_visibility_flag():
    customer = CustomerUserFactory()
    order, order_item, _, variant, _, _ = create_completed_order_with_variant_item(
        customer=customer,
    )

    review = ReviewFactory(
        order_item=order_item,
        reviewer=customer,
        variant=variant,
        rating=5,
        is_visible=True,
    )

    review.is_visible = False
    review.save(update_fields=["is_visible"])

    review.refresh_from_db()

    assert review.is_visible is False


def test_completed_status_value_is_string():
    completed_status = Review.get_completed_status_value()

    assert isinstance(completed_status, str)
    assert completed_status == "COMPLETED"


def test_review_rejects_order_item_without_variant():
    customer = CustomerUserFactory()
    order, order_item, product, cart = create_completed_order_with_product_only_item(
        customer=customer,
    )

    variant = ProductVariantFactory(
        product=product,
        price=Decimal("50.00"),
    )

    with pytest.raises(ValidationError):
        Review.validate_order_item_review_rules(
            reviewer=customer,
            order_item=order_item,
            variant=variant,
        )