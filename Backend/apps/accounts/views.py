from drf_spectacular.utils import (
    OpenApiResponse,
    extend_schema,
    extend_schema_view,
)
from rest_framework import generics, permissions, status, viewsets
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView
from django.contrib.auth import get_user_model
from django.db import transaction

from .models import Address
from .serializers import (
    AddressSerializer,
    CustomTokenObtainPairSerializer,
    LoginResponseSerializer,
    RegisterResponseSerializer,
    RegisterSerializer,
    UserSerializer,

    ChangePasswordSerializer,
    DetailResponseSerializer,
    ForgotPasswordSerializer,
    LogoutSerializer,
    ResetPasswordSerializer,
    VerifyEmailSerializer,
)

from .tasks import (
    send_email_verification_task,
    send_password_changed_email_task,
    send_password_reset_email_task,
    send_welcome_email_task,
)

User = get_user_model()

@extend_schema(
    tags=["Accounts"],
    request=RegisterSerializer,
    responses={
        201: RegisterResponseSerializer,
        400: OpenApiResponse(description="Validation error."),
    },
    summary="Register a new customer or vendor user",
    description=(
        "Creates a new user account. Public registration can create CUSTOMER "
        "or VENDOR users only. ADMIN users cannot be created from this endpoint."
    ),
)
class RegisterView(generics.CreateAPIView):
    serializer_class = RegisterSerializer
    permission_classes = [permissions.AllowAny]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = serializer.save()
        refresh = RefreshToken.for_user(user)

        transaction.on_commit(
            lambda: send_email_verification_task.delay(str(user.id))
        )

        response_data = {
            "detail": "Account created successfully. Please verify your email.",
            "user": UserSerializer(user).data,
            "tokens": {
                "refresh": str(refresh),
                "access": str(refresh.access_token),
            },
        }

        return Response(response_data, status=status.HTTP_201_CREATED)


@extend_schema(
    tags=["Accounts"],
    request=CustomTokenObtainPairSerializer,
    responses={
        200: LoginResponseSerializer,
        401: OpenApiResponse(description="Invalid credentials."),
    },
    summary="Login with email and password",
    description="Returns JWT refresh/access tokens and authenticated user details.",
)
class LoginView(TokenObtainPairView):
    serializer_class = CustomTokenObtainPairSerializer
    permission_classes = [permissions.AllowAny]


@extend_schema(
    tags=["Accounts"],
    responses={200: UserSerializer},
    summary="Get authenticated user profile",
    description="Returns the currently authenticated user.",
)
class MeView(generics.RetrieveAPIView):
    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        return self.request.user


@extend_schema_view(
    list=extend_schema(
        tags=["Addresses"],
        summary="List my addresses",
        description="Returns only addresses owned by the authenticated user.",
    ),
    create=extend_schema(
        tags=["Addresses"],
        summary="Create my address",
        description="Creates an address for the authenticated user.",
    ),
    retrieve=extend_schema(
        tags=["Addresses"],
        summary="Retrieve my address",
        description="Returns a single address owned by the authenticated user.",
    ),
    update=extend_schema(
        tags=["Addresses"],
        summary="Update my address",
        description="Updates a single address owned by the authenticated user.",
    ),
    partial_update=extend_schema(
        tags=["Addresses"],
        summary="Partially update my address",
        description="Partially updates a single address owned by the authenticated user.",
    ),
    destroy=extend_schema(
        tags=["Addresses"],
        summary="Delete my address",
        description="Deletes a single address owned by the authenticated user.",
    ),
)
class AddressViewSet(viewsets.ModelViewSet):
    serializer_class = AddressSerializer
    permission_classes = [permissions.IsAuthenticated]
    http_method_names = ["get", "post", "put", "patch", "delete", "head", "options"]

    def get_queryset(self):
        return Address.objects.filter(user=self.request.user).select_related("user")

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

    def perform_update(self, serializer):
        serializer.save(user=self.request.user)


# New Views 

@extend_schema(
    tags=["Accounts"],
    request=LogoutSerializer,
    responses={200: DetailResponseSerializer},
    summary="Logout user",
    description="Blacklists the refresh token. Access token will expire naturally.",
)
class LogoutView(generics.GenericAPIView):
    serializer_class = LogoutSerializer
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()

        return Response(
            {"detail": "Logged out successfully."},
            status=status.HTTP_200_OK,
        )


@extend_schema(
    tags=["Accounts"],
    request=ChangePasswordSerializer,
    responses={200: DetailResponseSerializer},
    summary="Change authenticated user's password",
    description=(
        "Requires old password. Password update happens synchronously. "
        "Notification email is sent asynchronously through Celery."
    ),
)
class ChangePasswordView(generics.GenericAPIView):
    serializer_class = ChangePasswordSerializer
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = serializer.save()

        transaction.on_commit(
            lambda: send_password_changed_email_task.delay(str(user.id))
        )

        return Response(
            {"detail": "Password changed successfully."},
            status=status.HTTP_200_OK,
        )


@extend_schema(
    tags=["Accounts"],
    request=ForgotPasswordSerializer,
    responses={200: DetailResponseSerializer},
    summary="Request password reset email",
    description=(
        "Always returns the same response to prevent email enumeration. "
        "If the user exists, password reset email is queued through Celery."
    ),
)
class ForgotPasswordView(generics.GenericAPIView):
    serializer_class = ForgotPasswordSerializer
    permission_classes = [permissions.AllowAny]

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        email = serializer.validated_data["email"]

        user = User.objects.filter(
            email__iexact=email,
            is_active=True,
        ).first()

        if user:
            transaction.on_commit(
                lambda: send_password_reset_email_task.delay(str(user.id))
            )

        return Response(
            {
                "detail": (
                    "If an account exists with this email, "
                    "a password reset link has been sent."
                )
            },
            status=status.HTTP_200_OK,
        )


@extend_schema(
    tags=["Accounts"],
    request=ResetPasswordSerializer,
    responses={200: DetailResponseSerializer},
    summary="Reset password using token",
    description=(
        "Resets password using uid and token from password reset email. "
        "Password changed notification is queued through Celery."
    ),
)
class ResetPasswordView(generics.GenericAPIView):
    serializer_class = ResetPasswordSerializer
    permission_classes = [permissions.AllowAny]

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = serializer.save()

        transaction.on_commit(
            lambda: send_password_changed_email_task.delay(str(user.id))
        )

        return Response(
            {"detail": "Password reset successfully."},
            status=status.HTTP_200_OK,
        )


@extend_schema(
    tags=["Accounts"],
    request=VerifyEmailSerializer,
    responses={200: DetailResponseSerializer},
    summary="Verify email address",
    description=(
        "Verifies user email using uid and token. "
        "Welcome email is queued through Celery after successful verification."
    ),
)
class VerifyEmailView(generics.GenericAPIView):
    serializer_class = VerifyEmailSerializer
    permission_classes = [permissions.AllowAny]

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = serializer.save()

        transaction.on_commit(
            lambda: send_welcome_email_task.delay(str(user.id))
        )

        return Response(
            {"detail": "Email verified successfully."},
            status=status.HTTP_200_OK,
        )