from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.coupons.views import (
    AdminCouponUsageViewSet,
    AdminCouponViewSet,
    CustomerCouponViewSet,
)


router = DefaultRouter()

router.register(
    r"coupons",
    CustomerCouponViewSet,
    basename="customer-coupons",
)

router.register(
    r"admin/coupons",
    AdminCouponViewSet,
    basename="admin-coupons",
)

router.register(
    r"admin/coupon-usages",
    AdminCouponUsageViewSet,
    basename="admin-coupon-usages",
)


urlpatterns = [
    path("", include(router.urls)),
]