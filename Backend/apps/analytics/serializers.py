from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.analytics.models import AnalyticsSnapshot


class AnalyticsSnapshotSerializer(serializers.ModelSerializer):
    top_vendor_id = serializers.UUIDField(read_only=True)
    top_vendor_store_name = serializers.SerializerMethodField()
    top_product_id = serializers.UUIDField(read_only=True)
    top_product_title = serializers.SerializerMethodField()

    class Meta:
        model = AnalyticsSnapshot
        fields = [
            "id",
            "date",
            "total_revenue",
            "total_orders",
            "new_customers",
            "top_vendor_id",
            "top_vendor_store_name",
            "top_product_id",
            "top_product_title",
        ]
        read_only_fields = fields

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_top_vendor_store_name(self, obj) -> str | None:
        if not obj.top_vendor:
            return None

        return obj.top_vendor.store_name

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_top_product_title(self, obj) -> str | None:
        if not obj.top_product:
            return None

        return (
            getattr(obj.top_product, "title", None)
            or getattr(obj.top_product, "name", None)
            or str(obj.top_product)
        )


class AnalyticsSnapshotQuerySerializer(serializers.Serializer):
    date = serializers.DateField(required=False)
    start_date = serializers.DateField(required=False)
    end_date = serializers.DateField(required=False)
    top_vendor_id = serializers.UUIDField(required=False)
    top_product_id = serializers.UUIDField(required=False)

    def validate(self, attrs):
        start_date = attrs.get("start_date")
        end_date = attrs.get("end_date")

        if start_date and end_date and start_date > end_date:
            raise serializers.ValidationError(
                {"end_date": "End date must be greater than or equal to start date."}
            )

        return attrs


class AnalyticsSnapshotComputeSerializer(serializers.Serializer):
    date = serializers.DateField(required=False)


class VendorDashboardQuerySerializer(serializers.Serializer):
    start_date = serializers.DateField(required=False)
    end_date = serializers.DateField(required=False)

    def validate(self, attrs):
        start_date = attrs.get("start_date")
        end_date = attrs.get("end_date")

        if start_date and end_date and start_date > end_date:
            raise serializers.ValidationError(
                {"end_date": "End date must be greater than or equal to start date."}
            )

        return attrs


class VendorDashboardSerializer(serializers.Serializer):
    vendor_id = serializers.UUIDField(read_only=True)
    total_revenue = serializers.DecimalField(
        max_digits=14,
        decimal_places=2,
        read_only=True,
    )
    total_orders = serializers.IntegerField(read_only=True)
    total_items_sold = serializers.IntegerField(read_only=True)