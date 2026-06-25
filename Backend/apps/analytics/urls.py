from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.analytics.views import (
    AdminAnalyticsSnapshotViewSet,
    VendorDashboardAPIView,
)


router = DefaultRouter()
router.register(
    "admin/snapshots",
    AdminAnalyticsSnapshotViewSet,
    basename="admin-analytics-snapshots",
)


urlpatterns = [
    path("", include(router.urls)),
    path(
        "vendor/dashboard/",
        VendorDashboardAPIView.as_view(),
        name="vendor-analytics-dashboard",
    ),
]