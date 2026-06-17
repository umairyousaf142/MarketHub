from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404

from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_view
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError as DRFValidationError
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response

from core.permissions.base import IsAdmin, IsVendor

from apps.catalog.models import Brand, Category, Product, ProductImage, ProductVariant
from apps.vendors.models import Vendor

from .serializers import (
    AdminProductReadSerializer,
    BrandSerializer,
    CategorySerializer,
    DetailResponseSerializer,
    ProductImageSerializer,
    ProductVariantSerializer,
    PublicBrandSerializer,
    PublicCategorySerializer,
    PublicProductDetailSerializer,
    PublicProductListSerializer,
    VendorProductReadSerializer,
    VendorProductWriteSerializer,
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
            "Vendor profile must be approved before managing catalog products."
        )

    return vendor


@extend_schema_view(
    list=extend_schema(
        tags=["Public Catalog"],
        summary="List public categories",
        description="Returns active categories for public browsing.",
    ),
    retrieve=extend_schema(
        tags=["Public Catalog"],
        summary="Retrieve public category",
        description="Returns one active category by slug.",
    ),
)
class PublicCategoryViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = PublicCategorySerializer
    permission_classes = [permissions.AllowAny]
    lookup_field = "slug"

    queryset = Category.objects.select_related("parent").filter(is_active=True)


@extend_schema_view(
    list=extend_schema(
        tags=["Public Catalog"],
        summary="List public brands",
        description="Returns active brands for public browsing.",
    ),
    retrieve=extend_schema(
        tags=["Public Catalog"],
        summary="Retrieve public brand",
        description="Returns one active brand by slug.",
    ),
)
class PublicBrandViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = PublicBrandSerializer
    permission_classes = [permissions.AllowAny]
    lookup_field = "slug"

    queryset = Brand.objects.filter(is_active=True)


@extend_schema_view(
    list=extend_schema(
        tags=["Public Catalog"],
        summary="List public products",
        description=(
            "Returns active products from approved vendors. "
            "Supports query params: search, category, brand, vendor, featured, min_price, max_price."
        ),
    ),
    retrieve=extend_schema(
        tags=["Public Catalog"],
        summary="Retrieve public product",
        description="Returns one active product by slug.",
    ),
)
class PublicProductViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [permissions.AllowAny]
    lookup_field = "slug"

    def get_serializer_class(self):
        if self.action == "retrieve":
            return PublicProductDetailSerializer

        return PublicProductListSerializer

    def get_queryset(self):
        queryset = (
            Product.objects.select_related(
                "vendor",
                "category",
                "brand",
            )
            .prefetch_related(
                "images",
                "variants",
            )
            .filter(
                status=Product.Status.ACTIVE,
                vendor__status=Vendor.Status.APPROVED,
                category__is_active=True,
            )
            .filter(
                Q(brand__isnull=True) | Q(brand__is_active=True)
            )
        )

        search = self.request.query_params.get("search")
        category = self.request.query_params.get("category")
        brand = self.request.query_params.get("brand")
        vendor = self.request.query_params.get("vendor")
        featured = self.request.query_params.get("featured")
        min_price = self.request.query_params.get("min_price")
        max_price = self.request.query_params.get("max_price")

        if search:
            queryset = queryset.filter(
                Q(name__icontains=search)
                | Q(short_description__icontains=search)
                | Q(description__icontains=search)
                | Q(sku__icontains=search)
            )

        if category:
            queryset = queryset.filter(category__slug__iexact=category)

        if brand:
            queryset = queryset.filter(brand__slug__iexact=brand)

        if vendor:
            queryset = queryset.filter(vendor__id=vendor)

        if featured in ["true", "1", "yes"]:
            queryset = queryset.filter(is_featured=True)

        if min_price:
            queryset = queryset.filter(base_price__gte=min_price)

        if max_price:
            queryset = queryset.filter(base_price__lte=max_price)

        return queryset


@extend_schema_view(
    list=extend_schema(
        tags=["Vendor Catalog"],
        summary="List my products",
        description="Returns products owned by the authenticated approved vendor.",
    ),
    create=extend_schema(
        tags=["Vendor Catalog"],
        request=VendorProductWriteSerializer,
        responses={201: VendorProductReadSerializer},
        summary="Create product",
        description="Creates a product for the authenticated approved vendor.",
    ),
    retrieve=extend_schema(
        tags=["Vendor Catalog"],
        summary="Retrieve my product",
        description="Returns one product owned by the authenticated approved vendor.",
    ),
    partial_update=extend_schema(
        tags=["Vendor Catalog"],
        request=VendorProductWriteSerializer,
        responses={200: VendorProductReadSerializer},
        summary="Update my product",
        description="Updates a product owned by the authenticated approved vendor.",
    ),
    destroy=extend_schema(
        tags=["Vendor Catalog"],
        responses={204: OpenApiResponse(description="Product archived.")},
        summary="Archive my product",
        description="Archives a product owned by the authenticated approved vendor.",
    ),
)
class VendorProductViewSet(viewsets.ModelViewSet):
    permission_classes = [
        permissions.IsAuthenticated,
        IsVendor,
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
        return get_approved_vendor_for_user(self.request.user)

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Product.objects.none()
        
        vendor = self.get_vendor()

        return (
            Product.objects.select_related(
                "vendor",
                "category",
                "brand",
            )
            .prefetch_related(
                "images",
                "variants",
            )
            .filter(vendor=vendor)
        )

    def get_serializer_class(self):
        if self.action in ["create", "partial_update"]:
            return VendorProductWriteSerializer

        return VendorProductReadSerializer

    def get_serializer_context(self):
        context = super().get_serializer_context()
        if getattr(self, "swagger_fake_view", False):
            return context
        context["vendor"] = self.get_vendor()
        return context

    def create(self, request, *args, **kwargs):
        vendor = self.get_vendor()

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        with transaction.atomic():
            product = serializer.save(vendor=vendor)

        response_serializer = VendorProductReadSerializer(
            product,
            context={"request": request},
        )

        return Response(response_serializer.data, status=status.HTTP_201_CREATED)

    def partial_update(self, request, *args, **kwargs):
        product = self.get_object()

        serializer = self.get_serializer(
            product,
            data=request.data,
            partial=True,
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()

        product.refresh_from_db()

        response_serializer = VendorProductReadSerializer(
            product,
            context={"request": request},
        )

        return Response(response_serializer.data, status=status.HTTP_200_OK)

    def destroy(self, request, *args, **kwargs):
        product = self.get_object()
        product.status = Product.Status.ARCHIVED
        product.save(update_fields=["status"])

        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(
        tags=["Vendor Catalog"],
        responses={
            200: VendorProductReadSerializer,
            400: OpenApiResponse(description="Invalid product status transition."),
        },
        summary="Submit product for review",
        description="Moves a vendor-owned product to pending review.",
    )
    @action(detail=True, methods=["post"], url_path="submit-for-review")
    def submit_for_review(self, request, pk=None):
        product = self.get_object()

        if product.status not in [
            Product.Status.DRAFT,
            Product.Status.REJECTED,
        ]:
            raise DRFValidationError(
                {"detail": "Only DRAFT or REJECTED products can be submitted for review."}
            )

        product.status = Product.Status.PENDING_REVIEW
        product.save(update_fields=["status"])

        serializer = self.get_serializer(product)

        return Response(serializer.data, status=status.HTTP_200_OK)


@extend_schema_view(
    list=extend_schema(
        tags=["Vendor Product Images"],
        summary="List product images",
        description="Returns images for a vendor-owned product.",
    ),
    create=extend_schema(
        tags=["Vendor Product Images"],
        summary="Upload product image",
        description="Uploads an image for a vendor-owned product.",
    ),
    retrieve=extend_schema(
        tags=["Vendor Product Images"],
        summary="Retrieve product image",
        description="Returns one image for a vendor-owned product.",
    ),
    partial_update=extend_schema(
        tags=["Vendor Product Images"],
        summary="Update product image",
        description="Updates image metadata or file for a vendor-owned product.",
    ),
    destroy=extend_schema(
        tags=["Vendor Product Images"],
        summary="Delete product image",
        description="Deletes one image from a vendor-owned product.",
    ),
)
class VendorProductImageViewSet(viewsets.ModelViewSet):
    serializer_class = ProductImageSerializer
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
        return get_approved_vendor_for_user(self.request.user)

    def get_product(self):
        vendor = self.get_vendor()

        return get_object_or_404(
            Product,
            id=self.kwargs["product_id"],
            vendor=vendor,
        )

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return ProductImage.objects.none()
        product = self.get_product()

        return ProductImage.objects.filter(product=product)

    def perform_create(self, serializer):
        product = self.get_product()

        try:
            serializer.save(product=product)
        except DjangoValidationError as exc:
            raise_drf_validation_error(exc)

    def perform_update(self, serializer):
        try:
            serializer.save()
        except DjangoValidationError as exc:
            raise_drf_validation_error(exc)


@extend_schema_view(
    list=extend_schema(
        tags=["Vendor Product Variants"],
        summary="List product variants",
        description="Returns variants for a vendor-owned product.",
    ),
    create=extend_schema(
        tags=["Vendor Product Variants"],
        summary="Create product variant",
        description="Creates a variant for a vendor-owned product.",
    ),
    retrieve=extend_schema(
        tags=["Vendor Product Variants"],
        summary="Retrieve product variant",
        description="Returns one variant for a vendor-owned product.",
    ),
    partial_update=extend_schema(
        tags=["Vendor Product Variants"],
        summary="Update product variant",
        description="Updates a variant for a vendor-owned product.",
    ),
    destroy=extend_schema(
        tags=["Vendor Product Variants"],
        summary="Delete product variant",
        description="Deletes one variant from a vendor-owned product.",
    ),
)
class VendorProductVariantViewSet(viewsets.ModelViewSet):
    serializer_class = ProductVariantSerializer
    permission_classes = [
        permissions.IsAuthenticated,
        IsVendor,
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
        return get_approved_vendor_for_user(self.request.user)

    def get_product(self):
        vendor = self.get_vendor()

        return get_object_or_404(
            Product,
            id=self.kwargs["product_id"],
            vendor=vendor,
        )

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return ProductVariant.objects.none()
        product = self.get_product()

        return ProductVariant.objects.filter(product=product)

    def get_serializer_context(self):
        context = super().get_serializer_context()
        if getattr(self, "swagger_fake_view", False):
            return context
        context["product"] = self.get_product()
        return context

    def perform_create(self, serializer):
        product = self.get_product()

        try:
            serializer.save(product=product)
        except DjangoValidationError as exc:
            raise_drf_validation_error(exc)

    def perform_update(self, serializer):
        try:
            serializer.save()
        except DjangoValidationError as exc:
            raise_drf_validation_error(exc)


@extend_schema_view(
    list=extend_schema(
        tags=["Admin Catalog"],
        summary="List categories",
        description="Admin-only endpoint to list categories.",
    ),
    create=extend_schema(
        tags=["Admin Catalog"],
        summary="Create category",
        description="Admin-only endpoint to create a category.",
    ),
    retrieve=extend_schema(
        tags=["Admin Catalog"],
        summary="Retrieve category",
        description="Admin-only endpoint to retrieve one category.",
    ),
    partial_update=extend_schema(
        tags=["Admin Catalog"],
        summary="Update category",
        description="Admin-only endpoint to update a category.",
    ),
    destroy=extend_schema(
        tags=["Admin Catalog"],
        summary="Delete category",
        description="Admin-only endpoint to delete a category.",
    ),
)
class AdminCategoryViewSet(viewsets.ModelViewSet):
    serializer_class = CategorySerializer
    permission_classes = [
        permissions.IsAuthenticated,
        IsAdmin,
    ]
    queryset = Category.objects.select_related("parent").all()

    http_method_names = [
        "get",
        "post",
        "patch",
        "delete",
        "head",
        "options",
    ]


@extend_schema_view(
    list=extend_schema(
        tags=["Admin Catalog"],
        summary="List brands",
        description="Admin-only endpoint to list brands.",
    ),
    create=extend_schema(
        tags=["Admin Catalog"],
        summary="Create brand",
        description="Admin-only endpoint to create a brand.",
    ),
    retrieve=extend_schema(
        tags=["Admin Catalog"],
        summary="Retrieve brand",
        description="Admin-only endpoint to retrieve one brand.",
    ),
    partial_update=extend_schema(
        tags=["Admin Catalog"],
        summary="Update brand",
        description="Admin-only endpoint to update a brand.",
    ),
    destroy=extend_schema(
        tags=["Admin Catalog"],
        summary="Delete brand",
        description="Admin-only endpoint to delete a brand.",
    ),
)
class AdminBrandViewSet(viewsets.ModelViewSet):
    serializer_class = BrandSerializer
    permission_classes = [
        permissions.IsAuthenticated,
        IsAdmin,
    ]
    queryset = Brand.objects.all()

    http_method_names = [
        "get",
        "post",
        "patch",
        "delete",
        "head",
        "options",
    ]


@extend_schema_view(
    list=extend_schema(
        tags=["Admin Product Review"],
        summary="List products",
        description="Admin-only endpoint to list all products.",
    ),
    retrieve=extend_schema(
        tags=["Admin Product Review"],
        summary="Retrieve product",
        description="Admin-only endpoint to retrieve one product.",
    ),
)
class AdminProductViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = AdminProductReadSerializer
    permission_classes = [
        permissions.IsAuthenticated,
        IsAdmin,
    ]

    queryset = (
        Product.objects.select_related(
            "vendor",
            "category",
            "brand",
        )
        .prefetch_related(
            "images",
            "variants",
        )
        .all()
    )

    @extend_schema(
        tags=["Admin Product Review"],
        responses={
            200: AdminProductReadSerializer,
            400: OpenApiResponse(description="Invalid product transition."),
        },
        summary="Approve product",
        description="Approves a pending review product and makes it active.",
    )
    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        product = self.get_object()

        if product.status != Product.Status.PENDING_REVIEW:
            raise DRFValidationError(
                {"detail": "Only PENDING_REVIEW products can be approved."}
            )

        product.status = Product.Status.ACTIVE

        try:
            product.save(update_fields=["status"])
        except DjangoValidationError as exc:
            raise_drf_validation_error(exc)

        serializer = self.get_serializer(product)

        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(
        tags=["Admin Product Review"],
        responses={
            200: AdminProductReadSerializer,
            400: OpenApiResponse(description="Invalid product transition."),
        },
        summary="Reject product",
        description="Rejects a pending review product.",
    )
    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        product = self.get_object()

        if product.status != Product.Status.PENDING_REVIEW:
            raise DRFValidationError(
                {"detail": "Only PENDING_REVIEW products can be rejected."}
            )

        product.status = Product.Status.REJECTED
        product.save(update_fields=["status"])

        serializer = self.get_serializer(product)

        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(
        tags=["Admin Product Review"],
        responses={200: AdminProductReadSerializer},
        summary="Archive product",
        description="Archives a product.",
    )
    @action(detail=True, methods=["post"])
    def archive(self, request, pk=None):
        product = self.get_object()

        product.status = Product.Status.ARCHIVED
        product.save(update_fields=["status"])

        serializer = self.get_serializer(product)

        return Response(serializer.data, status=status.HTTP_200_OK)