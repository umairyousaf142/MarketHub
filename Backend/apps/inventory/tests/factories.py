import factory

from apps.accounts.tests.factories import AdminUserFactory
from apps.catalog.tests.factories import ProductFactory
from apps.inventory.models import InventoryRecord, StockMovement


class InventoryRecordFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = InventoryRecord

    product = factory.SubFactory(ProductFactory)
    variant = None

    quantity_on_hand = 100
    quantity_reserved = 0

    low_stock_threshold = 5

    track_inventory = True
    allow_backorder = False


class StockMovementFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = StockMovement

    inventory_record = factory.SubFactory(InventoryRecordFactory)
    movement_type = StockMovement.MovementType.IN
    quantity = 10

    before_on_hand = 0
    after_on_hand = 10

    before_reserved = 0
    after_reserved = 0

    reason = "Test stock movement"
    reference = "TEST-REF"
    created_by = factory.SubFactory(AdminUserFactory)