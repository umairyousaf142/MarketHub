from decimal import Decimal

from rest_framework import serializers

from apps.orders.models import Order, OrderItem, VendorOrder


class DetailResponseSerializer(serializers.Serializer):
    detail = serializers.CharField()


class CheckoutSerializer(serializers.Serializer):
    shipping_address = serializers.JSONField(required=False, default=dict)
    billing_address = serializers.JSONField(required=False, default=dict)

    shipping_amount = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        required=False,
        default=Decimal("0.00"),
        min_value=Decimal("0.00"),
    )

    tax_amount = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        required=False,
        default=Decimal("0.00"),
        min_value=Decimal("0.00"),
    )

    discount_amount = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        required=False,
        default=Decimal("0.00"),
        min_value=Decimal("0.00"),
    )

    notes = serializers.CharField(required=False, allow_blank=True)

    def validate_shipping_address(self, value):
        if value is None:
            return {}

        if not isinstance(value, dict):
            raise serializers.ValidationError("Shipping address must be a JSON object.")

        return value

    def validate_billing_address(self, value):
        if value is None:
            return {}

        if not isinstance(value, dict):
            raise serializers.ValidationError("Billing address must be a JSON object.")

        return value


class OrderItemReadSerializer(serializers.ModelSerializer):
    order_id = serializers.UUIDField(source="order.id", read_only=True)
    order_number = serializers.CharField(source="order.order_number", read_only=True)

    vendor_id = serializers.UUIDField(source="vendor.id", read_only=True)
    vendor_store_name_live = serializers.CharField(
        source="vendor.store_name",
        read_only=True,
    )

    product_id = serializers.UUIDField(source="product.id", read_only=True)
    product_slug = serializers.CharField(source="product.slug", read_only=True)

    variant_id = serializers.SerializerMethodField()

    class Meta:
        model = OrderItem
        fields = [
            "id",
            "order",
            "order_id",
            "order_number",
            "vendor",
            "vendor_id",
            "vendor_store_name",
            "vendor_store_name_live",
            "product",
            "product_id",
            "product_slug",
            "variant",
            "variant_id",
            "inventory_record",
            "product_name",
            "product_sku",
            "variant_name",
            "variant_sku",
            "quantity",
            "unit_price",
            "line_total",
            "created_at",
        ]
        read_only_fields = fields

    def get_variant_id(self, obj):
        return str(obj.variant_id) if obj.variant_id else None


class VendorOrderSummarySerializer(serializers.ModelSerializer):
    vendor_id = serializers.UUIDField(source="vendor.id", read_only=True)
    vendor_store_name = serializers.CharField(source="vendor.store_name", read_only=True)

    class Meta:
        model = VendorOrder
        fields = [
            "id",
            "vendor",
            "vendor_id",
            "vendor_store_name",
            "status",
            "subtotal_amount",
            "item_count",
            "total_quantity",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class OrderReadSerializer(serializers.ModelSerializer):
    customer_id = serializers.UUIDField(source="customer.id", read_only=True)
    customer_email = serializers.EmailField(source="customer.email", read_only=True)

    source_cart_id = serializers.SerializerMethodField()

    item_count = serializers.IntegerField(read_only=True)
    total_quantity = serializers.IntegerField(read_only=True)

    items = OrderItemReadSerializer(many=True, read_only=True)
    vendor_orders = VendorOrderSummarySerializer(many=True, read_only=True)

    class Meta:
        model = Order
        fields = [
            "id",
            "order_number",
            "customer",
            "customer_id",
            "customer_email",
            "source_cart",
            "source_cart_id",
            "status",
            "payment_status",
            "inventory_status",
            "subtotal_amount",
            "shipping_amount",
            "tax_amount",
            "discount_amount",
            "total_amount",
            "shipping_address",
            "billing_address",
            "notes",
            "item_count",
            "total_quantity",
            "items",
            "vendor_orders",
            "placed_at",
            "paid_at",
            "cancelled_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_source_cart_id(self, obj):
        return str(obj.source_cart_id) if obj.source_cart_id else None


class VendorOrderReadSerializer(serializers.ModelSerializer):
    order_id = serializers.UUIDField(source="order.id", read_only=True)
    order_number = serializers.CharField(source="order.order_number", read_only=True)

    customer_id = serializers.UUIDField(source="order.customer.id", read_only=True)
    customer_email = serializers.EmailField(source="order.customer.email", read_only=True)

    order_status = serializers.CharField(source="order.status", read_only=True)
    payment_status = serializers.CharField(source="order.payment_status", read_only=True)
    inventory_status = serializers.CharField(
        source="order.inventory_status",
        read_only=True,
    )

    vendor_id = serializers.UUIDField(source="vendor.id", read_only=True)
    vendor_store_name = serializers.CharField(source="vendor.store_name", read_only=True)

    items = serializers.SerializerMethodField()

    class Meta:
        model = VendorOrder
        fields = [
            "id",
            "order",
            "order_id",
            "order_number",
            "customer_id",
            "customer_email",
            "order_status",
            "payment_status",
            "inventory_status",
            "vendor",
            "vendor_id",
            "vendor_store_name",
            "status",
            "subtotal_amount",
            "item_count",
            "total_quantity",
            "items",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_items(self, obj):
        items = obj.order.items.filter(vendor=obj.vendor).select_related(
            "order",
            "vendor",
            "product",
            "variant",
            "inventory_record",
        )
        return OrderItemReadSerializer(items, many=True).data


class VendorOrderStatusSerializer(serializers.Serializer):
    status = serializers.ChoiceField(
        choices=[
            VendorOrder.Status.PROCESSING,
            VendorOrder.Status.SHIPPED,
            VendorOrder.Status.DELIVERED,
        ]
    )