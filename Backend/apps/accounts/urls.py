from django.urls import include, path
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenRefreshView, TokenVerifyView

# from .views import AddressViewSet, LoginView, MeView, RegisterView
from .views import (
    AddressViewSet,
    ChangePasswordView,
    ForgotPasswordView,
    LoginView,
    LogoutView,
    MeView,
    RegisterView,
    ResetPasswordView,
    VerifyEmailView,
)

router = DefaultRouter()
router.register("addresses", AddressViewSet, basename="addresses")

urlpatterns = [
    path("register/", RegisterView.as_view(), name="accounts-register"),
    path("login/", LoginView.as_view(), name="accounts-login"),
    path("token/refresh/", TokenRefreshView.as_view(), name="token-refresh"),
    path("token/verify/", TokenVerifyView.as_view(), name="token-verify"),
    path("me/", MeView.as_view(), name="accounts-me"),
    path(
        "change-password/",
        ChangePasswordView.as_view(),
        name="accounts-change-password",
    ),
    path(
        "forgot-password/",
        ForgotPasswordView.as_view(),
        name="accounts-forgot-password",
    ),
    path(
        "reset-password/",
        ResetPasswordView.as_view(),
        name="accounts-reset-password",
    ),
    path(
        "verify-email/",
        VerifyEmailView.as_view(),
        name="accounts-verify-email",
    ),
    path("", include(router.urls)),
]