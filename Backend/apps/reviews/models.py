import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models, transaction
from django.db.models import Avg, Count, Q

from apps.catalog.models import ProductVariant
from apps.orders.models import Order, OrderItem


class Review(models.Model):
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    order_item = models.OneToOneField(
        OrderItem,
        on_delete=models.PROTECT,
        related_name="review",
    )

    reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="reviews",
    )

    variant = models.ForeignKey(
        ProductVariant,
        on_delete=models.PROTECT,
        related_name="reviews",
    )

    rating = models.PositiveSmallIntegerField(
        validators=[
            MinValueValidator(1),
            MaxValueValidator(5),
        ],
    )

    body = models.TextField()

    is_visible = models.BooleanField(
        default=True,
        db_index=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
    )

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["variant", "is_visible"]),
            models.Index(fields=["reviewer", "created_at"]),
            models.Index(fields=["rating"]),
            models.Index(fields=["created_at"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(rating__gte=1) & Q(rating__lte=5),
                name="reviews_rating_between_1_and_5",
            ),
        ]

    def __str__(self):
        return f"{self.variant_id} - {self.rating}/5"

    @staticmethod
    def get_completed_status_value():
        return getattr(Order.Status, "COMPLETED", "COMPLETED")

    @classmethod
    def get_rating_summary_for_variant(cls, variant):
        summary = cls.objects.filter(
            variant=variant,
            is_visible=True,
        ).aggregate(
            review_count=Count("id"),
            average_rating=Avg("rating"),
        )

        return {
            "review_count": summary["review_count"] or 0,
            "average_rating": summary["average_rating"],
        }

    @classmethod
    def validate_order_item_review_rules(cls, *, reviewer, order_item, variant):
        if not reviewer or not getattr(reviewer, "is_authenticated", False):
            raise ValidationError(
                {"reviewer": "Reviewer must be authenticated."}
            )

        if order_item.order.customer_id != reviewer.id:
            raise ValidationError(
                {"reviewer": "Only the buyer of this order item can review it."}
            )

        completed_status = cls.get_completed_status_value()

        if order_item.order.status != completed_status:
            raise ValidationError(
                {"order_item": "Only completed order items can be reviewed."}
            )

        if not order_item.variant_id:
            raise ValidationError(
                {"order_item": "Order item must have a product variant to review."}
            )

        variant_id = getattr(variant, "id", variant)

        if order_item.variant_id != variant_id:
            raise ValidationError(
                {"variant": "Review variant must match the purchased order item variant."}
            )

        return True

    def clean(self):
        if self.rating is not None and not 1 <= int(self.rating) <= 5:
            raise ValidationError(
                {"rating": "Rating must be between 1 and 5."}
            )

        if self.order_item_id and self.reviewer_id and self.variant_id:
            self.validate_order_item_review_rules(
                reviewer=self.reviewer,
                order_item=self.order_item,
                variant=self.variant,
            )

    def save(self, *args, **kwargs):
        self.full_clean()

        return super().save(*args, **kwargs)

    @classmethod
    def create_for_order_item(
        cls,
        *,
        order_item,
        reviewer,
        variant,
        rating,
        body,
        is_visible=True,
    ):
        with transaction.atomic():
            locked_order_item = (
               OrderItem.objects.select_for_update(of=("self",))
               .select_related("order")
               .get(pk=order_item.pk)
            )

            cls.validate_order_item_review_rules(
                reviewer=reviewer,
                order_item=locked_order_item,
                variant=variant,
            )

            return cls.objects.create(
                order_item=locked_order_item,
                reviewer=reviewer,
                variant=variant,
                rating=rating,
                body=body,
                is_visible=is_visible,
            )