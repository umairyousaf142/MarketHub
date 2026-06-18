import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import Q

from apps.catalog.models import Product, ProductVariant
from apps.vendors.models import Vendor


class InventoryRecord(models.Model):
    """
    Inventory record for stock tracking.

    Rules:
    - Inventory can be tracked at product level or variant level.
    - If variant is provided, it must belong to the selected product.
    - One product-level inventory record is allowed when variant is null.
    - One inventory record is allowed per variant.
    - Reserved quantity cannot exceed quantity on hand.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="inventory_records",
    )

    variant = models.OneToOneField(
        ProductVariant,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="inventory_record",
    )

    quantity_on_hand = models.PositiveIntegerField(default=0)
    quantity_reserved = models.PositiveIntegerField(default=0)

    low_stock_threshold = models.PositiveIntegerField(default=5)

    track_inventory = models.BooleanField(default=True, db_index=True)
    allow_backorder = models.BooleanField(default=False, db_index=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["product__name", "variant__name"]
        indexes = [
            models.Index(fields=["product", "track_inventory"]),
            models.Index(fields=["variant", "track_inventory"]),
            models.Index(fields=["quantity_on_hand"]),
            models.Index(fields=["quantity_reserved"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["product"],
                condition=Q(variant__isnull=True),
                name="inventory_one_product_level_record",
            ),
            models.CheckConstraint(
                condition=Q(quantity_on_hand__gte=0),
                name="inventory_quantity_on_hand_non_negative",
            ),
            models.CheckConstraint(
                condition=Q(quantity_reserved__gte=0),
                name="inventory_quantity_reserved_non_negative",
            ),
            models.CheckConstraint(
                condition=Q(low_stock_threshold__gte=0),
                name="inventory_low_stock_threshold_non_negative",
            ),
        ]

    @property
    def available_quantity(self):
        return self.quantity_on_hand - self.quantity_reserved

    @property
    def is_low_stock(self):
        if not self.track_inventory:
            return False

        return self.available_quantity <= self.low_stock_threshold

    def clean(self):
        if self.variant_id and self.product_id:
            if self.variant.product_id != self.product_id:
                raise ValidationError(
                    {"variant": "Variant must belong to the selected product."}
                )

        if self.product_id:
            if self.product.vendor.status != Vendor.Status.APPROVED:
                raise ValidationError(
                    {
                        "product": (
                            "Inventory can only be managed for products "
                            "owned by approved vendors."
                        )
                    }
                )

        if self.quantity_reserved > self.quantity_on_hand:
            raise ValidationError(
                {
                    "quantity_reserved": (
                        "Reserved quantity cannot exceed quantity on hand."
                    )
                }
            )

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    def _validate_quantity(self, quantity):
        if quantity is None:
            raise ValidationError({"quantity": "Quantity is required."})

        if not isinstance(quantity, int):
            raise ValidationError({"quantity": "Quantity must be an integer."})

        if quantity <= 0:
            raise ValidationError({"quantity": "Quantity must be greater than zero."})

    def _sync_from_locked_record(self, record):
        self.quantity_on_hand = record.quantity_on_hand
        self.quantity_reserved = record.quantity_reserved
        self.updated_at = record.updated_at

    def _create_movement(
        self,
        *,
        record,
        movement_type,
        quantity,
        before_on_hand,
        before_reserved,
        reason="",
        reference="",
        created_by=None,
    ):
        return StockMovement.objects.create(
            inventory_record=record,
            movement_type=movement_type,
            quantity=quantity,
            before_on_hand=before_on_hand,
            after_on_hand=record.quantity_on_hand,
            before_reserved=before_reserved,
            after_reserved=record.quantity_reserved,
            reason=reason,
            reference=reference,
            created_by=created_by,
        )

    def increase_stock(
        self,
        quantity,
        *,
        reason="Stock increase",
        reference="",
        created_by=None,
    ):
        self._validate_quantity(quantity)

        with transaction.atomic():
            record = InventoryRecord.objects.select_for_update().get(pk=self.pk)

            before_on_hand = record.quantity_on_hand
            before_reserved = record.quantity_reserved

            record.quantity_on_hand += quantity
            record.save(update_fields=["quantity_on_hand", "updated_at"])

            movement = self._create_movement(
                record=record,
                movement_type=StockMovement.MovementType.IN,
                quantity=quantity,
                before_on_hand=before_on_hand,
                before_reserved=before_reserved,
                reason=reason,
                reference=reference,
                created_by=created_by,
            )

        self._sync_from_locked_record(record)

        return movement

    def decrease_stock(
        self,
        quantity,
        *,
        reason="Stock decrease",
        reference="",
        created_by=None,
    ):
        self._validate_quantity(quantity)

        with transaction.atomic():
            record = InventoryRecord.objects.select_for_update().get(pk=self.pk)

            if record.available_quantity < quantity:
                raise ValidationError(
                    {"quantity": "Not enough available stock to decrease."}
                )

            before_on_hand = record.quantity_on_hand
            before_reserved = record.quantity_reserved

            record.quantity_on_hand -= quantity
            record.save(update_fields=["quantity_on_hand", "updated_at"])

            movement = self._create_movement(
                record=record,
                movement_type=StockMovement.MovementType.OUT,
                quantity=quantity,
                before_on_hand=before_on_hand,
                before_reserved=before_reserved,
                reason=reason,
                reference=reference,
                created_by=created_by,
            )

        self._sync_from_locked_record(record)

        return movement

    def reserve_stock(
        self,
        quantity,
        *,
        reason="Stock reserved",
        reference="",
        created_by=None,
    ):
        self._validate_quantity(quantity)

        with transaction.atomic():
            record = InventoryRecord.objects.select_for_update().get(pk=self.pk)

            if record.available_quantity < quantity:
                raise ValidationError(
                    {"quantity": "Not enough available stock to reserve."}
                )

            before_on_hand = record.quantity_on_hand
            before_reserved = record.quantity_reserved

            record.quantity_reserved += quantity
            record.save(update_fields=["quantity_reserved", "updated_at"])

            movement = self._create_movement(
                record=record,
                movement_type=StockMovement.MovementType.RESERVE,
                quantity=quantity,
                before_on_hand=before_on_hand,
                before_reserved=before_reserved,
                reason=reason,
                reference=reference,
                created_by=created_by,
            )

        self._sync_from_locked_record(record)

        return movement

    def release_reservation(
        self,
        quantity,
        *,
        reason="Reservation released",
        reference="",
        created_by=None,
    ):
        self._validate_quantity(quantity)

        with transaction.atomic():
            record = InventoryRecord.objects.select_for_update().get(pk=self.pk)

            if record.quantity_reserved < quantity:
                raise ValidationError(
                    {"quantity": "Cannot release more than reserved quantity."}
                )

            before_on_hand = record.quantity_on_hand
            before_reserved = record.quantity_reserved

            record.quantity_reserved -= quantity
            record.save(update_fields=["quantity_reserved", "updated_at"])

            movement = self._create_movement(
                record=record,
                movement_type=StockMovement.MovementType.RELEASE,
                quantity=quantity,
                before_on_hand=before_on_hand,
                before_reserved=before_reserved,
                reason=reason,
                reference=reference,
                created_by=created_by,
            )

        self._sync_from_locked_record(record)

        return movement

    def commit_reservation(
        self,
        quantity,
        *,
        reason="Reserved stock committed",
        reference="",
        created_by=None,
    ):
        self._validate_quantity(quantity)

        with transaction.atomic():
            record = InventoryRecord.objects.select_for_update().get(pk=self.pk)

            if record.quantity_reserved < quantity:
                raise ValidationError(
                    {"quantity": "Cannot commit more than reserved quantity."}
                )

            if record.quantity_on_hand < quantity:
                raise ValidationError(
                    {"quantity": "Cannot commit more than quantity on hand."}
                )

            before_on_hand = record.quantity_on_hand
            before_reserved = record.quantity_reserved

            record.quantity_reserved -= quantity
            record.quantity_on_hand -= quantity
            record.save(
                update_fields=[
                    "quantity_reserved",
                    "quantity_on_hand",
                    "updated_at",
                ]
            )

            movement = self._create_movement(
                record=record,
                movement_type=StockMovement.MovementType.SALE,
                quantity=quantity,
                before_on_hand=before_on_hand,
                before_reserved=before_reserved,
                reason=reason,
                reference=reference,
                created_by=created_by,
            )

        self._sync_from_locked_record(record)

        return movement

    def __str__(self):
        if self.variant:
            return f"{self.product.name} - {self.variant.name}"

        return self.product.name


class StockMovement(models.Model):
    """
    Audit trail for inventory changes.

    Every stock mutation should create a StockMovement record.
    This model should not be manually edited in normal workflows.
    """

    class MovementType(models.TextChoices):
        IN = "IN", "Stock In"
        OUT = "OUT", "Stock Out"
        RESERVE = "RESERVE", "Reserve"
        RELEASE = "RELEASE", "Release"
        SALE = "SALE", "Sale"
        ADJUSTMENT = "ADJUSTMENT", "Adjustment"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    inventory_record = models.ForeignKey(
        InventoryRecord,
        on_delete=models.CASCADE,
        related_name="movements",
    )

    movement_type = models.CharField(
        max_length=30,
        choices=MovementType.choices,
        db_index=True,
    )

    quantity = models.PositiveIntegerField()

    before_on_hand = models.PositiveIntegerField()
    after_on_hand = models.PositiveIntegerField()

    before_reserved = models.PositiveIntegerField()
    after_reserved = models.PositiveIntegerField()

    reason = models.CharField(max_length=255, blank=True)
    reference = models.CharField(max_length=120, blank=True, db_index=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="stock_movements",
    )

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["inventory_record", "created_at"]),
            models.Index(fields=["movement_type", "created_at"]),
            models.Index(fields=["reference"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(quantity__gt=0),
                name="inventory_stock_movement_quantity_positive",
            ),
            models.CheckConstraint(
                condition=Q(before_on_hand__gte=0),
                name="inventory_before_on_hand_non_negative",
            ),
            models.CheckConstraint(
                condition=Q(after_on_hand__gte=0),
                name="inventory_after_on_hand_non_negative",
            ),
            models.CheckConstraint(
                condition=Q(before_reserved__gte=0),
                name="inventory_before_reserved_non_negative",
            ),
            models.CheckConstraint(
                condition=Q(after_reserved__gte=0),
                name="inventory_after_reserved_non_negative",
            ),
        ]

    def clean(self):
        if self.quantity <= 0:
            raise ValidationError({"quantity": "Quantity must be greater than zero."})

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.movement_type} - {self.quantity}"