from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.payments.views import (
    AdminPaymentViewSet,
    CustomerPaymentViewSet,
    PaymentWebhookAPIView,
)


router = DefaultRouter()

router.register(
    r"payments",
    CustomerPaymentViewSet,
    basename="customer-payments",
)

router.register(
    r"admin/payments",
    AdminPaymentViewSet,
    basename="admin-payments",
)


urlpatterns = [
    path("", include(router.urls)),
    path(
        "webhooks/payments/<str:provider>/",
        PaymentWebhookAPIView.as_view(),
        name="payment-webhook",
    ),
]