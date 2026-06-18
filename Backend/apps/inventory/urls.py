from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    AdminInventoryRecordViewSet,
    AdminStockMovementViewSet,
    VendorInventoryRecordViewSet,
    VendorStockMovementViewSet,
)

router = DefaultRouter()

router.register(
    "vendor/records",
    VendorInventoryRecordViewSet,
    basename="vendor-inventory-records",
)

router.register(
    "vendor/movements",
    VendorStockMovementViewSet,
    basename="vendor-stock-movements",
)

router.register(
    "admin/records",
    AdminInventoryRecordViewSet,
    basename="admin-inventory-records",
)

router.register(
    "admin/movements",
    AdminStockMovementViewSet,
    basename="admin-stock-movements",
)

urlpatterns = [
    path("", include(router.urls)),
]