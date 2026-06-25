from drf_spectacular.utils import extend_schema
from rest_framework import generics, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.analytics.models import AnalyticsSnapshot
from apps.analytics.serializers import (
    AnalyticsSnapshotComputeSerializer,
    AnalyticsSnapshotQuerySerializer,
    AnalyticsSnapshotSerializer,
    VendorDashboardQuerySerializer,
    VendorDashboardSerializer,
)
from apps.analytics.services import (
    compute_daily_analytics_snapshot,
    get_vendor_dashboard_metrics,
    resolve_snapshot_date,
)
from apps.vendors.models import Vendor
from core.permissions.analytics import IsAdminRole, IsVendorRole


class AdminAnalyticsSnapshotViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = AnalyticsSnapshotSerializer
    permission_classes = [IsAdminRole]
    http_method_names = [
        "get",
        "post",
        "head",
        "options",
    ]

    def get_queryset(self):
        queryset = AnalyticsSnapshot.objects.select_related(
            "top_vendor",
            "top_product",
        ).order_by("-date")

        query_serializer = AnalyticsSnapshotQuerySerializer(
            data=self.request.query_params
        )
        query_serializer.is_valid(raise_exception=True)
        filters = query_serializer.validated_data

        if filters.get("date"):
            queryset = queryset.filter(date=filters["date"])

        if filters.get("start_date"):
            queryset = queryset.filter(date__gte=filters["start_date"])

        if filters.get("end_date"):
            queryset = queryset.filter(date__lte=filters["end_date"])

        if filters.get("top_vendor_id"):
            queryset = queryset.filter(top_vendor_id=filters["top_vendor_id"])

        if filters.get("top_product_id"):
            queryset = queryset.filter(top_product_id=filters["top_product_id"])

        return queryset

    @action(
        detail=False,
        methods=["post"],
        url_path="compute",
    )
    def compute(self, request):
        serializer = AnalyticsSnapshotComputeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        snapshot_date = resolve_snapshot_date(
            serializer.validated_data.get("date")
        )

        snapshot_exists = AnalyticsSnapshot.objects.filter(
            date=snapshot_date
        ).exists()

        snapshot = compute_daily_analytics_snapshot(snapshot_date)

        output_serializer = self.get_serializer(snapshot)

        response_status = (
            status.HTTP_200_OK
            if snapshot_exists
            else status.HTTP_201_CREATED
        )

        return Response(
            output_serializer.data,
            status=response_status,
        )


class VendorDashboardAPIView(generics.GenericAPIView):
    permission_classes = [IsVendorRole]
    serializer_class = VendorDashboardSerializer

    def get_vendor(self):
        try:
            return self.request.user.vendor_profile
        except Vendor.DoesNotExist as exc:
            raise PermissionDenied("Vendor profile is required.") from exc

    @extend_schema(
        parameters=[VendorDashboardQuerySerializer],
        responses=VendorDashboardSerializer,
    )
    def get(self, request):
        query_serializer = VendorDashboardQuerySerializer(
            data=request.query_params
        )
        query_serializer.is_valid(raise_exception=True)

        vendor = self.get_vendor()

        metrics = get_vendor_dashboard_metrics(
            vendor=vendor,
            start_date=query_serializer.validated_data.get("start_date"),
            end_date=query_serializer.validated_data.get("end_date"),
        )

        output_serializer = self.get_serializer(metrics)

        return Response(
            output_serializer.data,
            status=status.HTTP_200_OK,
        )