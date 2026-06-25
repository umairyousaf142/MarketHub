import uuid
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from apps.catalog.models import Product
from apps.vendors.models import Vendor


class AnalyticsSnapshot(models.Model):
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    date = models.DateField(
        db_index=True,
    )

    total_revenue = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal("0.00"),
    )

    total_orders = models.IntegerField(
        default=0,
    )

    new_customers = models.IntegerField(
        default=0,
    )

    top_vendor = models.ForeignKey(
        Vendor,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="analytics_snapshots_as_top_vendor",
    )

    top_product = models.ForeignKey(
        Product,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="analytics_snapshots_as_top_product",
    )

    class Meta:
        ordering = ["-date"]
        indexes = [
            models.Index(fields=["date"]),
            models.Index(fields=["top_vendor", "date"]),
            models.Index(fields=["top_product", "date"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(total_revenue__gte=0),
                name="analytics_snapshot_total_revenue_nonnegative",
            ),
            models.CheckConstraint(
                condition=Q(total_orders__gte=0),
                name="analytics_snapshot_total_orders_nonnegative",
            ),
            models.CheckConstraint(
                condition=Q(new_customers__gte=0),
                name="analytics_snapshot_new_customers_nonnegative",
            ),
        ]

    def __str__(self):
        return f"Analytics Snapshot - {self.date}"

    def clean(self):
        if self.total_revenue is not None and self.total_revenue < Decimal("0.00"):
            raise ValidationError(
                {"total_revenue": "Total revenue cannot be negative."}
            )

        if self.total_orders is not None and self.total_orders < 0:
            raise ValidationError(
                {"total_orders": "Total orders cannot be negative."}
            )

        if self.new_customers is not None and self.new_customers < 0:
            raise ValidationError(
                {"new_customers": "New customers cannot be negative."}
            )

    def save(self, *args, **kwargs):
        self.full_clean()

        return super().save(*args, **kwargs)