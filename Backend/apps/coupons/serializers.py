from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from apps.catalog.models import Category
from apps.coupons.models import Coupon, CouponUsage, normalize_coupon_code
from apps.orders.models import Order
from apps.vendors.models import Vendor
from core.permissions.roles import is_admin_user


class CouponReadSerializer(serializers.ModelSerializer):
    vendor_name = serializers.CharField(source="vendor.store_name", read_only=True)
    category_name = serializers.CharField(source="category.name", read_only=True)
    usage_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Coupon
        fields = [
            "id",
            "code",
            "type",
            "value",
            "max_discount",
            "scope",
            "vendor",
            "vendor_name",
            "category",
            "category_name",
            "min_order_value",
            "usage_limit",
            "per_user_limit",
            "valid_from",
            "valid_until",
            "is_active",
            "usage_count",
        ]
        read_only_fields = fields


class CouponAdminWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Coupon
        fields = [
            "code",
            "type",
            "value",
            "max_discount",
            "scope",
            "vendor",
            "category",
            "min_order_value",
            "usage_limit",
            "per_user_limit",
            "valid_from",
            "valid_until",
            "is_active",
        ]

    def validate_code(self, value):
        return normalize_coupon_code(value)

    def create(self, validated_data):
        try:
            return Coupon.objects.create(**validated_data)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.message_dict) from exc

    def update(self, instance, validated_data):
        for field, value in validated_data.items():
            setattr(instance, field, value)

        try:
            instance.save()
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.message_dict) from exc

        return instance


class CouponUsageReadSerializer(serializers.ModelSerializer):
    coupon_code = serializers.CharField(source="coupon.code", read_only=True)
    user_email = serializers.EmailField(source="user.email", read_only=True)
    order_number = serializers.CharField(source="order.order_number", read_only=True)

    class Meta:
        model = CouponUsage
        fields = [
            "id",
            "coupon",
            "coupon_code",
            "user",
            "user_email",
            "order",
            "order_number",
            "used_at",
        ]
        read_only_fields = fields


class CouponValidateSerializer(serializers.Serializer):
    code = serializers.CharField()
    order_id = serializers.UUIDField()
    vendor_id = serializers.UUIDField(required=False)
    category_id = serializers.UUIDField(required=False)

    def validate(self, attrs):
        request = self.context["request"]
        user = request.user

        code = normalize_coupon_code(attrs["code"])

        try:
            coupon = Coupon.objects.select_related(
                "vendor",
                "category",
            ).get(code__iexact=code)
        except Coupon.DoesNotExist as exc:
            raise serializers.ValidationError(
                {"code": "Coupon does not exist."}
            ) from exc

        try:
            order = Order.objects.select_related("customer").get(
                id=attrs["order_id"],
            )
        except Order.DoesNotExist as exc:
            raise serializers.ValidationError(
                {"order_id": "Order does not exist."}
            ) from exc

        if not is_admin_user(user) and order.customer_id != user.id:
            raise serializers.ValidationError(
                {"order_id": "You can only validate coupons for your own orders."}
            )

        vendor = None
        category = None

        if attrs.get("vendor_id"):
            vendor = Vendor.objects.filter(id=attrs["vendor_id"]).first()

            if not vendor:
                raise serializers.ValidationError(
                    {"vendor_id": "Vendor does not exist."}
                )

        if attrs.get("category_id"):
            category = Category.objects.filter(id=attrs["category_id"]).first()

            if not category:
                raise serializers.ValidationError(
                    {"category_id": "Category does not exist."}
                )

        try:
            coupon.validate_for_order(
                user=user,
                order_total=order.total_amount,
                vendor=vendor,
                category=category,
            )
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.message_dict) from exc

        attrs["coupon"] = coupon
        attrs["order"] = order
        attrs["vendor"] = vendor
        attrs["category"] = category
        attrs["discount_amount"] = coupon.calculate_discount(order.total_amount)

        return attrs


class CouponValidateResponseSerializer(serializers.Serializer):
    valid = serializers.BooleanField()
    coupon_id = serializers.UUIDField()
    code = serializers.CharField()
    type = serializers.CharField()
    scope = serializers.CharField()
    order_id = serializers.UUIDField()
    order_total = serializers.DecimalField(max_digits=10, decimal_places=2)
    discount_amount = serializers.DecimalField(max_digits=10, decimal_places=2)


class CouponUsageCreateSerializer(CouponValidateSerializer):
    def create(self, validated_data):
        coupon = validated_data["coupon"]
        order = validated_data["order"]
        vendor = validated_data.get("vendor")
        category = validated_data.get("category")
        request = self.context["request"]

        try:
            return coupon.record_usage(
                user=request.user,
                order=order,
                vendor=vendor,
                category=category,
            )
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.message_dict) from exc