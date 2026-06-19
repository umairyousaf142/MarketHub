from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from apps.accounts.tests.factories import CustomerUserFactory, VendorUserFactory
from apps.cart.models import Cart, CartItem
from apps.cart.tests.factories import CartFactory, CartItemFactory
from apps.catalog.models import Product
from apps.catalog.tests.factories import (
    PendingVendorFactory,
    ProductFactory,
    ProductVariantFactory,
)
from apps.inventory.tests.factories import InventoryRecordFactory


pytestmark = pytest.mark.django_db


def create_active_product_with_inventory(
    *,
    name="Active Cart Product",
    base_price=Decimal("100.00"),
    quantity_on_hand=100,
    quantity_reserved=0,
    low_stock_threshold=5,
    track_inventory=True,
    allow_backorder=False,
    **overrides,
):
    product = ProductFactory(
        name=name,
        base_price=base_price,
        status=Product.Status.ACTIVE,
        **overrides,
    )

    InventoryRecordFactory(
        product=product,
        variant=None,
        quantity_on_hand=quantity_on_hand,
        quantity_reserved=quantity_reserved,
        low_stock_threshold=low_stock_threshold,
        track_inventory=track_inventory,
        allow_backorder=allow_backorder,
    )

    return product


def create_active_variant_with_inventory(
    product,
    *,
    name="Default Variant",
    price=Decimal("120.00"),
    quantity_on_hand=100,
    quantity_reserved=0,
    is_active=True,
    track_inventory=True,
    allow_backorder=False,
    **overrides,
):
    variant = ProductVariantFactory(
        product=product,
        name=name,
        price=price,
        is_active=is_active,
        **overrides,
    )

    InventoryRecordFactory(
        product=product,
        variant=variant,
        quantity_on_hand=quantity_on_hand,
        quantity_reserved=quantity_reserved,
        track_inventory=track_inventory,
        allow_backorder=allow_backorder,
    )

    return variant


def test_cart_can_be_created_for_customer():
    customer = CustomerUserFactory()

    cart = CartFactory(customer=customer)

    assert cart.customer == customer
    assert cart.status == Cart.Status.ACTIVE
    assert str(cart).startswith("Cart")


def test_cart_cannot_be_created_for_vendor_user():
    vendor_user = VendorUserFactory()

    with pytest.raises(ValidationError):
        CartFactory(customer=vendor_user)


def test_only_one_active_cart_allowed_per_customer():
    customer = CustomerUserFactory()

    CartFactory(customer=customer)

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            CartFactory(customer=customer)


def test_converted_cart_sets_converted_at():
    cart = CartFactory(status=Cart.Status.CONVERTED)

    assert cart.converted_at is not None


def test_abandoned_cart_sets_abandoned_at():
    cart = CartFactory(status=Cart.Status.ABANDONED)

    assert cart.abandoned_at is not None


def test_cart_item_count_total_quantity_and_subtotal():
    cart = CartFactory()

    first_product = create_active_product_with_inventory(
        name="First Product",
        base_price=Decimal("10.00"),
    )
    second_product = create_active_product_with_inventory(
        name="Second Product",
        base_price=Decimal("20.00"),
    )

    CartItemFactory(
        cart=cart,
        product=first_product,
        quantity=2,
    )
    CartItemFactory(
        cart=cart,
        product=second_product,
        quantity=3,
    )

    assert cart.item_count == 2
    assert cart.total_quantity == 5
    assert cart.subtotal_amount == Decimal("80.00")


def test_cart_clear_removes_items_from_active_cart():
    cart = CartFactory()
    product = create_active_product_with_inventory()

    CartItemFactory(
        cart=cart,
        product=product,
        quantity=2,
    )

    assert cart.items.count() == 1

    cart.clear()

    assert cart.items.count() == 0


def test_cart_clear_rejects_converted_cart():
    cart = CartFactory(status=Cart.Status.CONVERTED)

    with pytest.raises(ValidationError):
        cart.clear()


def test_mark_converted_updates_status_and_timestamp():
    cart = CartFactory()

    cart.mark_converted()

    cart.refresh_from_db()

    assert cart.status == Cart.Status.CONVERTED
    assert cart.converted_at is not None


def test_mark_abandoned_updates_status_and_timestamp():
    cart = CartFactory()

    cart.mark_abandoned()

    cart.refresh_from_db()

    assert cart.status == Cart.Status.ABANDONED
    assert cart.abandoned_at is not None


def test_cart_add_item_creates_product_level_item():
    cart = CartFactory()
    product = create_active_product_with_inventory(
        base_price=Decimal("50.00"),
    )

    item = cart.add_item(
        product=product,
        quantity=2,
    )

    assert item.cart == cart
    assert item.product == product
    assert item.variant is None
    assert item.quantity == 2
    assert item.unit_price == Decimal("50.00")
    assert item.line_total == Decimal("100.00")


def test_cart_add_item_merges_existing_product_level_item():
    cart = CartFactory()
    product = create_active_product_with_inventory(
        quantity_on_hand=10,
    )

    first_item = cart.add_item(
        product=product,
        quantity=2,
    )

    second_item = cart.add_item(
        product=product,
        quantity=3,
    )

    first_item.refresh_from_db()

    assert first_item.id == second_item.id
    assert first_item.quantity == 5
    assert cart.items.count() == 1


def test_cart_add_item_creates_variant_level_item():
    cart = CartFactory()
    product = create_active_product_with_inventory()
    variant = create_active_variant_with_inventory(
        product,
        name="128GB Black",
        price=Decimal("150.00"),
    )

    item = cart.add_item(
        product=product,
        variant=variant,
        quantity=2,
    )

    assert item.product == product
    assert item.variant == variant
    assert item.quantity == 2
    assert item.unit_price == Decimal("150.00")
    assert item.line_total == Decimal("300.00")


def test_cart_add_item_rejects_zero_quantity():
    cart = CartFactory()
    product = create_active_product_with_inventory()

    with pytest.raises(ValidationError):
        cart.add_item(
            product=product,
            quantity=0,
        )


def test_cart_add_item_rejects_inactive_cart():
    cart = CartFactory(status=Cart.Status.CONVERTED)
    product = create_active_product_with_inventory()

    with pytest.raises(ValidationError):
        cart.add_item(
            product=product,
            quantity=1,
        )


def test_cart_item_requires_active_product():
    cart = CartFactory()
    product = ProductFactory(status=Product.Status.DRAFT)

    with pytest.raises(ValidationError):
        CartItem.objects.create(
            cart=cart,
            product=product,
            quantity=1,
        )


def test_cart_item_requires_approved_vendor():
    cart = CartFactory()
    pending_vendor = PendingVendorFactory()

    product = ProductFactory(
        vendor=pending_vendor,
        status=Product.Status.DRAFT,
    )

    Product.objects.filter(pk=product.pk).update(status=Product.Status.ACTIVE)
    product.refresh_from_db()

    with pytest.raises(ValidationError):
        CartItem.objects.create(
            cart=cart,
            product=product,
            quantity=1,
        )


def test_cart_item_requires_active_category():
    cart = CartFactory()
    product = create_active_product_with_inventory()

    product.category.is_active = False
    product.category.save(update_fields=["is_active"])

    with pytest.raises(ValidationError):
        CartItem.objects.create(
            cart=cart,
            product=product,
            quantity=1,
        )


def test_cart_item_requires_active_brand():
    cart = CartFactory()
    product = create_active_product_with_inventory()

    product.brand.is_active = False
    product.brand.save(update_fields=["is_active"])

    with pytest.raises(ValidationError):
        CartItem.objects.create(
            cart=cart,
            product=product,
            quantity=1,
        )


def test_cart_item_variant_must_belong_to_product():
    cart = CartFactory()

    product = create_active_product_with_inventory(name="Main Product")
    other_product = create_active_product_with_inventory(name="Other Product")

    other_variant = create_active_variant_with_inventory(
        other_product,
        name="Other Variant",
    )

    with pytest.raises(ValidationError):
        CartItem.objects.create(
            cart=cart,
            product=product,
            variant=other_variant,
            quantity=1,
        )


def test_cart_item_requires_active_variant():
    cart = CartFactory()
    product = create_active_product_with_inventory()

    variant = create_active_variant_with_inventory(
        product,
        name="Inactive Variant",
        is_active=False,
    )

    with pytest.raises(ValidationError):
        CartItem.objects.create(
            cart=cart,
            product=product,
            variant=variant,
            quantity=1,
        )


def test_cart_item_requires_inventory_record():
    cart = CartFactory()

    product = ProductFactory(
        name="Product Without Inventory",
        status=Product.Status.ACTIVE,
    )

    with pytest.raises(ValidationError):
        CartItem.objects.create(
            cart=cart,
            product=product,
            quantity=1,
        )


def test_cart_item_rejects_quantity_exceeding_available_stock():
    cart = CartFactory()

    product = create_active_product_with_inventory(
        quantity_on_hand=5,
        quantity_reserved=2,
    )

    with pytest.raises(ValidationError):
        CartItem.objects.create(
            cart=cart,
            product=product,
            quantity=4,
        )


def test_cart_item_allows_exceeding_stock_when_track_inventory_disabled():
    cart = CartFactory()

    product = create_active_product_with_inventory(
        quantity_on_hand=0,
        quantity_reserved=0,
        track_inventory=False,
    )

    item = CartItem.objects.create(
        cart=cart,
        product=product,
        quantity=99,
    )

    assert item.quantity == 99


def test_cart_item_allows_exceeding_stock_when_backorder_enabled():
    cart = CartFactory()

    product = create_active_product_with_inventory(
        quantity_on_hand=0,
        quantity_reserved=0,
        allow_backorder=True,
    )

    item = CartItem.objects.create(
        cart=cart,
        product=product,
        quantity=25,
    )

    assert item.quantity == 25


def test_product_level_unit_price_is_snapshotted_on_create():
    cart = CartFactory()

    product = create_active_product_with_inventory(
        base_price=Decimal("100.00"),
    )

    item = CartItemFactory(
        cart=cart,
        product=product,
        quantity=1,
    )

    Product.objects.filter(pk=product.pk).update(base_price=Decimal("200.00"))

    item.refresh_from_db()

    assert item.unit_price == Decimal("100.00")


def test_variant_level_unit_price_is_snapshotted_on_create():
    cart = CartFactory()
    product = create_active_product_with_inventory()
    variant = create_active_variant_with_inventory(
        product,
        price=Decimal("150.00"),
    )

    item = CartItemFactory(
        cart=cart,
        product=product,
        variant=variant,
        quantity=1,
    )

    type(variant).objects.filter(pk=variant.pk).update(price=Decimal("250.00"))

    item.refresh_from_db()

    assert item.unit_price == Decimal("150.00")


def test_cart_item_line_total_uses_snapshot_price_and_quantity():
    cart = CartFactory()

    product = create_active_product_with_inventory(
        base_price=Decimal("12.50"),
    )

    item = CartItemFactory(
        cart=cart,
        product=product,
        quantity=3,
    )

    assert item.line_total == Decimal("37.50")


def test_duplicate_product_level_item_per_cart_rejected():
    cart = CartFactory()
    product = create_active_product_with_inventory()

    CartItemFactory(
        cart=cart,
        product=product,
        variant=None,
        quantity=1,
    )

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            CartItem.objects.create(
                cart=cart,
                product=product,
                variant=None,
                quantity=1,
            )


def test_duplicate_variant_level_item_per_cart_rejected():
    cart = CartFactory()
    product = create_active_product_with_inventory()
    variant = create_active_variant_with_inventory(product)

    CartItemFactory(
        cart=cart,
        product=product,
        variant=variant,
        quantity=1,
    )

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            CartItem.objects.create(
                cart=cart,
                product=product,
                variant=variant,
                quantity=1,
            )


def test_same_product_can_have_product_level_and_variant_level_items():
    cart = CartFactory()

    product = create_active_product_with_inventory()
    variant = create_active_variant_with_inventory(product)

    product_level_item = CartItemFactory(
        cart=cart,
        product=product,
        variant=None,
        quantity=1,
    )

    variant_level_item = CartItemFactory(
        cart=cart,
        product=product,
        variant=variant,
        quantity=1,
    )

    assert product_level_item.product == product
    assert product_level_item.variant is None

    assert variant_level_item.product == product
    assert variant_level_item.variant == variant

    assert cart.items.count() == 2


def test_cart_item_quantity_update_revalidates_inventory():
    cart = CartFactory()

    product = create_active_product_with_inventory(
        quantity_on_hand=5,
        quantity_reserved=0,
    )

    item = CartItemFactory(
        cart=cart,
        product=product,
        quantity=3,
    )

    item.quantity = 6

    with pytest.raises(ValidationError):
        item.save()

    item.refresh_from_db()

    assert item.quantity == 3


def test_cart_item_str_for_product_level():
    cart = CartFactory()

    product = create_active_product_with_inventory(
        name="Simple Cart Product",
    )

    item = CartItemFactory(
        cart=cart,
        product=product,
        quantity=2,
    )

    assert str(item) == "Simple Cart Product x 2"


def test_cart_item_str_for_variant_level():
    cart = CartFactory()

    product = create_active_product_with_inventory(
        name="Shoes",
    )

    variant = create_active_variant_with_inventory(
        product,
        name="Size 42",
    )

    item = CartItemFactory(
        cart=cart,
        product=product,
        variant=variant,
        quantity=2,
    )

    assert str(item) == "Shoes - Size 42 x 2"