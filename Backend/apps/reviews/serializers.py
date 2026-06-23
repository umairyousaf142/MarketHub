from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError
from rest_framework import serializers

from apps.catalog.models import ProductVariant
from apps.orders.models import OrderItem
from apps.reviews.models import Review


class ReviewReadSerializer(serializers.ModelSerializer):
    order_number = serializers.CharField(
        source="order_item.order.order_number",
        read_only=True,
    )
    product_name = serializers.CharField(
        source="order_item.product_name",
        read_only=True,
    )
    reviewer_email = serializers.EmailField(
        source="reviewer.email",
        read_only=True,
    )
    variant_sku = serializers.CharField(
        source="variant.sku",
        read_only=True,
    )

    class Meta:
        model = Review
        fields = [
            "id",
            "order_item",
            "order_number",
            "product_name",
            "reviewer",
            "reviewer_email",
            "variant",
            "variant_sku",
            "rating",
            "body",
            "is_visible",
            "created_at",
        ]
        read_only_fields = fields


class PublicReviewReadSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(
        source="order_item.product_name",
        read_only=True,
    )
    variant_sku = serializers.CharField(
        source="variant.sku",
        read_only=True,
    )

    class Meta:
        model = Review
        fields = [
            "id",
            "variant",
            "variant_sku",
            "product_name",
            "rating",
            "body",
            "created_at",
        ]
        read_only_fields = fields


class ReviewCreateSerializer(serializers.Serializer):
    order_item = serializers.UUIDField()
    variant = serializers.UUIDField()
    rating = serializers.IntegerField(min_value=1, max_value=5)
    body = serializers.CharField(allow_blank=False)

    def validate(self, attrs):
        request = self.context["request"]

        try:
            order_item = OrderItem.objects.select_related(
                "order",
                "variant",
            ).get(id=attrs["order_item"])
        except OrderItem.DoesNotExist as exc:
            raise serializers.ValidationError(
                {"order_item": "Order item does not exist."}
            ) from exc

        try:
            variant = ProductVariant.objects.get(id=attrs["variant"])
        except ProductVariant.DoesNotExist as exc:
            raise serializers.ValidationError(
                {"variant": "Product variant does not exist."}
            ) from exc

        if Review.objects.filter(order_item=order_item).exists():
            raise serializers.ValidationError(
                {"order_item": "This order item has already been reviewed."}
            )

        try:
            Review.validate_order_item_review_rules(
                reviewer=request.user,
                order_item=order_item,
                variant=variant,
            )
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.message_dict) from exc

        attrs["order_item_obj"] = order_item
        attrs["variant_obj"] = variant

        return attrs

    def create(self, validated_data):
        request = self.context["request"]

        try:
            return Review.create_for_order_item(
                order_item=validated_data["order_item_obj"],
                reviewer=request.user,
                variant=validated_data["variant_obj"],
                rating=validated_data["rating"],
                body=validated_data["body"],
            )
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.message_dict) from exc
        except IntegrityError as exc:
            raise serializers.ValidationError(
                {"order_item": "This order item has already been reviewed."}
            ) from exc


class ReviewVisibilityUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Review
        fields = [
            "is_visible",
        ]

    def update(self, instance, validated_data):
        instance.is_visible = validated_data["is_visible"]
        instance.save(update_fields=["is_visible"])

        return instance


class ReviewRatingSummarySerializer(serializers.Serializer):
    variant_id = serializers.UUIDField()
    review_count = serializers.IntegerField()
    average_rating = serializers.DecimalField(
        max_digits=4,
        decimal_places=2,
        allow_null=True,
    )