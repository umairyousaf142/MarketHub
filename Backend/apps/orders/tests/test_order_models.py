from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from apps.accounts.tests.factories import CustomerUserFactory, VendorUserFactory
from apps.cart.models import CartItem
from apps.cart.tests.factories import CartFactory, CartItemFactory
from apps.catalog.models import Product
from apps.catalog.tests.factories import (
    ApprovedVendorFactory,
    ProductFactory,
    ProductVariantFactory,
)
from apps.inventory.tests.factories import InventoryRecordFactory
from apps.orders.models import Order, OrderItem, VendorOrder
from apps.orders.tests.factories import (
    OrderFactory,
    OrderItemFactory,
    VendorOrderFactory,
)


pytestmark = pytest.mark.django_db


def create_active_product_with_inventory(
    *,
    name="Order Product",
    base_price=Decimal("100.00"),
    quantity_on_hand=100,
    quantity_reserved=0,
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

    inventory_record = InventoryRecordFactory(
        product=product,
        variant=None,
        quantity_on_hand=quantity_on_hand,
        quantity_reserved=quantity_reserved,
        track_inventory=track_inventory,
        allow_backorder=allow_backorder,
    )

    return product, inventory_record


def create_active_variant_with_inventory(
    product,
    *,
    name="Order Variant",
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

    inventory_record = InventoryRecordFactory(
        product=product,
        variant=variant,
        quantity_on_hand=quantity_on_hand,
        quantity_reserved=quantity_reserved,
        track_inventory=track_inventory,
        allow_backorder=allow_backorder,
    )

    return variant, inventory_record


def test_order_can_be_created_for_customer_and_generates_order_number():
    customer = CustomerUserFactory()

    order = OrderFactory(customer=customer)

    assert order.customer == customer
    assert order.order_number.startswith("MH-")
    assert order.status == Order.Status.PENDING
    assert str(order) == order.order_number


def test_order_cannot_be_created_for_vendor_user():
    vendor_user = VendorUserFactory()

    with pytest.raises(ValidationError):
        OrderFactory(customer=vendor_user)


def test_order_source_cart_must_belong_to_customer():
    cart_customer = CustomerUserFactory()
    other_customer = CustomerUserFactory()

    cart = CartFactory(customer=cart_customer)

    with pytest.raises(ValidationError):
        OrderFactory(
            customer=other_customer,
            source_cart=cart,
        )


def test_order_calculates_total_amount():
    order = OrderFactory(
        subtotal_amount=Decimal("100.00"),
        shipping_amount=Decimal("10.00"),
        tax_amount=Decimal("5.00"),
        discount_amount=Decimal("15.00"),
    )

    assert order.total_amount == Decimal("100.00")


def test_order_total_amount_cannot_be_negative():
    with pytest.raises(ValidationError):
        OrderFactory(
            subtotal_amount=Decimal("10.00"),
            shipping_amount=Decimal("0.00"),
            tax_amount=Decimal("0.00"),
            discount_amount=Decimal("20.00"),
        )


def test_paid_order_sets_paid_at():
    order = OrderFactory(payment_status=Order.PaymentStatus.PAID)

    assert order.paid_at is not None


def test_cancelled_order_sets_cancelled_at():
    order = OrderFactory(status=Order.Status.CANCELLED)

    assert order.cancelled_at is not None


def test_order_item_count_and_total_quantity():
    order = OrderFactory()

    OrderItemFactory(order=order, quantity=2)
    OrderItemFactory(order=order, quantity=3)

    assert order.item_count == 2
    assert order.total_quantity == 5


def test_order_str_returns_order_number():
    order = OrderFactory()

    assert str(order) == order.order_number


def test_order_item_can_be_created_with_product_snapshot():
    order = OrderFactory()
    product = ProductFactory(
        name="Snapshot Product",
        sku="SNAP-001",
    )

    item = OrderItemFactory(
        order=order,
        product=product,
        quantity=2,
        unit_price=Decimal("50.00"),
    )

    assert item.order == order
    assert item.product == product
    assert item.vendor == product.vendor
    assert item.product_name == "Snapshot Product"
    assert item.product_sku == "SNAP-001"
    assert item.vendor_store_name == product.vendor.store_name
    assert item.quantity == 2
    assert item.unit_price == Decimal("50.00")
    assert item.line_total == Decimal("100.00")


def test_order_item_can_be_created_with_variant_snapshot():
    order = OrderFactory()
    product = ProductFactory(name="Variant Snapshot Product")
    variant = ProductVariantFactory(
        product=product,
        name="128GB Black",
        sku="VAR-SNAP-001",
    )

    item = OrderItemFactory(
        order=order,
        product=product,
        variant=variant,
        quantity=1,
        unit_price=Decimal("150.00"),
    )

    assert item.variant == variant
    assert item.variant_name == "128GB Black"
    assert item.variant_sku == "VAR-SNAP-001"
    assert item.line_total == Decimal("150.00")


def test_order_item_quantity_must_be_positive():
    with pytest.raises(ValidationError):
        OrderItemFactory(quantity=0)


def test_order_item_unit_price_cannot_be_negative():
    with pytest.raises(ValidationError):
        OrderItemFactory(unit_price=Decimal("-1.00"))


def test_order_item_variant_must_belong_to_product():
    order = OrderFactory()

    product = ProductFactory(name="Main Product")
    other_product = ProductFactory(name="Other Product")
    other_variant = ProductVariantFactory(product=other_product)

    with pytest.raises(ValidationError):
        OrderItemFactory(
            order=order,
            product=product,
            variant=other_variant,
        )


def test_order_item_vendor_must_match_product_vendor():
    order = OrderFactory()

    product = ProductFactory()
    other_vendor = ApprovedVendorFactory()

    with pytest.raises(ValidationError):
        OrderItemFactory(
            order=order,
            product=product,
            vendor=other_vendor,
        )


def test_order_item_line_total_is_calculated():
    item = OrderItemFactory(
        quantity=3,
        unit_price=Decimal("12.50"),
    )

    assert item.line_total == Decimal("37.50")


def test_order_item_str_for_product_level():
    item = OrderItemFactory(
        product_name="Simple Ordered Product",
        variant_name="",
        quantity=2,
    )

    assert str(item) == "Simple Ordered Product x 2"


def test_order_item_str_for_variant_level():
    item = OrderItemFactory(
        product_name="Shoes",
        variant_name="Size 42",
        quantity=2,
    )

    assert str(item) == "Shoes - Size 42 x 2"


def test_vendor_order_recalculates_totals():
    order = OrderFactory()

    vendor = ApprovedVendorFactory()
    product = ProductFactory(vendor=vendor)

    OrderItemFactory(
        order=order,
        product=product,
        vendor=vendor,
        quantity=2,
        unit_price=Decimal("10.00"),
    )
    OrderItemFactory(
        order=order,
        product=product,
        vendor=vendor,
        quantity=3,
        unit_price=Decimal("20.00"),
    )

    vendor_order = VendorOrder.objects.create(
        order=order,
        vendor=vendor,
    )

    vendor_order.recalculate_totals(save=True)
    vendor_order.refresh_from_db()

    assert vendor_order.subtotal_amount == Decimal("80.00")
    assert vendor_order.item_count == 2
    assert vendor_order.total_quantity == 5


def test_only_one_vendor_order_allowed_per_order_vendor():
    order = OrderFactory()

    vendor = ApprovedVendorFactory()
    product = ProductFactory(vendor=vendor)

    OrderItemFactory(
        order=order,
        product=product,
        vendor=vendor,
    )

    VendorOrder.objects.create(
        order=order,
        vendor=vendor,
    )

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            VendorOrder.objects.create(
                order=order,
                vendor=vendor,
            )


def test_vendor_order_requires_vendor_items_in_order():
    order = OrderFactory()
    vendor = ApprovedVendorFactory()

    with pytest.raises(ValidationError):
        VendorOrder.objects.create(
            order=order,
            vendor=vendor,
        )


def test_vendor_order_str_returns_order_and_vendor():
    vendor_order = VendorOrderFactory()

    assert str(vendor_order) == (
        f"{vendor_order.order.order_number} - {vendor_order.vendor.store_name}"
    )


def test_create_from_cart_rejects_empty_cart():
    cart = CartFactory()

    with pytest.raises(ValidationError):
        Order.create_from_cart(cart)


def test_create_from_cart_creates_order_items_vendor_order_and_reserves_inventory():
    customer = CustomerUserFactory()
    cart = CartFactory(customer=customer)

    product, inventory_record = create_active_product_with_inventory(
        name="Order API Product",
        base_price=Decimal("50.00"),
        quantity_on_hand=20,
        quantity_reserved=0,
    )

    CartItemFactory(
        cart=cart,
        product=product,
        quantity=2,
    )

    order = Order.create_from_cart(
        cart,
        shipping_address={"city": "Lahore"},
        billing_address={"city": "Lahore"},
        shipping_amount=Decimal("10.00"),
        tax_amount=Decimal("5.00"),
        discount_amount=Decimal("0.00"),
        notes="Test order",
    )

    order.refresh_from_db()
    cart.refresh_from_db()
    inventory_record.refresh_from_db()

    assert order.customer == customer
    assert order.source_cart == cart
    assert order.subtotal_amount == Decimal("100.00")
    assert order.total_amount == Decimal("115.00")
    assert order.inventory_status == Order.InventoryStatus.RESERVED

    assert order.items.count() == 1
    assert order.vendor_orders.count() == 1

    order_item = order.items.first()

    assert order_item.product == product
    assert order_item.product_name == product.name
    assert order_item.quantity == 2
    assert order_item.unit_price == Decimal("50.00")
    assert order_item.line_total == Decimal("100.00")
    assert order_item.inventory_record == inventory_record

    vendor_order = order.vendor_orders.first()

    assert vendor_order.vendor == product.vendor
    assert vendor_order.subtotal_amount == Decimal("100.00")
    assert vendor_order.item_count == 1
    assert vendor_order.total_quantity == 2

    assert inventory_record.quantity_on_hand == 20
    assert inventory_record.quantity_reserved == 2
    assert inventory_record.movements.count() == 1

    assert cart.status == cart.Status.CONVERTED


def test_create_from_cart_with_variant_item_uses_variant_snapshot_and_inventory():
    cart = CartFactory()

    product, _ = create_active_product_with_inventory(
        name="Variant Order Product",
        base_price=Decimal("100.00"),
    )
    variant, variant_inventory = create_active_variant_with_inventory(
        product,
        name="256GB Blue",
        price=Decimal("180.00"),
        quantity_on_hand=10,
    )

    CartItemFactory(
        cart=cart,
        product=product,
        variant=variant,
        quantity=2,
    )

    order = Order.create_from_cart(cart)

    order_item = order.items.first()
    variant_inventory.refresh_from_db()

    assert order_item.variant == variant
    assert order_item.variant_name == "256GB Blue"
    assert order_item.unit_price == Decimal("180.00")
    assert order_item.line_total == Decimal("360.00")
    assert order_item.inventory_record == variant_inventory

    assert variant_inventory.quantity_reserved == 2
    assert order.inventory_status == Order.InventoryStatus.RESERVED


def test_create_from_cart_creates_vendor_orders_per_vendor():
    cart = CartFactory()

    first_product, _ = create_active_product_with_inventory(
        name="First Vendor Product",
        base_price=Decimal("10.00"),
    )
    second_product, _ = create_active_product_with_inventory(
        name="Second Vendor Product",
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

    order = Order.create_from_cart(cart)

    assert order.items.count() == 2
    assert order.vendor_orders.count() == 2

    first_vendor_order = order.vendor_orders.get(vendor=first_product.vendor)
    second_vendor_order = order.vendor_orders.get(vendor=second_product.vendor)

    assert first_vendor_order.subtotal_amount == Decimal("20.00")
    assert first_vendor_order.total_quantity == 2

    assert second_vendor_order.subtotal_amount == Decimal("60.00")
    assert second_vendor_order.total_quantity == 3


def test_create_from_cart_rolls_back_when_inventory_is_not_available():
    cart = CartFactory()

    product, inventory_record = create_active_product_with_inventory(
        quantity_on_hand=10,
        quantity_reserved=0,
    )

    CartItemFactory(
        cart=cart,
        product=product,
        quantity=5,
    )

    inventory_record.quantity_on_hand = 3
    inventory_record.save(update_fields=["quantity_on_hand", "updated_at"])

    with pytest.raises(ValidationError):
        Order.create_from_cart(cart)

    cart.refresh_from_db()
    inventory_record.refresh_from_db()

    assert Order.objects.count() == 0
    assert cart.status == cart.Status.ACTIVE
    assert inventory_record.quantity_reserved == 0
    assert inventory_record.movements.count() == 0


def test_create_from_cart_rejects_missing_inventory_record():
    cart = CartFactory()

    product = ProductFactory(
        name="Missing Inventory Product",
        base_price=Decimal("40.00"),
        status=Product.Status.ACTIVE,
    )

    CartItem.objects.bulk_create(
        [
            CartItem(
                cart=cart,
                product=product,
                variant=None,
                quantity=1,
                unit_price=Decimal("40.00"),
            )
        ]
    )

    with pytest.raises(ValidationError):
        Order.create_from_cart(cart)

    cart.refresh_from_db()

    assert Order.objects.count() == 0
    assert cart.status == cart.Status.ACTIVE


def test_create_from_cart_with_inventory_tracking_disabled_does_not_reserve_stock():
    cart = CartFactory()

    product, inventory_record = create_active_product_with_inventory(
        quantity_on_hand=0,
        quantity_reserved=0,
        track_inventory=False,
    )

    CartItemFactory(
        cart=cart,
        product=product,
        quantity=10,
    )

    order = Order.create_from_cart(cart)

    inventory_record.refresh_from_db()

    assert order.inventory_status == Order.InventoryStatus.NOT_RESERVED
    assert inventory_record.quantity_on_hand == 0
    assert inventory_record.quantity_reserved == 0
    assert inventory_record.movements.count() == 0


def test_create_from_cart_with_backorder_enabled_does_not_reserve_stock():
    cart = CartFactory()

    product, inventory_record = create_active_product_with_inventory(
        quantity_on_hand=0,
        quantity_reserved=0,
        allow_backorder=True,
    )

    CartItemFactory(
        cart=cart,
        product=product,
        quantity=5,
    )

    order = Order.create_from_cart(cart)

    inventory_record.refresh_from_db()

    assert order.inventory_status == Order.InventoryStatus.NOT_RESERVED
    assert inventory_record.quantity_on_hand == 0
    assert inventory_record.quantity_reserved == 0
    assert inventory_record.movements.count() == 0


def test_commit_inventory_commits_reserved_stock():
    cart = CartFactory()

    product, inventory_record = create_active_product_with_inventory(
        quantity_on_hand=20,
        quantity_reserved=0,
    )

    CartItemFactory(
        cart=cart,
        product=product,
        quantity=4,
    )

    order = Order.create_from_cart(cart)

    order.commit_inventory()

    order.refresh_from_db()
    inventory_record.refresh_from_db()

    assert order.inventory_status == Order.InventoryStatus.COMMITTED
    assert inventory_record.quantity_on_hand == 16
    assert inventory_record.quantity_reserved == 0
    assert inventory_record.movements.count() == 2
    assert inventory_record.movements.filter(movement_type="SALE").exists()


def test_commit_inventory_rejects_non_reserved_order():
    order = OrderFactory(inventory_status=Order.InventoryStatus.NOT_RESERVED)

    with pytest.raises(ValidationError):
        order.commit_inventory()


def test_release_inventory_releases_reserved_stock():
    cart = CartFactory()

    product, inventory_record = create_active_product_with_inventory(
        quantity_on_hand=20,
        quantity_reserved=0,
    )

    CartItemFactory(
        cart=cart,
        product=product,
        quantity=4,
    )

    order = Order.create_from_cart(cart)

    order.release_inventory()

    order.refresh_from_db()
    inventory_record.refresh_from_db()

    assert order.inventory_status == Order.InventoryStatus.RELEASED
    assert inventory_record.quantity_on_hand == 20
    assert inventory_record.quantity_reserved == 0
    assert inventory_record.movements.count() == 2
    assert inventory_record.movements.filter(movement_type="RELEASE").exists()


def test_release_inventory_rejects_non_reserved_order():
    order = OrderFactory(inventory_status=Order.InventoryStatus.NOT_RESERVED)

    with pytest.raises(ValidationError):
        order.release_inventory()


def test_mark_paid_commits_inventory_and_confirms_order_and_vendor_orders():
    cart = CartFactory()

    product, inventory_record = create_active_product_with_inventory(
        quantity_on_hand=20,
        quantity_reserved=0,
    )

    CartItemFactory(
        cart=cart,
        product=product,
        quantity=3,
    )

    order = Order.create_from_cart(cart)

    order.mark_paid()

    order.refresh_from_db()
    inventory_record.refresh_from_db()

    vendor_order = order.vendor_orders.first()

    assert order.payment_status == Order.PaymentStatus.PAID
    assert order.status == Order.Status.CONFIRMED
    assert order.paid_at is not None
    assert order.inventory_status == Order.InventoryStatus.COMMITTED

    assert inventory_record.quantity_on_hand == 17
    assert inventory_record.quantity_reserved == 0

    assert vendor_order.status == VendorOrder.Status.CONFIRMED


def test_cancel_releases_inventory_and_cancels_order_and_vendor_orders():
    cart = CartFactory()

    product, inventory_record = create_active_product_with_inventory(
        quantity_on_hand=20,
        quantity_reserved=0,
    )

    CartItemFactory(
        cart=cart,
        product=product,
        quantity=3,
    )

    order = Order.create_from_cart(cart)

    order.cancel()

    order.refresh_from_db()
    inventory_record.refresh_from_db()

    vendor_order = order.vendor_orders.first()

    assert order.status == Order.Status.CANCELLED
    assert order.cancelled_at is not None
    assert order.inventory_status == Order.InventoryStatus.RELEASED

    assert inventory_record.quantity_on_hand == 20
    assert inventory_record.quantity_reserved == 0

    assert vendor_order.status == VendorOrder.Status.CANCELLED


def test_mark_paid_without_reserved_inventory_confirms_without_commit():
    cart = CartFactory()

    product, inventory_record = create_active_product_with_inventory(
        quantity_on_hand=0,
        quantity_reserved=0,
        track_inventory=False,
    )

    CartItemFactory(
        cart=cart,
        product=product,
        quantity=5,
    )

    order = Order.create_from_cart(cart)

    order.mark_paid()

    order.refresh_from_db()
    inventory_record.refresh_from_db()

    assert order.payment_status == Order.PaymentStatus.PAID
    assert order.status == Order.Status.CONFIRMED
    assert order.inventory_status == Order.InventoryStatus.NOT_RESERVED

    assert inventory_record.quantity_on_hand == 0
    assert inventory_record.quantity_reserved == 0
    assert inventory_record.movements.count() == 0


def test_cancel_without_reserved_inventory_cancels_without_release():
    cart = CartFactory()

    product, inventory_record = create_active_product_with_inventory(
        quantity_on_hand=0,
        quantity_reserved=0,
        allow_backorder=True,
    )

    CartItemFactory(
        cart=cart,
        product=product,
        quantity=5,
    )

    order = Order.create_from_cart(cart)

    order.cancel()

    order.refresh_from_db()
    inventory_record.refresh_from_db()

    assert order.status == Order.Status.CANCELLED
    assert order.inventory_status == Order.InventoryStatus.NOT_RESERVED

    assert inventory_record.quantity_on_hand == 0
    assert inventory_record.quantity_reserved == 0
    assert inventory_record.movements.count() == 0