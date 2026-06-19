from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    AdminCartItemViewSet,
    AdminCartViewSet,
    CustomerCartViewSet,
)

router = DefaultRouter()

router.register(
    "my-cart",
    CustomerCartViewSet,
    basename="customer-cart",
)

router.register(
    "admin/carts",
    AdminCartViewSet,
    basename="admin-carts",
)

router.register(
    "admin/items",
    AdminCartItemViewSet,
    basename="admin-cart-items",
)

urlpatterns = [
    path("", include(router.urls)),
]