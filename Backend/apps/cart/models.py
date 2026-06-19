import uuid
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import Q, Sum
from django.utils import timezone

from apps.catalog.models import Product, ProductVariant
from apps.inventory.models import InventoryRecord
from apps.vendors.models import Vendor


class Cart(models.Model):
    """
    Customer shopping cart.

    Rules:
    - Only CUSTOMER users can own carts.
    - One active cart is allowed per customer.
    - Converted carts should not be modified.
    """

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        CONVERTED = "CONVERTED", "Converted"
        ABANDONED = "ABANDONED", "Abandoned"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="carts",
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.ACTIVE,
        db_index=True,
    )

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    converted_at = models.DateTimeField(null=True, blank=True)
    abandoned_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["customer", "status"]),
            models.Index(fields=["status", "created_at"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["customer"],
                condition=Q(status="ACTIVE"),
                name="cart_one_active_cart_per_customer",
            ),
        ]

    @property
    def item_count(self):
        return self.items.count()

    @property
    def total_quantity(self):
        result = self.items.aggregate(total=Sum("quantity"))
        return result["total"] or 0

    @property
    def subtotal_amount(self):
        total = Decimal("0.00")

        for item in self.items.all():
            total += item.line_total

        return total.quantize(Decimal("0.01"))

    def clean(self):
        if self.customer_id:
            customer_role = getattr(self.customer, "role", None)

            if customer_role != "CUSTOMER":
                raise ValidationError(
                    {"customer": "Only customer users can own carts."}
                )

        if self.status == self.Status.CONVERTED and not self.converted_at:
            self.converted_at = timezone.now()

        if self.status == self.Status.ABANDONED and not self.abandoned_at:
            self.abandoned_at = timezone.now()

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    def ensure_active(self):
        if self.status != self.Status.ACTIVE:
            raise ValidationError(
                {"cart": "Only active carts can be modified."}
            )

    def add_item(self, product, quantity=1, variant=None):
        """
        Adds item to cart or increases quantity when same item already exists.
        """
        self.ensure_active()

        if quantity <= 0:
            raise ValidationError(
                {"quantity": "Quantity must be greater than zero."}
            )

        with transaction.atomic():
            existing_item = CartItem.objects.filter(
                cart=self,
                product=product,
                variant=variant,
            ).first()

            if existing_item:
                existing_item.quantity += quantity
                existing_item.save()
                return existing_item

            return CartItem.objects.create(
                cart=self,
                product=product,
                variant=variant,
                quantity=quantity,
            )

    def clear(self):
        self.ensure_active()
        self.items.all().delete()

    def mark_converted(self):
        self.status = self.Status.CONVERTED
        self.converted_at = timezone.now()
        self.save(update_fields=["status", "converted_at", "updated_at"])

    def mark_abandoned(self):
        self.status = self.Status.ABANDONED
        self.abandoned_at = timezone.now()
        self.save(update_fields=["status", "abandoned_at", "updated_at"])

    def __str__(self):
        return f"Cart {self.id} - {self.customer}"


class CartItem(models.Model):
    """
    Product line item inside cart.

    Rules:
    - Cart must be active.
    - Product must be ACTIVE.
    - Product vendor must be APPROVED.
    - Category must be active.
    - Brand must be active if selected.
    - Variant must belong to selected product.
    - Variant must be active.
    - Inventory availability is checked before save.
    - Unit price is stored as a snapshot when item is created.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    cart = models.ForeignKey(
        Cart,
        on_delete=models.CASCADE,
        related_name="items",
    )

    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="cart_items",
    )

    variant = models.ForeignKey(
        ProductVariant,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="cart_items",
    )

    quantity = models.PositiveIntegerField(default=1)

    unit_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
    )

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["cart", "product"]),
            models.Index(fields=["cart", "variant"]),
            models.Index(fields=["product"]),
            models.Index(fields=["variant"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["cart", "product"],
                condition=Q(variant__isnull=True),
                name="cart_unique_product_level_item",
            ),
            models.UniqueConstraint(
                fields=["cart", "variant"],
                condition=Q(variant__isnull=False),
                name="cart_unique_variant_level_item",
            ),
            models.CheckConstraint(
                condition=Q(quantity__gt=0),
                name="cart_item_quantity_positive",
            ),
            models.CheckConstraint(
                condition=Q(unit_price__gte=0),
                name="cart_item_unit_price_non_negative",
            ),
        ]

    @property
    def line_total(self):
        return (self.unit_price * self.quantity).quantize(Decimal("0.01"))

    def get_current_unit_price(self):
        if self.variant_id:
            return self.variant.price

        return self.product.base_price

    def get_inventory_record(self):
        if self.variant_id:
            return InventoryRecord.objects.filter(
                product=self.product,
                variant=self.variant,
            ).first()

        return InventoryRecord.objects.filter(
            product=self.product,
            variant__isnull=True,
        ).first()

    def clean(self):
        if self.cart_id:
            self.cart.ensure_active()

        if self.quantity <= 0:
            raise ValidationError(
                {"quantity": "Quantity must be greater than zero."}
            )

        if not self.product_id:
            raise ValidationError({"product": "Product is required."})

        if self.product.status != Product.Status.ACTIVE:
            raise ValidationError(
                {"product": "Only active products can be added to cart."}
            )

        if self.product.vendor.status != Vendor.Status.APPROVED:
            raise ValidationError(
                {"product": "Product vendor must be approved."}
            )

        if not self.product.category.is_active:
            raise ValidationError(
                {"product": "Product category must be active."}
            )

        if self.product.brand_id and not self.product.brand.is_active:
            raise ValidationError(
                {"product": "Product brand must be active."}
            )

        if self.variant_id:
            if self.variant.product_id != self.product_id:
                raise ValidationError(
                    {"variant": "Variant must belong to the selected product."}
                )

            if not self.variant.is_active:
                raise ValidationError(
                    {"variant": "Only active variants can be added to cart."}
                )

        inventory_record = self.get_inventory_record()

        if not inventory_record:
            raise ValidationError(
                {"inventory": "Inventory record is required for this product."}
            )

        if not inventory_record.track_inventory:
            return

        if inventory_record.allow_backorder:
            return

        if inventory_record.available_quantity < self.quantity:
            raise ValidationError(
                {"quantity": "Requested quantity exceeds available stock."}
            )

    def save(self, *args, **kwargs):
        if self._state.adding:
            self.unit_price = self.get_current_unit_price()

        self.clean()
        super().save(*args, **kwargs)

    def __str__(self):
        if self.variant:
            return f"{self.product.name} - {self.variant.name} x {self.quantity}"

        return f"{self.product.name} x {self.quantity}"