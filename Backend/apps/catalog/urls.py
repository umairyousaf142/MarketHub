from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    AdminBrandViewSet,
    AdminCategoryViewSet,
    AdminProductViewSet,
    PublicBrandViewSet,
    PublicCategoryViewSet,
    PublicProductViewSet,
    VendorProductImageViewSet,
    VendorProductVariantViewSet,
    VendorProductViewSet,
)

router = DefaultRouter()

router.register(
    "categories",
    PublicCategoryViewSet,
    basename="public-categories",
)

router.register(
    "brands",
    PublicBrandViewSet,
    basename="public-brands",
)

router.register(
    "products",
    PublicProductViewSet,
    basename="public-products",
)

router.register(
    "vendor/products",
    VendorProductViewSet,
    basename="vendor-products",
)

router.register(
    "admin/categories",
    AdminCategoryViewSet,
    basename="admin-categories",
)

router.register(
    "admin/brands",
    AdminBrandViewSet,
    basename="admin-brands",
)

router.register(
    "admin/products",
    AdminProductViewSet,
    basename="admin-products",
)

vendor_product_images = VendorProductImageViewSet.as_view(
    {
        "get": "list",
        "post": "create",
    }
)

vendor_product_image_detail = VendorProductImageViewSet.as_view(
    {
        "get": "retrieve",
        "patch": "partial_update",
        "delete": "destroy",
    }
)

vendor_product_variants = VendorProductVariantViewSet.as_view(
    {
        "get": "list",
        "post": "create",
    }
)

vendor_product_variant_detail = VendorProductVariantViewSet.as_view(
    {
        "get": "retrieve",
        "patch": "partial_update",
        "delete": "destroy",
    }
)

urlpatterns = [
    path("", include(router.urls)),
    path(
        "vendor/products/<uuid:product_id>/images/",
        vendor_product_images,
        name="vendor-product-images-list",
    ),
    path(
        "vendor/products/<uuid:product_id>/images/<uuid:pk>/",
        vendor_product_image_detail,
        name="vendor-product-images-detail",
    ),
    path(
        "vendor/products/<uuid:product_id>/variants/",
        vendor_product_variants,
        name="vendor-product-variants-list",
    ),
    path(
        "vendor/products/<uuid:product_id>/variants/<uuid:pk>/",
        vendor_product_variant_detail,
        name="vendor-product-variants-detail",
    ),
]