from django.core.exceptions import ValidationError as DjangoValidationError
from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_view
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError as DRFValidationError
from rest_framework.response import Response

from core.permissions.base import IsAdmin, IsVendor

from apps.inventory.models import InventoryRecord, StockMovement
from apps.vendors.models import Vendor

from .serializers import (
    InventoryRecordReadSerializer,
    InventoryRecordWriteSerializer,
    StockMovementReadSerializer,
    StockOperationSerializer,
)


def raise_drf_validation_error(exc):
    if hasattr(exc, "message_dict"):
        raise DRFValidationError(exc.message_dict)

    if hasattr(exc, "messages"):
        raise DRFValidationError({"detail": exc.messages})

    raise DRFValidationError({"detail": str(exc)})


def get_approved_vendor_for_user(user):
    vendor = Vendor.objects.filter(user=user).first()

    if not vendor:
        raise NotFound("Vendor profile not found. Complete vendor onboarding first.")

    if vendor.status != Vendor.Status.APPROVED:
        raise PermissionDenied(
            "Vendor profile must be approved before managing inventory."
        )

    return vendor


class StockOperationMixin:
    def perform_stock_operation(self, request, record, operation_name):
        serializer = StockOperationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        quantity = serializer.validated_data["quantity"]
        reason = serializer.validated_data.get("reason", "")
        reference = serializer.validated_data.get("reference", "")

        operation = getattr(record, operation_name)

        try:
            operation(
                quantity,
                reason=reason,
                reference=reference,
                created_by=request.user,
            )
        except DjangoValidationError as exc:
            raise_drf_validation_error(exc)

        record.refresh_from_db()

        response_serializer = InventoryRecordReadSerializer(
            record,
            context={"request": request},
        )

        return Response(response_serializer.data, status=status.HTTP_200_OK)


@extend_schema_view(
    list=extend_schema(
        tags=["Vendor Inventory"],
        summary="List my inventory records",
        description="Returns inventory records for products owned by the authenticated approved vendor.",
    ),
    create=extend_schema(
        tags=["Vendor Inventory"],
        request=InventoryRecordWriteSerializer,
        responses={201: InventoryRecordReadSerializer},
        summary="Create inventory record",
        description="Creates a product-level or variant-level inventory record for the authenticated approved vendor.",
    ),
    retrieve=extend_schema(
        tags=["Vendor Inventory"],
        summary="Retrieve my inventory record",
        description="Returns one inventory record owned by the authenticated approved vendor.",
    ),
    partial_update=extend_schema(
        tags=["Vendor Inventory"],
        request=InventoryRecordWriteSerializer,
        responses={200: InventoryRecordReadSerializer},
        summary="Update inventory settings",
        description="Updates inventory settings such as low stock threshold, tracking, and backorder flags.",
    ),
)
class VendorInventoryRecordViewSet(StockOperationMixin, viewsets.ModelViewSet):
    permission_classes = [
        permissions.IsAuthenticated,
        IsVendor,
    ]

    http_method_names = [
        "get",
        "post",
        "patch",
        "head",
        "options",
    ]

    def get_vendor(self):
        return get_approved_vendor_for_user(self.request.user)

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return InventoryRecord.objects.none()

        vendor = self.get_vendor()

        return (
            InventoryRecord.objects.select_related(
                "product",
                "product__vendor",
                "variant",
            )
            .filter(product__vendor=vendor)
        )

    def get_serializer_class(self):
        if self.action in ["create", "partial_update"]:
            return InventoryRecordWriteSerializer

        return InventoryRecordReadSerializer

    def get_serializer_context(self):
        context = super().get_serializer_context()

        if getattr(self, "swagger_fake_view", False):
            return context

        context["vendor"] = self.get_vendor()
        return context

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        record = serializer.save()

        response_serializer = InventoryRecordReadSerializer(
            record,
            context={"request": request},
        )

        return Response(response_serializer.data, status=status.HTTP_201_CREATED)

    def partial_update(self, request, *args, **kwargs):
        record = self.get_object()

        serializer = self.get_serializer(
            record,
            data=request.data,
            partial=True,
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()

        record.refresh_from_db()

        response_serializer = InventoryRecordReadSerializer(
            record,
            context={"request": request},
        )

        return Response(response_serializer.data, status=status.HTTP_200_OK)

    @extend_schema(
        tags=["Vendor Inventory"],
        request=StockOperationSerializer,
        responses={
            200: InventoryRecordReadSerializer,
            400: OpenApiResponse(description="Invalid stock operation."),
        },
        summary="Increase stock",
        description="Increases quantity on hand and creates a stock movement audit record.",
    )
    @action(detail=True, methods=["post"], url_path="increase-stock")
    def increase_stock(self, request, pk=None):
        record = self.get_object()
        return self.perform_stock_operation(request, record, "increase_stock")

    @extend_schema(
        tags=["Vendor Inventory"],
        request=StockOperationSerializer,
        responses={
            200: InventoryRecordReadSerializer,
            400: OpenApiResponse(description="Invalid stock operation."),
        },
        summary="Decrease stock",
        description="Decreases available stock and creates a stock movement audit record.",
    )
    @action(detail=True, methods=["post"], url_path="decrease-stock")
    def decrease_stock(self, request, pk=None):
        record = self.get_object()
        return self.perform_stock_operation(request, record, "decrease_stock")


@extend_schema_view(
    list=extend_schema(
        tags=["Vendor Inventory"],
        summary="List my stock movements",
        description="Returns stock movement history for the authenticated approved vendor.",
    ),
    retrieve=extend_schema(
        tags=["Vendor Inventory"],
        summary="Retrieve my stock movement",
        description="Returns one stock movement for the authenticated approved vendor.",
    ),
)
class VendorStockMovementViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = StockMovementReadSerializer
    permission_classes = [
        permissions.IsAuthenticated,
        IsVendor,
    ]

    def get_vendor(self):
        return get_approved_vendor_for_user(self.request.user)

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return StockMovement.objects.none()

        vendor = self.get_vendor()

        return (
            StockMovement.objects.select_related(
                "inventory_record",
                "inventory_record__product",
                "inventory_record__product__vendor",
                "inventory_record__variant",
                "created_by",
            )
            .filter(inventory_record__product__vendor=vendor)
        )


@extend_schema_view(
    list=extend_schema(
        tags=["Admin Inventory"],
        summary="List inventory records",
        description="Admin-only endpoint to list all inventory records.",
    ),
    retrieve=extend_schema(
        tags=["Admin Inventory"],
        summary="Retrieve inventory record",
        description="Admin-only endpoint to retrieve one inventory record.",
    ),
)
class AdminInventoryRecordViewSet(StockOperationMixin, viewsets.ReadOnlyModelViewSet):
    serializer_class = InventoryRecordReadSerializer
    permission_classes = [
        permissions.IsAuthenticated,
        IsAdmin,
    ]

    queryset = InventoryRecord.objects.select_related(
        "product",
        "product__vendor",
        "variant",
    ).all()

    @extend_schema(
        tags=["Admin Inventory"],
        request=StockOperationSerializer,
        responses={200: InventoryRecordReadSerializer},
        summary="Increase stock",
        description="Admin-only stock increase operation.",
    )
    @action(detail=True, methods=["post"], url_path="increase-stock")
    def increase_stock(self, request, pk=None):
        record = self.get_object()
        return self.perform_stock_operation(request, record, "increase_stock")

    @extend_schema(
        tags=["Admin Inventory"],
        request=StockOperationSerializer,
        responses={200: InventoryRecordReadSerializer},
        summary="Decrease stock",
        description="Admin-only stock decrease operation.",
    )
    @action(detail=True, methods=["post"], url_path="decrease-stock")
    def decrease_stock(self, request, pk=None):
        record = self.get_object()
        return self.perform_stock_operation(request, record, "decrease_stock")

    @extend_schema(
        tags=["Admin Inventory"],
        request=StockOperationSerializer,
        responses={200: InventoryRecordReadSerializer},
        summary="Reserve stock",
        description="Admin-only stock reservation operation.",
    )
    @action(detail=True, methods=["post"], url_path="reserve-stock")
    def reserve_stock(self, request, pk=None):
        record = self.get_object()
        return self.perform_stock_operation(request, record, "reserve_stock")

    @extend_schema(
        tags=["Admin Inventory"],
        request=StockOperationSerializer,
        responses={200: InventoryRecordReadSerializer},
        summary="Release reservation",
        description="Admin-only reservation release operation.",
    )
    @action(detail=True, methods=["post"], url_path="release-reservation")
    def release_reservation(self, request, pk=None):
        record = self.get_object()
        return self.perform_stock_operation(request, record, "release_reservation")

    @extend_schema(
        tags=["Admin Inventory"],
        request=StockOperationSerializer,
        responses={200: InventoryRecordReadSerializer},
        summary="Commit reservation",
        description="Admin-only operation to convert reserved stock into sold stock.",
    )
    @action(detail=True, methods=["post"], url_path="commit-reservation")
    def commit_reservation(self, request, pk=None):
        record = self.get_object()
        return self.perform_stock_operation(request, record, "commit_reservation")


@extend_schema_view(
    list=extend_schema(
        tags=["Admin Inventory"],
        summary="List stock movements",
        description="Admin-only endpoint to list all stock movements.",
    ),
    retrieve=extend_schema(
        tags=["Admin Inventory"],
        summary="Retrieve stock movement",
        description="Admin-only endpoint to retrieve one stock movement.",
    ),
)
class AdminStockMovementViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = StockMovementReadSerializer
    permission_classes = [
        permissions.IsAuthenticated,
        IsAdmin,
    ]

    queryset = StockMovement.objects.select_related(
        "inventory_record",
        "inventory_record__product",
        "inventory_record__product__vendor",
        "inventory_record__variant",
        "created_by",
    ).all()