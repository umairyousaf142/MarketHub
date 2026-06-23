from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.reviews.views import (
    AdminReviewViewSet,
    CustomerReviewViewSet,
    PublicReviewViewSet,
)


router = DefaultRouter()

router.register(
    r"reviews",
    CustomerReviewViewSet,
    basename="customer-reviews",
)

router.register(
    r"public/reviews",
    PublicReviewViewSet,
    basename="public-reviews",
)

router.register(
    r"admin/reviews",
    AdminReviewViewSet,
    basename="admin-reviews",
)


urlpatterns = [
    path("", include(router.urls)),
]