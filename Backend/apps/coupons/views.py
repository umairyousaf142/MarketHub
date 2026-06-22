from drf_spectacular.utils import (
    OpenApiParameter,
    OpenApiResponse,
    extend_schema,
    extend_schema_view,
)
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.coupons.models import Coupon, CouponUsage
from apps.coupons.serializers import (
    CouponAdminWriteSerializer,
    CouponReadSerializer,
    CouponUsageCreateSerializer,
    CouponUsageReadSerializer,
    CouponValidateResponseSerializer,
    CouponValidateSerializer,
)
from core.permissions.roles import IsAdminRole, IsCustomerRole


def get_coupon_queryset():
    return (
        Coupon.objects.select_related(
            "vendor",
            "category",
        )
        .prefetch_related("usages")
        .order_by("code")
    )


def filter_coupon_queryset(queryset, request):
    code = request.query_params.get("code")
    type_value = request.query_params.get("type")
    scope = request.query_params.get("scope")
    is_active = request.query_params.get("is_active")
    vendor_id = request.query_params.get("vendor_id")
    category_id = request.query_params.get("category_id")

    if code:
        queryset = queryset.filter(code__icontains=code)

    if type_value:
        queryset = queryset.filter(type=type_value)

    if scope:
        queryset = queryset.filter(scope=scope)

    if is_active is not None:
        if str(is_active).lower() in ["true", "1", "yes"]:
            queryset = queryset.filter(is_active=True)

        if str(is_active).lower() in ["false", "0", "no"]:
            queryset = queryset.filter(is_active=False)

    if vendor_id:
        queryset = queryset.filter(vendor_id=vendor_id)

    if category_id:
        queryset = queryset.filter(category_id=category_id)

    return queryset


def get_coupon_usage_queryset():
    return (
        CouponUsage.objects.select_related(
            "coupon",
            "user",
            "order",
        )
        .order_by("-used_at")
    )


def filter_coupon_usage_queryset(queryset, request):
    coupon_id = request.query_params.get("coupon_id")
    code = request.query_params.get("code")
    user_id = request.query_params.get("user_id")
    order_id = request.query_params.get("order_id")

    if coupon_id:
        queryset = queryset.filter(coupon_id=coupon_id)

    if code:
        queryset = queryset.filter(coupon__code__icontains=code)

    if user_id:
        queryset = queryset.filter(user_id=user_id)

    if order_id:
        queryset = queryset.filter(order_id=order_id)

    return queryset


@extend_schema_view(
    list=extend_schema(
        tags=["Admin Coupons"],
        summary="List coupons",
        parameters=[
            OpenApiParameter("code", str, OpenApiParameter.QUERY),
            OpenApiParameter("type", str, OpenApiParameter.QUERY),
            OpenApiParameter("scope", str, OpenApiParameter.QUERY),
            OpenApiParameter("is_active", bool, OpenApiParameter.QUERY),
            OpenApiParameter("vendor_id", str, OpenApiParameter.QUERY),
            OpenApiParameter("category_id", str, OpenApiParameter.QUERY),
        ],
    ),
    retrieve=extend_schema(
        tags=["Admin Coupons"],
        summary="Retrieve coupon",
    ),
    create=extend_schema(
        tags=["Admin Coupons"],
        summary="Create coupon",
        request=CouponAdminWriteSerializer,
        responses={201: CouponReadSerializer},
    ),
    update=extend_schema(
        tags=["Admin Coupons"],
        summary="Update coupon",
        request=CouponAdminWriteSerializer,
        responses={200: CouponReadSerializer},
    ),
    partial_update=extend_schema(
        tags=["Admin Coupons"],
        summary="Partially update coupon",
        request=CouponAdminWriteSerializer,
        responses={200: CouponReadSerializer},
    ),
    destroy=extend_schema(
        tags=["Admin Coupons"],
        summary="Delete coupon",
    ),
)
class AdminCouponViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAdminRole]

    def get_queryset(self):
        return filter_coupon_queryset(get_coupon_queryset(), self.request)

    def get_serializer_class(self):
        if self.action in ["create", "update", "partial_update"]:
            return CouponAdminWriteSerializer

        return CouponReadSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        coupon = serializer.save()

        response_serializer = CouponReadSerializer(
            coupon,
            context=self.get_serializer_context(),
        )

        return Response(response_serializer.data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        instance = self.get_object()

        serializer = self.get_serializer(
            instance,
            data=request.data,
            partial=partial,
        )
        serializer.is_valid(raise_exception=True)

        coupon = serializer.save()

        response_serializer = CouponReadSerializer(
            coupon,
            context=self.get_serializer_context(),
        )

        return Response(response_serializer.data, status=status.HTTP_200_OK)


@extend_schema_view(
    list=extend_schema(
        tags=["Admin Coupon Usage"],
        summary="List coupon usage records",
        parameters=[
            OpenApiParameter("coupon_id", str, OpenApiParameter.QUERY),
            OpenApiParameter("code", str, OpenApiParameter.QUERY),
            OpenApiParameter("user_id", str, OpenApiParameter.QUERY),
            OpenApiParameter("order_id", str, OpenApiParameter.QUERY),
        ],
    ),
    retrieve=extend_schema(
        tags=["Admin Coupon Usage"],
        summary="Retrieve coupon usage record",
    ),
)
class AdminCouponUsageViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = CouponUsageReadSerializer
    permission_classes = [IsAdminRole]

    def get_queryset(self):
        return filter_coupon_usage_queryset(
            get_coupon_usage_queryset(),
            self.request,
        )


class CustomerCouponViewSet(viewsets.GenericViewSet):
    permission_classes = [IsCustomerRole]

    @extend_schema(
        tags=["Customer Coupons"],
        summary="Validate coupon for customer order",
        request=CouponValidateSerializer,
        responses={
            200: CouponValidateResponseSerializer,
            400: OpenApiResponse(description="Validation error"),
        },
    )
    @action(
        detail=False,
        methods=["post"],
        url_path="validate",
    )
    def validate_coupon(self, request):
        serializer = CouponValidateSerializer(
            data=request.data,
            context=self.get_serializer_context(),
        )
        serializer.is_valid(raise_exception=True)

        coupon = serializer.validated_data["coupon"]
        order = serializer.validated_data["order"]

        return Response(
            {
                "valid": True,
                "coupon_id": coupon.id,
                "code": coupon.code,
                "type": coupon.type,
                "scope": coupon.scope,
                "order_id": order.id,
                "order_total": order.total_amount,
                "discount_amount": serializer.validated_data["discount_amount"],
            },
            status=status.HTTP_200_OK,
        )

    @extend_schema(
        tags=["Customer Coupons"],
        summary="Record coupon usage for customer order",
        request=CouponUsageCreateSerializer,
        responses={
            201: CouponUsageReadSerializer,
            400: OpenApiResponse(description="Validation error"),
        },
    )
    @action(
        detail=False,
        methods=["post"],
        url_path="usage",
    )
    def usage(self, request):
        serializer = CouponUsageCreateSerializer(
            data=request.data,
            context=self.get_serializer_context(),
        )
        serializer.is_valid(raise_exception=True)

        usage = serializer.save()

        response_serializer = CouponUsageReadSerializer(
            usage,
            context=self.get_serializer_context(),
        )

        return Response(response_serializer.data, status=status.HTTP_201_CREATED)