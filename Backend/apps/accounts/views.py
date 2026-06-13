from drf_spectacular.utils import (
    OpenApiResponse,
    extend_schema,
    extend_schema_view,
)
from rest_framework import generics, permissions, status, viewsets
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView

from .models import Address
from .serializers import (
    AddressSerializer,
    CustomTokenObtainPairSerializer,
    LoginResponseSerializer,
    RegisterResponseSerializer,
    RegisterSerializer,
    UserSerializer,
)


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

        response_data = {
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