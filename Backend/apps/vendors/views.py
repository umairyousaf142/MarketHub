from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import (
    OpenApiParameter,
    OpenApiResponse,
    extend_schema,
    extend_schema_view,
)

VENDOR_DOCUMENT_ID_PATH_PARAMETER = OpenApiParameter(
    name="id",
    type=OpenApiTypes.UUID,
    location=OpenApiParameter.PATH,
    description="Vendor document ID.",
)

from rest_framework import generics, mixins, permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError as DRFValidationError
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response

from core.permissions.base import IsAdmin, IsVendor

from .models import CommissionPlan, Vendor, VendorDocument
from .serializers import (
    AdminVendorReadSerializer,
    CommissionPlanSerializer,
    DetailResponseSerializer,
    VendorDocumentSerializer,
    VendorOnboardingSerializer,
    VendorProfileUpdateSerializer,
    VendorReadSerializer,
    AdminVendorDocumentReadSerializer,
)


def raise_drf_validation_error(exc):
    if hasattr(exc, "message_dict"):
        raise DRFValidationError(exc.message_dict)

    if hasattr(exc, "messages"):
        raise DRFValidationError({"detail": exc.messages})

    raise DRFValidationError({"detail": str(exc)})


@extend_schema(
    tags=["Vendors"],
    request=VendorOnboardingSerializer,
    responses={
        201: VendorReadSerializer,
        400: OpenApiResponse(description="Validation error."),
        403: OpenApiResponse(description="Only VENDOR users can onboard."),
    },
    summary="Create vendor profile",
    description=(
        "Creates a pending vendor profile for the authenticated VENDOR user. "
        "Each user can only have one vendor profile."
    ),
)
class VendorOnboardingView(generics.CreateAPIView):
    serializer_class = VendorOnboardingSerializer
    permission_classes = [
        permissions.IsAuthenticated,
        IsVendor,
    ]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        with transaction.atomic():
            vendor = serializer.save()

        response_serializer = VendorReadSerializer(
            vendor,
            context={"request": request},
        )

        return Response(response_serializer.data, status=status.HTTP_201_CREATED)


@extend_schema(
    tags=["Vendors"],
    responses={
        200: VendorReadSerializer,
        404: OpenApiResponse(description="Vendor profile not found."),
    },
    summary="Get or update my vendor profile",
    description=(
        "Returns or updates the authenticated vendor's own profile. "
        "Only store_name can be updated by the vendor."
    ),
)
class VendorMeView(generics.RetrieveUpdateAPIView):
    permission_classes = [
        permissions.IsAuthenticated,
        IsVendor,
    ]

    http_method_names = [
        "get",
        "patch",
        "head",
        "options",
    ]

    def get_serializer_class(self):
        if self.request.method == "PATCH":
            return VendorProfileUpdateSerializer

        return VendorReadSerializer

    def get_object(self):
        vendor = (
            Vendor.objects.select_related(
                "user",
                "commission_plan",
                "approved_by",
            )
            .filter(user=self.request.user)
            .first()
        )

        if not vendor:
            raise NotFound("Vendor profile not found. Complete onboarding first.")

        return vendor

    def partial_update(self, request, *args, **kwargs):
        vendor = self.get_object()

        serializer = self.get_serializer(
            vendor,
            data=request.data,
            partial=True,
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()

        response_serializer = VendorReadSerializer(
            vendor,
            context={"request": request},
        )

        return Response(response_serializer.data, status=status.HTTP_200_OK)


@extend_schema_view(
    list=extend_schema(
        tags=["Vendor Documents"],
        summary="List my vendor documents",
        description="Returns documents uploaded by the authenticated vendor.",
    ),
    create=extend_schema(
        tags=["Vendor Documents"],
        summary="Upload vendor document",
        description="Uploads a KYC document for the authenticated vendor.",
    ),
    retrieve=extend_schema(
        tags=["Vendor Documents"],
        summary="Retrieve my vendor document",
        description="Returns one document owned by the authenticated vendor.",
        parameters=[VENDOR_DOCUMENT_ID_PATH_PARAMETER],
    ),
    partial_update=extend_schema(
        tags=["Vendor Documents"],
        summary="Update my vendor document",
        description="Updates document type or file for the authenticated vendor.",
        parameters=[VENDOR_DOCUMENT_ID_PATH_PARAMETER],
    ),
    destroy=extend_schema(
        tags=["Vendor Documents"],
        summary="Delete my vendor document",
        description="Deletes a document owned by the authenticated vendor.",
        parameters=[VENDOR_DOCUMENT_ID_PATH_PARAMETER],
    ),
)
class VendorDocumentViewSet(viewsets.ModelViewSet):
    serializer_class = VendorDocumentSerializer
    permission_classes = [
        permissions.IsAuthenticated,
        IsVendor,
    ]
    parser_classes = [
        MultiPartParser,
        FormParser,
    ]
    http_method_names = [
        "get",
        "post",
        "patch",
        "delete",
        "head",
        "options",
    ]

    def get_vendor(self):
        vendor = Vendor.objects.filter(user=self.request.user).first()

        if not vendor:
            raise NotFound("Vendor profile not found. Complete onboarding first.")

        return vendor

    def get_queryset(self):
        vendor = self.get_vendor()

        return VendorDocument.objects.filter(vendor=vendor).select_related("vendor")

    def perform_create(self, serializer):
        vendor = self.get_vendor()
        serializer.save(vendor=vendor)

    def perform_update(self, serializer):
        serializer.save()


@extend_schema_view(
    list=extend_schema(
        tags=["Admin Vendors"],
        summary="List vendors",
        description="Admin-only endpoint to list all vendors.",
    ),
    retrieve=extend_schema(
        tags=["Admin Vendors"],
        summary="Retrieve vendor",
        description="Admin-only endpoint to retrieve a vendor profile.",
    ),
)
class AdminVendorViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = AdminVendorReadSerializer
    permission_classes = [
        permissions.IsAuthenticated,
        IsAdmin,
    ]

    queryset = Vendor.objects.select_related(
        "user",
        "commission_plan",
        "approved_by",
    ).all()

    @extend_schema(
        tags=["Admin Vendors"],
        responses={
            200: AdminVendorReadSerializer,
            400: OpenApiResponse(description="Invalid transition."),
        },
        summary="Approve vendor",
        description="Approves a pending vendor. Only ADMIN users can perform this action.",
    )
    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        vendor = self.get_object()

        try:
            vendor.approve(request.user)
        except DjangoValidationError as exc:
            raise_drf_validation_error(exc)

        serializer = self.get_serializer(vendor)

        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(
        tags=["Admin Vendors"],
        responses={
            200: AdminVendorReadSerializer,
            400: OpenApiResponse(description="Invalid transition."),
        },
        summary="Reject vendor",
        description="Rejects a pending vendor. Only ADMIN users can perform this action.",
    )
    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        vendor = self.get_object()

        try:
            vendor.reject(request.user)
        except DjangoValidationError as exc:
            raise_drf_validation_error(exc)

        serializer = self.get_serializer(vendor)

        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(
        tags=["Admin Vendors"],
        responses={
            200: AdminVendorReadSerializer,
            400: OpenApiResponse(description="Invalid transition."),
        },
        summary="Suspend vendor",
        description="Suspends an approved vendor. Only ADMIN users can perform this action.",
    )
    @action(detail=True, methods=["post"])
    def suspend(self, request, pk=None):
        vendor = self.get_object()

        try:
            vendor.suspend(request.user)
        except DjangoValidationError as exc:
            raise_drf_validation_error(exc)

        serializer = self.get_serializer(vendor)

        return Response(serializer.data, status=status.HTTP_200_OK)



@extend_schema_view(
    list=extend_schema(
        tags=["Admin Vendor Documents"],
        summary="List vendor documents",
        description="Admin-only endpoint to list all uploaded vendor KYC documents.",
    ),
    retrieve=extend_schema(
        tags=["Admin Vendor Documents"],
        summary="Retrieve vendor document",
        description="Admin-only endpoint to retrieve a vendor KYC document.",
    ),
)
class AdminVendorDocumentViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = AdminVendorDocumentReadSerializer
    permission_classes = [
        permissions.IsAuthenticated,
        IsAdmin,
    ]

    queryset = VendorDocument.objects.select_related(
        "vendor",
        "vendor__user",
    ).all()

    @extend_schema(
        tags=["Admin Vendor Documents"],
        responses={
            200: AdminVendorDocumentReadSerializer,
        },
        summary="Verify vendor document",
        description="Marks a vendor KYC document as verified. Only ADMIN users can perform this action.",
    )
    @action(detail=True, methods=["post"])
    def verify(self, request, pk=None):
        document = self.get_object()

        if not document.verified:
            document.verified = True
            document.save(update_fields=["verified"])

        serializer = self.get_serializer(document)

        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(
        tags=["Admin Vendor Documents"],
        responses={
            200: AdminVendorDocumentReadSerializer,
        },
        summary="Unverify vendor document",
        description="Marks a vendor KYC document as unverified. Only ADMIN users can perform this action.",
    )
    @action(detail=True, methods=["post"])
    def unverify(self, request, pk=None):
        document = self.get_object()

        if document.verified:
            document.verified = False
            document.save(update_fields=["verified"])

        serializer = self.get_serializer(document)

        return Response(serializer.data, status=status.HTTP_200_OK)



@extend_schema_view(
    list=extend_schema(
        tags=["Admin Commission Plans"],
        summary="List commission plans",
        description="Admin-only endpoint to list commission plans.",
    ),
    create=extend_schema(
        tags=["Admin Commission Plans"],
        summary="Create commission plan",
        description="Admin-only endpoint to create a commission plan.",
    ),
    retrieve=extend_schema(
        tags=["Admin Commission Plans"],
        summary="Retrieve commission plan",
        description="Admin-only endpoint to retrieve one commission plan.",
    ),
    update=extend_schema(
        tags=["Admin Commission Plans"],
        summary="Update commission plan",
        description="Admin-only endpoint to update a commission plan.",
    ),
    partial_update=extend_schema(
        tags=["Admin Commission Plans"],
        summary="Partially update commission plan",
        description="Admin-only endpoint to partially update a commission plan.",
    ),
    destroy=extend_schema(
        tags=["Admin Commission Plans"],
        summary="Delete commission plan",
        description="Admin-only endpoint to delete a commission plan.",
    ),
)

class CommissionPlanViewSet(viewsets.ModelViewSet):
    serializer_class = CommissionPlanSerializer
    permission_classes = [
        permissions.IsAuthenticated,
        IsAdmin,
    ]

    queryset = CommissionPlan.objects.all()

    def perform_create(self, serializer):
        try:
            serializer.save()
        except DjangoValidationError as exc:
            raise_drf_validation_error(exc)

    def perform_update(self, serializer):
        try:
            serializer.save()
        except DjangoValidationError as exc:
            raise_drf_validation_error(exc)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()

        try:
            instance.delete()
        except DjangoValidationError as exc:
            raise_drf_validation_error(exc)

        return Response(status=status.HTTP_204_NO_CONTENT)