from decimal import Decimal
from pathlib import Path

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from apps.vendors.models import CommissionPlan, Vendor, VendorDocument


class DetailResponseSerializer(serializers.Serializer):
    detail = serializers.CharField()


class CommissionPlanSerializer(serializers.ModelSerializer):
    class Meta:
        model = CommissionPlan
        fields = [
            "id",
            "name",
            "percentage",
            "is_default",
        ]
        read_only_fields = ["id"]

    def validate_name(self, value):
        value = value.strip()

        queryset = CommissionPlan.objects.filter(name__iexact=value)

        if self.instance:
            queryset = queryset.exclude(pk=self.instance.pk)

        if queryset.exists():
            raise serializers.ValidationError(
                "A commission plan with this name already exists."
            )

        return value

    def validate_percentage(self, value):
        if value < Decimal("0.00") or value > Decimal("100.00"):
            raise serializers.ValidationError(
                "Commission percentage must be between 0 and 100."
            )

        return value

    def validate(self, attrs):
        is_default = attrs.get(
            "is_default",
            self.instance.is_default if self.instance else False,
        )

        if not is_default:
            has_default = CommissionPlan.objects.filter(is_default=True)

            if self.instance:
                has_default = has_default.exclude(pk=self.instance.pk)

            if not has_default.exists():
                raise serializers.ValidationError(
                    {
                        "is_default": (
                            "At least one default commission plan is required."
                        )
                    }
                )

        return attrs

    def create(self, validated_data):
        try:
            return super().create(validated_data)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.message_dict if hasattr(exc, "message_dict") else exc.messages)

    def update(self, instance, validated_data):
        try:
            return super().update(instance, validated_data)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.message_dict if hasattr(exc, "message_dict") else exc.messages)


class CommissionPlanCompactSerializer(serializers.ModelSerializer):
    class Meta:
        model = CommissionPlan
        fields = [
            "id",
            "name",
            "percentage",
            "is_default",
        ]


class VendorReadSerializer(serializers.ModelSerializer):
    user_id = serializers.UUIDField(source="user.id", read_only=True)
    user_email = serializers.EmailField(source="user.email", read_only=True)

    commission_plan_detail = CommissionPlanCompactSerializer(
        source="commission_plan",
        read_only=True,
    )

    approved_by_id = serializers.UUIDField(source="approved_by.id", read_only=True)
    approved_by_email = serializers.EmailField(source="approved_by.email", read_only=True)

    class Meta:
        model = Vendor
        fields = [
            "id",
            "user_id",
            "user_email",
            "store_name",
            "status",
            "commission_plan",
            "commission_plan_detail",
            "approved_at",
            "approved_by_id",
            "approved_by_email",
        ]
        read_only_fields = [
            "id",
            "user_id",
            "user_email",
            "status",
            "commission_plan",
            "commission_plan_detail",
            "approved_at",
            "approved_by_id",
            "approved_by_email",
        ]


class VendorOnboardingSerializer(serializers.ModelSerializer):
    class Meta:
        model = Vendor
        fields = [
            "id",
            "store_name",
        ]
        read_only_fields = ["id"]

    def validate_store_name(self, value):
        value = value.strip()

        if not value:
            raise serializers.ValidationError("Store name is required.")

        if Vendor.objects.filter(store_name__iexact=value).exists():
            raise serializers.ValidationError(
                "A vendor store with this name already exists."
            )

        return value

    def validate(self, attrs):
        request = self.context["request"]

        if Vendor.objects.filter(user=request.user).exists():
            raise serializers.ValidationError(
                {"detail": "Vendor profile already exists for this user."}
            )

        return attrs

    def create(self, validated_data):
        request = self.context["request"]

        return Vendor.objects.create(
            user=request.user,
            store_name=validated_data["store_name"],
        )


class VendorProfileUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Vendor
        fields = [
            "store_name",
        ]

    def validate_store_name(self, value):
        value = value.strip()

        if not value:
            raise serializers.ValidationError("Store name is required.")

        queryset = Vendor.objects.filter(store_name__iexact=value)

        if self.instance:
            queryset = queryset.exclude(pk=self.instance.pk)

        if queryset.exists():
            raise serializers.ValidationError(
                "A vendor store with this name already exists."
            )

        return value


class VendorDocumentSerializer(serializers.ModelSerializer):
    class Meta:
        model = VendorDocument
        fields = [
            "id",
            "doc_type",
            "file",
            "verified",
        ]
        read_only_fields = [
            "id",
            "verified",
        ]

    def validate_file(self, value):
        max_size = 5 * 1024 * 1024
        allowed_extensions = {".pdf", ".jpg", ".jpeg", ".png"}

        if hasattr(value, "size") and value.size > max_size:
            raise serializers.ValidationError(
                "Document file size cannot exceed 5MB."
            )

        extension = Path(value.name).suffix.lower()

        if extension not in allowed_extensions:
            raise serializers.ValidationError(
                "Only PDF, JPG, JPEG, and PNG files are allowed."
            )

        return value


class AdminVendorReadSerializer(VendorReadSerializer):
    pass



class AdminVendorDocumentReadSerializer(serializers.ModelSerializer):
    vendor_id = serializers.UUIDField(source="vendor.id", read_only=True)
    vendor_store_name = serializers.CharField(source="vendor.store_name", read_only=True)
    vendor_user_id = serializers.UUIDField(source="vendor.user.id", read_only=True)
    vendor_user_email = serializers.EmailField(source="vendor.user.email", read_only=True)

    class Meta:
        model = VendorDocument
        fields = [
            "id",
            "vendor_id",
            "vendor_store_name",
            "vendor_user_id",
            "vendor_user_email",
            "doc_type",
            "file",
            "verified",
        ]
        read_only_fields = fields