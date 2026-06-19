from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    AdminOrderItemViewSet,
    AdminOrderViewSet,
    AdminVendorOrderViewSet,
    CustomerOrderViewSet,
    VendorOrderViewSet,
)

router = DefaultRouter()

router.register(
    "my-orders",
    CustomerOrderViewSet,
    basename="customer-orders",
)

router.register(
    "vendor/orders",
    VendorOrderViewSet,
    basename="vendor-orders",
)

router.register(
    "admin/orders",
    AdminOrderViewSet,
    basename="admin-orders",
)

router.register(
    "admin/vendor-orders",
    AdminVendorOrderViewSet,
    basename="admin-vendor-orders",
)

router.register(
    "admin/items",
    AdminOrderItemViewSet,
    basename="admin-order-items",
)

urlpatterns = [
    path("", include(router.urls)),
]