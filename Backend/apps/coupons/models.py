import uuid
from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import Q
from django.db.models.functions import Lower
from django.utils import timezone

from apps.catalog.models import Category
from apps.orders.models import Order
from apps.vendors.models import Vendor


MONEY_QUANT = Decimal("0.01")


def normalize_coupon_code(code):
    return str(code or "").strip().upper()


def normalize_money(value):
    return Decimal(str(value or "0.00")).quantize(
        MONEY_QUANT,
        rounding=ROUND_HALF_UP,
    )


class Coupon(models.Model):
    class Type(models.TextChoices):
        PERCENTAGE = "PERCENTAGE", "Percentage"
        FIXED = "FIXED", "Fixed"

    class Scope(models.TextChoices):
        GLOBAL = "GLOBAL", "Global"
        VENDOR = "VENDOR", "Vendor"
        CATEGORY = "CATEGORY", "Category"

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    code = models.CharField(
        max_length=80,
        unique=True,
        db_index=True,
    )

    type = models.CharField(
        max_length=20,
        choices=Type.choices,
    )

    value = models.DecimalField(
        max_digits=10,
        decimal_places=2,
    )

    max_discount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
    )

    scope = models.CharField(
        max_length=20,
        choices=Scope.choices,
        default=Scope.GLOBAL,
        db_index=True,
    )

    vendor = models.ForeignKey(
        Vendor,
        on_delete=models.PROTECT,
        related_name="coupons",
        null=True,
        blank=True,
    )

    category = models.ForeignKey(
        Category,
        on_delete=models.PROTECT,
        related_name="coupons",
        null=True,
        blank=True,
    )

    min_order_value = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
    )

    usage_limit = models.PositiveIntegerField(
        null=True,
        blank=True,
    )

    per_user_limit = models.PositiveIntegerField(
        default=1,
    )

    valid_from = models.DateTimeField()
    valid_until = models.DateTimeField()

    is_active = models.BooleanField(
        default=True,
        db_index=True,
    )

    class Meta:
        ordering = ["code"]
        indexes = [
            models.Index(fields=["code"]),
            models.Index(fields=["scope", "is_active"]),
            models.Index(fields=["valid_from", "valid_until"]),
            models.Index(fields=["vendor", "is_active"]),
            models.Index(fields=["category", "is_active"]),
        ]
        constraints = [
            models.UniqueConstraint(
                Lower("code"),
                name="coupons_coupon_code_ci_unique",
            ),
            models.CheckConstraint(
                condition=Q(value__gt=0),
                name="coupons_coupon_value_positive",
            ),
            models.CheckConstraint(
                condition=Q(min_order_value__gte=0),
                name="coupons_coupon_min_order_non_negative",
            ),
            models.CheckConstraint(
                condition=Q(per_user_limit__gt=0),
                name="coupons_coupon_per_user_limit_positive",
            ),
        ]

    def __str__(self):
        return self.code

    def clean(self):
        self.code = normalize_coupon_code(self.code)

        if not self.code:
            raise ValidationError({"code": "Coupon code is required."})

        if self.value <= Decimal("0.00"):
            raise ValidationError({"value": "Coupon value must be greater than zero."})

        if self.max_discount is not None and self.max_discount <= Decimal("0.00"):
            raise ValidationError(
                {"max_discount": "Max discount must be greater than zero."}
            )

        if self.min_order_value < Decimal("0.00"):
            raise ValidationError(
                {"min_order_value": "Minimum order value cannot be negative."}
            )

        if self.per_user_limit <= 0:
            raise ValidationError(
                {"per_user_limit": "Per-user limit must be greater than zero."}
            )

        if self.usage_limit is not None and self.usage_limit <= 0:
            raise ValidationError(
                {"usage_limit": "Usage limit must be greater than zero."}
            )

        if self.valid_until <= self.valid_from:
            raise ValidationError(
                {"valid_until": "Valid until must be after valid from."}
            )

        if self.scope == self.Scope.GLOBAL:
            if self.vendor_id:
                raise ValidationError(
                    {"vendor": "Vendor must be empty for GLOBAL coupons."}
                )

            if self.category_id:
                raise ValidationError(
                    {"category": "Category must be empty for GLOBAL coupons."}
                )

        if self.scope == self.Scope.VENDOR:
            if not self.vendor_id:
                raise ValidationError(
                    {"vendor": "Vendor is required for VENDOR coupons."}
                )

            if self.category_id:
                raise ValidationError(
                    {"category": "Category must be empty for VENDOR coupons."}
                )

        if self.scope == self.Scope.CATEGORY:
            if not self.category_id:
                raise ValidationError(
                    {"category": "Category is required for CATEGORY coupons."}
                )

            if self.vendor_id:
                raise ValidationError(
                    {"vendor": "Vendor must be empty for CATEGORY coupons."}
                )

    def save(self, *args, **kwargs):
        self.code = normalize_coupon_code(self.code)
        self.full_clean()

        return super().save(*args, **kwargs)

    @property
    def usage_count(self):
        if not self.pk:
            return 0

        return self.usages.count()

    def user_usage_count(self, user):
        if not self.pk or not user:
            return 0

        return self.usages.filter(user=user).count()

    def is_currently_valid(self, *, at=None):
        at = at or timezone.now()

        return self.is_active and self.valid_from <= at <= self.valid_until

    def calculate_discount(self, order_total):
        order_total = normalize_money(order_total)

        if order_total <= Decimal("0.00"):
            return Decimal("0.00")

        if self.type == self.Type.FIXED:
            return min(normalize_money(self.value), order_total)

        discount = normalize_money(order_total * (self.value / Decimal("100.00")))

        if self.max_discount is not None:
            discount = min(discount, normalize_money(self.max_discount))

        return min(discount, order_total)

    def validate_for_order(
        self,
        *,
        user,
        order_total,
        vendor=None,
        category=None,
        at=None,
    ):
        at = at or timezone.now()
        order_total = normalize_money(order_total)

        if not self.is_active:
            raise ValidationError({"coupon": "Coupon is inactive."})

        if not self.valid_from <= at <= self.valid_until:
            raise ValidationError({"coupon": "Coupon is not valid at this time."})

        if order_total < self.min_order_value:
            raise ValidationError(
                {
                    "min_order_value": (
                        "Order total does not meet the minimum order value."
                    )
                }
            )

        if self.usage_limit is not None and self.usage_count >= self.usage_limit:
            raise ValidationError({"usage_limit": "Coupon usage limit has been reached."})

        if self.user_usage_count(user) >= self.per_user_limit:
            raise ValidationError(
                {"per_user_limit": "User coupon usage limit has been reached."}
            )

        if self.scope == self.Scope.VENDOR:
            vendor_id = getattr(vendor, "id", vendor)

            if not vendor_id or vendor_id != self.vendor_id:
                raise ValidationError(
                    {"vendor": "Coupon is not valid for this vendor."}
                )

        if self.scope == self.Scope.CATEGORY:
            category_id = getattr(category, "id", category)

            if not category_id or category_id != self.category_id:
                raise ValidationError(
                    {"category": "Coupon is not valid for this category."}
                )

        return True

    def record_usage(self, *, user, order, vendor=None, category=None):
        if order.customer_id != user.id:
            raise ValidationError(
                {"user": "Coupon usage user must match the order customer."}
            )

        with transaction.atomic():
            locked_coupon = Coupon.objects.select_for_update().get(pk=self.pk)

            locked_coupon.validate_for_order(
                user=user,
                order_total=order.total_amount,
                vendor=vendor,
                category=category,
            )

            return CouponUsage.objects.create(
                coupon=locked_coupon,
                user=user,
                order=order,
            )


class CouponUsage(models.Model):
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    coupon = models.ForeignKey(
        Coupon,
        on_delete=models.PROTECT,
        related_name="usages",
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="coupon_usages",
    )

    order = models.ForeignKey(
        Order,
        on_delete=models.PROTECT,
        related_name="coupon_usages",
    )

    used_at = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
    )

    class Meta:
        ordering = ["-used_at"]
        indexes = [
            models.Index(fields=["coupon", "used_at"]),
            models.Index(fields=["user", "used_at"]),
            models.Index(fields=["order"]),
        ]

    def __str__(self):
        return f"{self.coupon.code} - {self.user_id} - {self.order_id}"

    def clean(self):
        if self.order_id and self.user_id:
            if self.order.customer_id != self.user_id:
                raise ValidationError(
                    {"user": "Coupon usage user must match the order customer."}
                )

    def save(self, *args, **kwargs):
        self.full_clean()

        return super().save(*args, **kwargs)