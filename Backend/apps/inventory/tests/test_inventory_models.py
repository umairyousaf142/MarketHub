import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from apps.accounts.tests.factories import AdminUserFactory
from apps.catalog.tests.factories import (
    PendingVendorFactory,
    ProductFactory,
    ProductVariantFactory,
)
from apps.inventory.models import InventoryRecord, StockMovement
from apps.inventory.tests.factories import (
    InventoryRecordFactory,
    StockMovementFactory,
)


pytestmark = pytest.mark.django_db


def test_product_level_inventory_record_can_be_created():
    product = ProductFactory(name="Inventory Product")

    record = InventoryRecordFactory(
        product=product,
        variant=None,
        quantity_on_hand=100,
        quantity_reserved=10,
        low_stock_threshold=5,
    )

    assert record.product == product
    assert record.variant is None
    assert record.quantity_on_hand == 100
    assert record.quantity_reserved == 10
    assert record.available_quantity == 90


def test_variant_level_inventory_record_can_be_created():
    product = ProductFactory(name="Variant Inventory Product")
    variant = ProductVariantFactory(product=product, name="Large")

    record = InventoryRecordFactory(
        product=product,
        variant=variant,
        quantity_on_hand=50,
        quantity_reserved=5,
    )

    assert record.product == product
    assert record.variant == variant
    assert record.available_quantity == 45
    assert str(record) == "Variant Inventory Product - Large"


def test_inventory_variant_must_belong_to_selected_product():
    first_product = ProductFactory()
    second_product = ProductFactory()

    variant = ProductVariantFactory(product=first_product)

    with pytest.raises(ValidationError):
        InventoryRecordFactory(
            product=second_product,
            variant=variant,
        )


def test_inventory_can_only_be_managed_for_approved_vendor_products():
    pending_vendor = PendingVendorFactory()
    product = ProductFactory(vendor=pending_vendor)

    with pytest.raises(ValidationError):
        InventoryRecordFactory(product=product)


def test_reserved_quantity_cannot_exceed_quantity_on_hand():
    with pytest.raises(ValidationError):
        InventoryRecordFactory(
            quantity_on_hand=5,
            quantity_reserved=10,
        )


def test_only_one_product_level_inventory_record_allowed_per_product():
    product = ProductFactory()

    InventoryRecordFactory(
        product=product,
        variant=None,
    )

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            InventoryRecordFactory(
                product=product,
                variant=None,
            )


def test_only_one_inventory_record_allowed_per_variant():
    product = ProductFactory()
    variant = ProductVariantFactory(product=product)

    InventoryRecordFactory(
        product=product,
        variant=variant,
    )

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            InventoryRecordFactory(
                product=product,
                variant=variant,
            )


def test_available_quantity_is_quantity_on_hand_minus_reserved():
    record = InventoryRecordFactory(
        quantity_on_hand=20,
        quantity_reserved=7,
    )

    assert record.available_quantity == 13


def test_is_low_stock_true_when_available_quantity_at_or_below_threshold():
    record = InventoryRecordFactory(
        quantity_on_hand=10,
        quantity_reserved=6,
        low_stock_threshold=4,
    )

    assert record.available_quantity == 4
    assert record.is_low_stock is True


def test_is_low_stock_false_when_track_inventory_disabled():
    record = InventoryRecordFactory(
        quantity_on_hand=2,
        quantity_reserved=0,
        low_stock_threshold=5,
        track_inventory=False,
    )

    assert record.is_low_stock is False


def test_increase_stock_updates_on_hand_and_creates_movement():
    admin = AdminUserFactory()

    record = InventoryRecordFactory(
        quantity_on_hand=10,
        quantity_reserved=2,
    )

    movement = record.increase_stock(
        5,
        reason="Restock",
        reference="RESTOCK-001",
        created_by=admin,
    )

    record.refresh_from_db()

    assert record.quantity_on_hand == 15
    assert record.quantity_reserved == 2
    assert record.available_quantity == 13

    assert movement.movement_type == StockMovement.MovementType.IN
    assert movement.quantity == 5
    assert movement.before_on_hand == 10
    assert movement.after_on_hand == 15
    assert movement.before_reserved == 2
    assert movement.after_reserved == 2
    assert movement.reason == "Restock"
    assert movement.reference == "RESTOCK-001"
    assert movement.created_by == admin


def test_decrease_stock_updates_on_hand_and_creates_movement():
    admin = AdminUserFactory()

    record = InventoryRecordFactory(
        quantity_on_hand=20,
        quantity_reserved=5,
    )

    movement = record.decrease_stock(
        10,
        reason="Manual stock decrease",
        reference="OUT-001",
        created_by=admin,
    )

    record.refresh_from_db()

    assert record.quantity_on_hand == 10
    assert record.quantity_reserved == 5
    assert record.available_quantity == 5

    assert movement.movement_type == StockMovement.MovementType.OUT
    assert movement.quantity == 10
    assert movement.before_on_hand == 20
    assert movement.after_on_hand == 10
    assert movement.before_reserved == 5
    assert movement.after_reserved == 5


def test_decrease_stock_cannot_exceed_available_quantity():
    record = InventoryRecordFactory(
        quantity_on_hand=10,
        quantity_reserved=6,
    )

    with pytest.raises(ValidationError):
        record.decrease_stock(5)

    record.refresh_from_db()

    assert record.quantity_on_hand == 10
    assert record.quantity_reserved == 6
    assert record.movements.count() == 0


def test_reserve_stock_updates_reserved_and_creates_movement():
    record = InventoryRecordFactory(
        quantity_on_hand=20,
        quantity_reserved=3,
    )

    movement = record.reserve_stock(
        5,
        reason="Cart reservation",
        reference="CART-001",
    )

    record.refresh_from_db()

    assert record.quantity_on_hand == 20
    assert record.quantity_reserved == 8
    assert record.available_quantity == 12

    assert movement.movement_type == StockMovement.MovementType.RESERVE
    assert movement.quantity == 5
    assert movement.before_on_hand == 20
    assert movement.after_on_hand == 20
    assert movement.before_reserved == 3
    assert movement.after_reserved == 8


def test_reserve_stock_cannot_exceed_available_quantity():
    record = InventoryRecordFactory(
        quantity_on_hand=10,
        quantity_reserved=8,
    )

    with pytest.raises(ValidationError):
        record.reserve_stock(3)

    record.refresh_from_db()

    assert record.quantity_reserved == 8
    assert record.movements.count() == 0


def test_release_reservation_updates_reserved_and_creates_movement():
    record = InventoryRecordFactory(
        quantity_on_hand=20,
        quantity_reserved=8,
    )

    movement = record.release_reservation(
        3,
        reason="Cart expired",
        reference="CART-EXPIRED-001",
    )

    record.refresh_from_db()

    assert record.quantity_on_hand == 20
    assert record.quantity_reserved == 5
    assert record.available_quantity == 15

    assert movement.movement_type == StockMovement.MovementType.RELEASE
    assert movement.quantity == 3
    assert movement.before_reserved == 8
    assert movement.after_reserved == 5


def test_release_reservation_cannot_exceed_reserved_quantity():
    record = InventoryRecordFactory(
        quantity_on_hand=20,
        quantity_reserved=4,
    )

    with pytest.raises(ValidationError):
        record.release_reservation(5)

    record.refresh_from_db()

    assert record.quantity_reserved == 4
    assert record.movements.count() == 0


def test_commit_reservation_updates_on_hand_reserved_and_creates_sale_movement():
    record = InventoryRecordFactory(
        quantity_on_hand=20,
        quantity_reserved=8,
    )

    movement = record.commit_reservation(
        5,
        reason="Order paid",
        reference="ORDER-001",
    )

    record.refresh_from_db()

    assert record.quantity_on_hand == 15
    assert record.quantity_reserved == 3
    assert record.available_quantity == 12

    assert movement.movement_type == StockMovement.MovementType.SALE
    assert movement.quantity == 5
    assert movement.before_on_hand == 20
    assert movement.after_on_hand == 15
    assert movement.before_reserved == 8
    assert movement.after_reserved == 3


def test_commit_reservation_cannot_exceed_reserved_quantity():
    record = InventoryRecordFactory(
        quantity_on_hand=20,
        quantity_reserved=3,
    )

    with pytest.raises(ValidationError):
        record.commit_reservation(4)

    record.refresh_from_db()

    assert record.quantity_on_hand == 20
    assert record.quantity_reserved == 3
    assert record.movements.count() == 0


def test_commit_reservation_cannot_exceed_quantity_on_hand():
    record = InventoryRecordFactory(
        quantity_on_hand=5,
        quantity_reserved=5,
    )

    InventoryRecord.objects.filter(pk=record.pk).update(
        quantity_on_hand=3,
        quantity_reserved=5,
    )

    record.refresh_from_db()

    with pytest.raises(ValidationError):
        record.commit_reservation(4)

    record.refresh_from_db()

    assert record.quantity_on_hand == 3
    assert record.quantity_reserved == 5
    assert record.movements.count() == 0


def test_stock_operation_rejects_zero_quantity():
    record = InventoryRecordFactory()

    with pytest.raises(ValidationError):
        record.increase_stock(0)


def test_stock_operation_rejects_negative_quantity():
    record = InventoryRecordFactory()

    with pytest.raises(ValidationError):
        record.reserve_stock(-1)


def test_stock_operation_rejects_non_integer_quantity():
    record = InventoryRecordFactory()

    with pytest.raises(ValidationError):
        record.decrease_stock("5")


def test_stock_movement_quantity_must_be_positive():
    record = InventoryRecordFactory()

    with pytest.raises(ValidationError):
        StockMovement.objects.create(
            inventory_record=record,
            movement_type=StockMovement.MovementType.IN,
            quantity=0,
            before_on_hand=0,
            after_on_hand=0,
            before_reserved=0,
            after_reserved=0,
        )


def test_stock_movement_str_returns_type_and_quantity():
    movement = StockMovementFactory(
        movement_type=StockMovement.MovementType.IN,
        quantity=10,
    )

    assert str(movement) == "IN - 10"


def test_inventory_record_str_for_product_level():
    product = ProductFactory(name="Simple Product")

    record = InventoryRecordFactory(
        product=product,
        variant=None,
    )

    assert str(record) == "Simple Product"


def test_inventory_record_str_for_variant_level():
    product = ProductFactory(name="Shoes")
    variant = ProductVariantFactory(
        product=product,
        name="Size 42",
    )

    record = InventoryRecordFactory(
        product=product,
        variant=variant,
    )

    assert str(record) == "Shoes - Size 42"


def test_stock_movements_keep_before_and_after_snapshots_across_multiple_operations():
    record = InventoryRecordFactory(
        quantity_on_hand=100,
        quantity_reserved=0,
    )

    record.reserve_stock(
        10,
        reason="Cart reserve",
        reference="CART-100",
    )

    record.commit_reservation(
        4,
        reason="Order sale",
        reference="ORDER-100",
    )

    record.release_reservation(
        6,
        reason="Remaining reservation released",
        reference="CART-100-RELEASE",
    )

    movements = list(record.movements.order_by("created_at"))

    assert len(movements) == 3

    reserve_movement = movements[0]
    sale_movement = movements[1]
    release_movement = movements[2]

    assert reserve_movement.movement_type == StockMovement.MovementType.RESERVE
    assert reserve_movement.before_on_hand == 100
    assert reserve_movement.after_on_hand == 100
    assert reserve_movement.before_reserved == 0
    assert reserve_movement.after_reserved == 10

    assert sale_movement.movement_type == StockMovement.MovementType.SALE
    assert sale_movement.before_on_hand == 100
    assert sale_movement.after_on_hand == 96
    assert sale_movement.before_reserved == 10
    assert sale_movement.after_reserved == 6

    assert release_movement.movement_type == StockMovement.MovementType.RELEASE
    assert release_movement.before_on_hand == 96
    assert release_movement.after_on_hand == 96
    assert release_movement.before_reserved == 6
    assert release_movement.after_reserved == 0

    record.refresh_from_db()

    assert record.quantity_on_hand == 96
    assert record.quantity_reserved == 0
    assert record.available_quantity == 96