from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    AdminVendorViewSet,
    CommissionPlanViewSet,
    VendorDocumentViewSet,
    VendorMeView,
    VendorOnboardingView,
    AdminVendorDocumentViewSet,
)

router = DefaultRouter()
router.register("documents", VendorDocumentViewSet, basename="vendor-documents")
router.register("admin/vendors", AdminVendorViewSet, basename="admin-vendors")
router.register(
    "admin/documents",
    AdminVendorDocumentViewSet,
    basename="admin-vendor-documents",
)
router.register(
    "admin/commission-plans",
    CommissionPlanViewSet,
    basename="admin-commission-plans",
)

urlpatterns = [
    path("onboarding/", VendorOnboardingView.as_view(), name="vendor-onboarding"),
    path("me/", VendorMeView.as_view(), name="vendor-me"),
    path("", include(router.urls)),
]