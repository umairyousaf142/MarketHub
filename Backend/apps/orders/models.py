import uuid
from decimal import Decimal
from secrets import token_hex

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import Q, Sum
from django.utils import timezone

from apps.cart.models import Cart, CartItem
from apps.catalog.models import Product, ProductVariant
from apps.inventory.models import InventoryRecord
from apps.vendors.models import Vendor


def generate_order_number():
    date_part = timezone.now().strftime("%Y%m%d")

    while True:
        random_part = token_hex(4).upper()
        order_number = f"MH-{date_part}-{random_part}"

        if not Order.objects.filter(order_number=order_number).exists():
            return order_number


class Order(models.Model):
    """
    Customer order.

    Rules:
    - Only CUSTOMER users can own orders.
    - Order can be created from an active cart.
    - Cart items are copied into order item snapshots.
    - Inventory can be reserved, committed, or released.
    - VendorOrder records are created per vendor.
    """

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        CONFIRMED = "CONFIRMED", "Confirmed"
        PROCESSING = "PROCESSING", "Processing"
        SHIPPED = "SHIPPED", "Shipped"
        DELIVERED = "DELIVERED", "Delivered"
        CANCELLED = "CANCELLED", "Cancelled"

    class PaymentStatus(models.TextChoices):
        PENDING = "PENDING", "Pending"
        PAID = "PAID", "Paid"
        FAILED = "FAILED", "Failed"
        REFUNDED = "REFUNDED", "Refunded"

    class InventoryStatus(models.TextChoices):
        NOT_RESERVED = "NOT_RESERVED", "Not Reserved"
        RESERVED = "RESERVED", "Reserved"
        COMMITTED = "COMMITTED", "Committed"
        RELEASED = "RELEASED", "Released"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    order_number = models.CharField(
        max_length=40,
        unique=True,
        db_index=True,
        blank=True,
    )

    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="orders",
    )

    source_cart = models.OneToOneField(
        Cart,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="order",
    )

    status = models.CharField(
        max_length=30,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )

    payment_status = models.CharField(
        max_length=30,
        choices=PaymentStatus.choices,
        default=PaymentStatus.PENDING,
        db_index=True,
    )

    inventory_status = models.CharField(
        max_length=30,
        choices=InventoryStatus.choices,
        default=InventoryStatus.NOT_RESERVED,
        db_index=True,
    )

    subtotal_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
    )

    shipping_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
    )

    tax_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
    )

    discount_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
    )

    total_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
    )

    shipping_address = models.JSONField(default=dict, blank=True)
    billing_address = models.JSONField(default=dict, blank=True)

    notes = models.TextField(blank=True)

    placed_at = models.DateTimeField(default=timezone.now, db_index=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["customer", "status"]),
            models.Index(fields=["status", "created_at"]),
            models.Index(fields=["payment_status", "created_at"]),
            models.Index(fields=["inventory_status", "created_at"]),
            models.Index(fields=["order_number"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(subtotal_amount__gte=0),
                name="orders_subtotal_amount_non_negative",
            ),
            models.CheckConstraint(
                condition=Q(shipping_amount__gte=0),
                name="orders_shipping_amount_non_negative",
            ),
            models.CheckConstraint(
                condition=Q(tax_amount__gte=0),
                name="orders_tax_amount_non_negative",
            ),
            models.CheckConstraint(
                condition=Q(discount_amount__gte=0),
                name="orders_discount_amount_non_negative",
            ),
            models.CheckConstraint(
                condition=Q(total_amount__gte=0),
                name="orders_total_amount_non_negative",
            ),
        ]

    @property
    def item_count(self):
        return self.items.count()

    @property
    def total_quantity(self):
        result = self.items.aggregate(total=Sum("quantity"))
        return result["total"] or 0

    def calculate_total_amount(self):
        subtotal = Decimal(str(self.subtotal_amount or "0.00"))
        shipping = Decimal(str(self.shipping_amount or "0.00"))
        tax = Decimal(str(self.tax_amount or "0.00"))
        discount = Decimal(str(self.discount_amount or "0.00"))

        total = subtotal + shipping + tax - discount

        if total < Decimal("0.00"):
            raise ValidationError(
                {"total_amount": "Order total amount cannot be negative."}
            )

        return total.quantize(Decimal("0.01"))

    def clean(self):
        if self.customer_id:
            customer_role = getattr(self.customer, "role", None)

            if customer_role != "CUSTOMER":
                raise ValidationError(
                    {"customer": "Only customer users can own orders."}
                )

        if self.source_cart_id:
            if self.source_cart.customer_id != self.customer_id:
                raise ValidationError(
                    {"source_cart": "Source cart must belong to the order customer."}
                )

        self.subtotal_amount = Decimal(str(self.subtotal_amount or "0.00")).quantize(
            Decimal("0.01")
        )
        self.shipping_amount = Decimal(str(self.shipping_amount or "0.00")).quantize(
            Decimal("0.01")
        )
        self.tax_amount = Decimal(str(self.tax_amount or "0.00")).quantize(
            Decimal("0.01")
        )
        self.discount_amount = Decimal(str(self.discount_amount or "0.00")).quantize(
            Decimal("0.01")
        )
        self.total_amount = self.calculate_total_amount()

        if self.status == self.Status.CANCELLED and not self.cancelled_at:
            self.cancelled_at = timezone.now()

        if self.payment_status == self.PaymentStatus.PAID and not self.paid_at:
            self.paid_at = timezone.now()

    def save(self, *args, **kwargs):
        if not self.order_number:
            self.order_number = generate_order_number()

        self.clean()
        super().save(*args, **kwargs)

    @classmethod
    def create_from_cart(
        cls,
        cart,
        *,
        shipping_address=None,
        billing_address=None,
        shipping_amount=Decimal("0.00"),
        tax_amount=Decimal("0.00"),
        discount_amount=Decimal("0.00"),
        notes="",
    ):
        with transaction.atomic():
            locked_cart = (
                Cart.objects.select_for_update()
                .select_related("customer")
                .prefetch_related(
                    "items",
                    "items__product",
                    "items__product__vendor",
                    "items__variant",
                )
                .get(pk=cart.pk)
            )

            locked_cart.ensure_active()

            cart_items = list(
                locked_cart.items.select_related(
                    "product",
                    "product__vendor",
                    "variant",
                )
            )

            if not cart_items:
                raise ValidationError({"cart": "Cannot create order from an empty cart."})

            order = cls.objects.create(
                customer=locked_cart.customer,
                source_cart=locked_cart,
                subtotal_amount=locked_cart.subtotal_amount,
                shipping_amount=shipping_amount,
                tax_amount=tax_amount,
                discount_amount=discount_amount,
                shipping_address=shipping_address or {},
                billing_address=billing_address or {},
                notes=notes,
            )

            reserved_any_inventory = False

            for cart_item in cart_items:
                inventory_record = cart_item.get_inventory_record()

                if not inventory_record:
                    raise ValidationError(
                        {
                            "inventory": (
                                "Inventory record is required before creating order."
                            )
                        }
                    )

                if (
                    inventory_record.track_inventory
                    and not inventory_record.allow_backorder
                ):
                    inventory_record.reserve_stock(
                        cart_item.quantity,
                        reason="Order stock reservation",
                        reference=order.order_number,
                        created_by=locked_cart.customer,
                    )
                    reserved_any_inventory = True
                    inventory_record.refresh_from_db()

                OrderItem.objects.create_from_cart_item(
                    order=order,
                    cart_item=cart_item,
                    inventory_record=inventory_record,
                )

            vendor_ids = order.items.values_list("vendor_id", flat=True).distinct()

            for vendor_id in vendor_ids:
                vendor_order = VendorOrder.objects.create(
                    order=order,
                    vendor_id=vendor_id,
                )
                vendor_order.recalculate_totals(save=True)

            if reserved_any_inventory:
                order.inventory_status = cls.InventoryStatus.RESERVED
                order.save(update_fields=["inventory_status", "updated_at"])

            locked_cart.mark_converted()

            return order

    def commit_inventory(self):
        if self.inventory_status != self.InventoryStatus.RESERVED:
            raise ValidationError(
                {"inventory_status": "Only reserved inventory can be committed."}
            )

        with transaction.atomic():
            for item in self.items.select_related("inventory_record"):
                if not item.inventory_record:
                    continue

                if (
                    item.inventory_record.track_inventory
                    and not item.inventory_record.allow_backorder
                ):
                    item.inventory_record.commit_reservation(
                        item.quantity,
                        reason="Order inventory committed",
                        reference=self.order_number,
                        created_by=self.customer,
                    )

            self.inventory_status = self.InventoryStatus.COMMITTED
            self.save(update_fields=["inventory_status", "updated_at"])

    def release_inventory(self):
        if self.inventory_status != self.InventoryStatus.RESERVED:
            raise ValidationError(
                {"inventory_status": "Only reserved inventory can be released."}
            )

        with transaction.atomic():
            for item in self.items.select_related("inventory_record"):
                if not item.inventory_record:
                    continue

                if (
                    item.inventory_record.track_inventory
                    and not item.inventory_record.allow_backorder
                ):
                    item.inventory_record.release_reservation(
                        item.quantity,
                        reason="Order inventory released",
                        reference=self.order_number,
                        created_by=self.customer,
                    )

            self.inventory_status = self.InventoryStatus.RELEASED
            self.save(update_fields=["inventory_status", "updated_at"])

    def mark_paid(self, *, commit_inventory=True):
        if commit_inventory and self.inventory_status == self.InventoryStatus.RESERVED:
            self.commit_inventory()

        self.payment_status = self.PaymentStatus.PAID
        self.status = self.Status.CONFIRMED
        self.paid_at = timezone.now()
        self.save(
            update_fields=[
                "payment_status",
                "status",
                "paid_at",
                "updated_at",
            ]
        )

        self.vendor_orders.update(status=VendorOrder.Status.CONFIRMED)

    def cancel(self, *, release_inventory=True):
        if release_inventory and self.inventory_status == self.InventoryStatus.RESERVED:
            self.release_inventory()

        self.status = self.Status.CANCELLED
        self.cancelled_at = timezone.now()
        self.save(
            update_fields=[
                "status",
                "cancelled_at",
                "updated_at",
            ]
        )

        self.vendor_orders.update(status=VendorOrder.Status.CANCELLED)

    def __str__(self):
        return self.order_number


class OrderItemManager(models.Manager):
    def create_from_cart_item(self, *, order, cart_item, inventory_record=None):
        return self.create(
            order=order,
            vendor=cart_item.product.vendor,
            product=cart_item.product,
            variant=cart_item.variant,
            inventory_record=inventory_record,
            product_name=cart_item.product.name,
            product_sku=cart_item.product.sku,
            variant_name=cart_item.variant.name if cart_item.variant else "",
            variant_sku=cart_item.variant.sku if cart_item.variant else "",
            vendor_store_name=cart_item.product.vendor.store_name,
            quantity=cart_item.quantity,
            unit_price=cart_item.unit_price,
        )


class OrderItem(models.Model):
    """
    Snapshot of a cart item at order placement time.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name="items",
    )

    vendor = models.ForeignKey(
        Vendor,
        on_delete=models.PROTECT,
        related_name="order_items",
    )

    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        related_name="order_items",
    )

    variant = models.ForeignKey(
        ProductVariant,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="order_items",
    )

    inventory_record = models.ForeignKey(
        InventoryRecord,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="order_items",
    )

    product_name = models.CharField(max_length=255)
    product_sku = models.CharField(max_length=100)

    variant_name = models.CharField(max_length=255, blank=True)
    variant_sku = models.CharField(max_length=100, blank=True)

    vendor_store_name = models.CharField(max_length=255)

    quantity = models.PositiveIntegerField()

    unit_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
    )

    line_total = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
    )

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    objects = OrderItemManager()

    class Meta:
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["order", "vendor"]),
            models.Index(fields=["vendor", "created_at"]),
            models.Index(fields=["product"]),
            models.Index(fields=["variant"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(quantity__gt=0),
                name="orders_item_quantity_positive",
            ),
            models.CheckConstraint(
                condition=Q(unit_price__gte=0),
                name="orders_item_unit_price_non_negative",
            ),
            models.CheckConstraint(
                condition=Q(line_total__gte=0),
                name="orders_item_line_total_non_negative",
            ),
        ]

    def calculate_line_total(self):
        return (self.unit_price * self.quantity).quantize(Decimal("0.01"))

    def clean(self):
        if self.quantity <= 0:
            raise ValidationError(
                {"quantity": "Quantity must be greater than zero."}
            )

        if self.unit_price < Decimal("0.00"):
            raise ValidationError(
                {"unit_price": "Unit price cannot be negative."}
            )

        if self.variant_id and self.variant.product_id != self.product_id:
            raise ValidationError(
                {"variant": "Variant must belong to the selected product."}
            )

        if self.vendor_id and self.product_id:
            if self.vendor_id != self.product.vendor_id:
                raise ValidationError(
                    {"vendor": "Vendor must match the selected product vendor."}
                )

    def save(self, *args, **kwargs):
        if self.product_id and not self.vendor_id:
            self.vendor = self.product.vendor

        if self.product_id and not self.product_name:
            self.product_name = self.product.name

        if self.product_id and not self.product_sku:
            self.product_sku = self.product.sku

        if self.product_id and not self.vendor_store_name:
            self.vendor_store_name = self.product.vendor.store_name

        if self.variant_id:
            if not self.variant_name:
                self.variant_name = self.variant.name

            if not self.variant_sku:
                self.variant_sku = self.variant.sku

        self.line_total = self.calculate_line_total()

        self.clean()
        super().save(*args, **kwargs)

    def __str__(self):
        if self.variant_name:
            return f"{self.product_name} - {self.variant_name} x {self.quantity}"

        return f"{self.product_name} x {self.quantity}"


class VendorOrder(models.Model):
    """
    Vendor-level sub-order foundation.
    One customer order can produce multiple vendor orders.
    """

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        CONFIRMED = "CONFIRMED", "Confirmed"
        PROCESSING = "PROCESSING", "Processing"
        SHIPPED = "SHIPPED", "Shipped"
        DELIVERED = "DELIVERED", "Delivered"
        CANCELLED = "CANCELLED", "Cancelled"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name="vendor_orders",
    )

    vendor = models.ForeignKey(
        Vendor,
        on_delete=models.PROTECT,
        related_name="vendor_orders",
    )

    status = models.CharField(
        max_length=30,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )

    subtotal_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
    )

    item_count = models.PositiveIntegerField(default=0)
    total_quantity = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["vendor", "status"]),
            models.Index(fields=["order", "vendor"]),
            models.Index(fields=["status", "created_at"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["order", "vendor"],
                name="orders_unique_vendor_order_per_order",
            ),
            models.CheckConstraint(
                condition=Q(subtotal_amount__gte=0),
                name="orders_vendor_order_subtotal_non_negative",
            ),
            models.CheckConstraint(
                condition=Q(item_count__gte=0),
                name="orders_vendor_order_item_count_non_negative",
            ),
            models.CheckConstraint(
                condition=Q(total_quantity__gte=0),
                name="orders_vendor_order_total_quantity_non_negative",
            ),
        ]

    def clean(self):
        if self.order_id and self.vendor_id:
            if not self.order.items.filter(vendor=self.vendor).exists():
                raise ValidationError(
                    {
                        "vendor": (
                            "Vendor order can only be created for vendors "
                            "with items in this order."
                        )
                    }
                )

    def recalculate_totals(self, *, save=False):
        items = self.order.items.filter(vendor=self.vendor)

        subtotal = Decimal("0.00")
        total_quantity = 0
        item_count = 0

        for item in items:
            subtotal += item.line_total
            total_quantity += item.quantity
            item_count += 1

        self.subtotal_amount = subtotal.quantize(Decimal("0.01"))
        self.total_quantity = total_quantity
        self.item_count = item_count

        if save:
            self.save(
                update_fields=[
                    "subtotal_amount",
                    "total_quantity",
                    "item_count",
                    "updated_at",
                ]
            )

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.order.order_number} - {self.vendor.store_name}"