from drf_spectacular.utils import extend_schema_field
from decimal import Decimal

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from apps.cart.models import Cart, CartItem
from apps.catalog.models import Product, ProductVariant
from apps.inventory.models import InventoryRecord
from apps.vendors.models import Vendor


def raise_serializer_validation_error(exc):
    if hasattr(exc, "message_dict"):
        raise serializers.ValidationError(exc.message_dict)

    if hasattr(exc, "messages"):
        raise serializers.ValidationError({"detail": exc.messages})

    raise serializers.ValidationError({"detail": str(exc)})


class CartItemReadSerializer(serializers.ModelSerializer):
    product_id = serializers.UUIDField(source="product.id", read_only=True)
    product_name = serializers.CharField(source="product.name", read_only=True)
    product_slug = serializers.CharField(source="product.slug", read_only=True)
    product_sku = serializers.CharField(source="product.sku", read_only=True)

    vendor_id = serializers.UUIDField(source="product.vendor.id", read_only=True)
    vendor_store_name = serializers.CharField(
        source="product.vendor.store_name",
        read_only=True,
    )

    variant_id = serializers.SerializerMethodField()
    variant_name = serializers.SerializerMethodField()
    variant_sku = serializers.SerializerMethodField()

    line_total = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        read_only=True,
    )

    class Meta:
        model = CartItem
        fields = [
            "id",
            "product",
            "product_id",
            "product_name",
            "product_slug",
            "product_sku",
            "vendor_id",
            "vendor_store_name",
            "variant",
            "variant_id",
            "variant_name",
            "variant_sku",
            "quantity",
            "unit_price",
            "line_total",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    @extend_schema_field(serializers.UUIDField(allow_null=True))
    def get_variant_id(self, obj) -> str | None:
        return str(obj.variant_id) if obj.variant_id else None

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_variant_name(self, obj) -> str | None:
        return obj.variant.name if obj.variant_id else None

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_variant_sku(self, obj) -> str | None:
        return obj.variant.sku if obj.variant_id else None


class CartReadSerializer(serializers.ModelSerializer):
    customer_id = serializers.UUIDField(source="customer.id", read_only=True)
    customer_email = serializers.EmailField(source="customer.email", read_only=True)

    items = CartItemReadSerializer(many=True, read_only=True)

    item_count = serializers.IntegerField(read_only=True)
    total_quantity = serializers.IntegerField(read_only=True)
    subtotal_amount = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        read_only=True,
    )

    class Meta:
        model = Cart
        fields = [
            "id",
            "customer_id",
            "customer_email",
            "status",
            "items",
            "item_count",
            "total_quantity",
            "subtotal_amount",
            "created_at",
            "updated_at",
            "converted_at",
            "abandoned_at",
        ]
        read_only_fields = fields


class CartItemAddSerializer(serializers.Serializer):
    product = serializers.PrimaryKeyRelatedField(
        queryset=Product.objects.select_related(
            "vendor",
            "category",
            "brand",
        ).all()
    )
    variant = serializers.PrimaryKeyRelatedField(
        queryset=ProductVariant.objects.select_related("product").all(),
        required=False,
        allow_null=True,
    )
    quantity = serializers.IntegerField(min_value=1)

    def validate(self, attrs):
        product = attrs["product"]
        variant = attrs.get("variant")

        if product.status != Product.Status.ACTIVE:
            raise serializers.ValidationError(
                {"product": "Only active products can be added to cart."}
            )

        if product.vendor.status != Vendor.Status.APPROVED:
            raise serializers.ValidationError(
                {"product": "Product vendor must be approved."}
            )

        if not product.category.is_active:
            raise serializers.ValidationError(
                {"product": "Product category must be active."}
            )

        if product.brand_id and not product.brand.is_active:
            raise serializers.ValidationError(
                {"product": "Product brand must be active."}
            )

        if variant:
            if variant.product_id != product.id:
                raise serializers.ValidationError(
                    {"variant": "Variant must belong to the selected product."}
                )

            if not variant.is_active:
                raise serializers.ValidationError(
                    {"variant": "Only active variants can be added to cart."}
                )

        inventory_record = self.get_inventory_record(product, variant)

        if not inventory_record:
            raise serializers.ValidationError(
                {"inventory": "Inventory record is required for this product."}
            )

        if inventory_record.track_inventory and not inventory_record.allow_backorder:
            if inventory_record.available_quantity < attrs["quantity"]:
                raise serializers.ValidationError(
                    {"quantity": "Requested quantity exceeds available stock."}
                )

        return attrs

    def get_inventory_record(self, product, variant=None):
        if variant:
            return InventoryRecord.objects.filter(
                product=product,
                variant=variant,
            ).first()

        return InventoryRecord.objects.filter(
            product=product,
            variant__isnull=True,
        ).first()


class CartItemQuantityUpdateSerializer(serializers.Serializer):
    quantity = serializers.IntegerField(min_value=1)

    def validate_quantity(self, value):
        item = self.context.get("item")

        if not item:
            return value

        inventory_record = item.get_inventory_record()

        if not inventory_record:
            raise serializers.ValidationError(
                "Inventory record is required for this product."
            )

        if inventory_record.track_inventory and not inventory_record.allow_backorder:
            if inventory_record.available_quantity < value:
                raise serializers.ValidationError(
                    "Requested quantity exceeds available stock."
                )

        return value


class CartClearResponseSerializer(serializers.Serializer):
    detail = serializers.CharField()