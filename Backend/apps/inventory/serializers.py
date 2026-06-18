from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError
from rest_framework import serializers

from apps.catalog.models import Product, ProductVariant
from apps.inventory.models import InventoryRecord, StockMovement
from apps.vendors.models import Vendor


def raise_serializer_validation_error(exc):
    if hasattr(exc, "message_dict"):
        raise serializers.ValidationError(exc.message_dict)

    if hasattr(exc, "messages"):
        raise serializers.ValidationError({"detail": exc.messages})

    raise serializers.ValidationError({"detail": str(exc)})


class StockOperationSerializer(serializers.Serializer):
    quantity = serializers.IntegerField(min_value=1)
    reason = serializers.CharField(required=False, allow_blank=True, max_length=255)
    reference = serializers.CharField(required=False, allow_blank=True, max_length=120)


class InventoryRecordReadSerializer(serializers.ModelSerializer):
    product_id = serializers.UUIDField(source="product.id", read_only=True)
    product_name = serializers.CharField(source="product.name", read_only=True)
    product_sku = serializers.CharField(source="product.sku", read_only=True)

    vendor_id = serializers.UUIDField(source="product.vendor.id", read_only=True)
    vendor_store_name = serializers.CharField(
        source="product.vendor.store_name",
        read_only=True,
    )

    variant_id = serializers.SerializerMethodField()
    variant_name = serializers.SerializerMethodField()
    variant_sku = serializers.SerializerMethodField()

    available_quantity = serializers.IntegerField(read_only=True)
    is_low_stock = serializers.BooleanField(read_only=True)

    class Meta:
        model = InventoryRecord
        fields = [
            "id",
            "product",
            "product_id",
            "product_name",
            "product_sku",
            "vendor_id",
            "vendor_store_name",
            "variant",
            "variant_id",
            "variant_name",
            "variant_sku",
            "quantity_on_hand",
            "quantity_reserved",
            "available_quantity",
            "low_stock_threshold",
            "is_low_stock",
            "track_inventory",
            "allow_backorder",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_variant_id(self, obj):
        return str(obj.variant_id) if obj.variant_id else None

    def get_variant_name(self, obj):
        return obj.variant.name if obj.variant_id else None

    def get_variant_sku(self, obj):
        return obj.variant.sku if obj.variant_id else None


class InventoryRecordWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = InventoryRecord
        fields = [
            "product",
            "variant",
            "quantity_on_hand",
            "quantity_reserved",
            "low_stock_threshold",
            "track_inventory",
            "allow_backorder",
        ]

    def validate(self, attrs):
        vendor = self.context.get("vendor")

        product = attrs.get(
            "product",
            self.instance.product if self.instance else None,
        )

        variant = attrs.get(
            "variant",
            self.instance.variant if self.instance else None,
        )

        quantity_on_hand = attrs.get(
            "quantity_on_hand",
            self.instance.quantity_on_hand if self.instance else 0,
        )

        quantity_reserved = attrs.get(
            "quantity_reserved",
            self.instance.quantity_reserved if self.instance else 0,
        )

        if self.instance:
            blocked_fields = {"product", "variant", "quantity_on_hand", "quantity_reserved"}
            sent_blocked_fields = blocked_fields.intersection(attrs.keys())

            if sent_blocked_fields:
                raise serializers.ValidationError(
                    {
                        "detail": (
                            "Product, variant, quantity_on_hand, and quantity_reserved "
                            "cannot be updated directly. Use stock operation endpoints."
                        )
                    }
                )

        if not product:
            raise serializers.ValidationError({"product": "Product is required."})

        if vendor and product.vendor_id != vendor.id:
            raise serializers.ValidationError(
                {"product": "You can only manage inventory for your own products."}
            )

        if product.vendor.status != Vendor.Status.APPROVED:
            raise serializers.ValidationError(
                {
                    "product": (
                        "Inventory can only be managed for products owned by "
                        "approved vendors."
                    )
                }
            )

        if variant and variant.product_id != product.id:
            raise serializers.ValidationError(
                {"variant": "Variant must belong to the selected product."}
            )

        if quantity_reserved > quantity_on_hand:
            raise serializers.ValidationError(
                {
                    "quantity_reserved": (
                        "Reserved quantity cannot exceed quantity on hand."
                    )
                }
            )

        existing_record = InventoryRecord.objects.all()

        if variant:
            existing_record = existing_record.filter(variant=variant)
        else:
            existing_record = existing_record.filter(
                product=product,
                variant__isnull=True,
            )

        if self.instance:
            existing_record = existing_record.exclude(pk=self.instance.pk)

        if existing_record.exists():
            raise serializers.ValidationError(
                {"detail": "Inventory record already exists for this product or variant."}
            )

        return attrs

    def create(self, validated_data):
        try:
            return super().create(validated_data)
        except DjangoValidationError as exc:
            raise_serializer_validation_error(exc)
        except IntegrityError:
            raise serializers.ValidationError(
                {"detail": "Inventory record already exists for this product or variant."}
            )

    def update(self, instance, validated_data):
        try:
            return super().update(instance, validated_data)
        except DjangoValidationError as exc:
            raise_serializer_validation_error(exc)
        except IntegrityError:
            raise serializers.ValidationError(
                {"detail": "Inventory record already exists for this product or variant."}
            )


class StockMovementReadSerializer(serializers.ModelSerializer):
    inventory_record_id = serializers.UUIDField(
        source="inventory_record.id",
        read_only=True,
    )

    product_id = serializers.UUIDField(
        source="inventory_record.product.id",
        read_only=True,
    )

    product_name = serializers.CharField(
        source="inventory_record.product.name",
        read_only=True,
    )

    product_sku = serializers.CharField(
        source="inventory_record.product.sku",
        read_only=True,
    )

    vendor_id = serializers.UUIDField(
        source="inventory_record.product.vendor.id",
        read_only=True,
    )

    vendor_store_name = serializers.CharField(
        source="inventory_record.product.vendor.store_name",
        read_only=True,
    )

    variant_id = serializers.SerializerMethodField()
    variant_name = serializers.SerializerMethodField()
    variant_sku = serializers.SerializerMethodField()

    created_by_id = serializers.UUIDField(source="created_by.id", read_only=True)
    created_by_email = serializers.EmailField(source="created_by.email", read_only=True)

    class Meta:
        model = StockMovement
        fields = [
            "id",
            "inventory_record_id",
            "product_id",
            "product_name",
            "product_sku",
            "vendor_id",
            "vendor_store_name",
            "variant_id",
            "variant_name",
            "variant_sku",
            "movement_type",
            "quantity",
            "before_on_hand",
            "after_on_hand",
            "before_reserved",
            "after_reserved",
            "reason",
            "reference",
            "created_by_id",
            "created_by_email",
            "created_at",
        ]
        read_only_fields = fields

    def get_variant_id(self, obj):
        variant = obj.inventory_record.variant
        return str(variant.id) if variant else None

    def get_variant_name(self, obj):
        variant = obj.inventory_record.variant
        return variant.name if variant else None

    def get_variant_sku(self, obj):
        variant = obj.inventory_record.variant
        return variant.sku if variant else None