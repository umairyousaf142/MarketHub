from drf_spectacular.utils import (
    OpenApiParameter,
    OpenApiResponse,
    extend_schema,
    extend_schema_view,
)
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from apps.catalog.models import ProductVariant
from apps.reviews.models import Review
from apps.reviews.serializers import (
    PublicReviewReadSerializer,
    ReviewCreateSerializer,
    ReviewRatingSummarySerializer,
    ReviewReadSerializer,
    ReviewVisibilityUpdateSerializer,
)
from core.permissions.roles import IsAdminRole, IsCustomerRole


def get_review_queryset():
    return (
        Review.objects.select_related(
            "order_item",
            "order_item__order",
            "reviewer",
            "variant",
        )
        .order_by("-created_at")
    )


def filter_review_queryset(queryset, request):
    variant_id = request.query_params.get("variant_id")
    order_item_id = request.query_params.get("order_item_id")
    reviewer_id = request.query_params.get("reviewer_id")
    rating = request.query_params.get("rating")
    is_visible = request.query_params.get("is_visible")

    if variant_id:
        queryset = queryset.filter(variant_id=variant_id)

    if order_item_id:
        queryset = queryset.filter(order_item_id=order_item_id)

    if reviewer_id:
        queryset = queryset.filter(reviewer_id=reviewer_id)

    if rating:
        queryset = queryset.filter(rating=rating)

    if is_visible is not None:
        if str(is_visible).lower() in ["true", "1", "yes"]:
            queryset = queryset.filter(is_visible=True)

        if str(is_visible).lower() in ["false", "0", "no"]:
            queryset = queryset.filter(is_visible=False)

    return queryset


@extend_schema_view(
    list=extend_schema(
        tags=["Customer Reviews"],
        summary="List my reviews",
        parameters=[
            OpenApiParameter("variant_id", str, OpenApiParameter.QUERY),
            OpenApiParameter("order_item_id", str, OpenApiParameter.QUERY),
            OpenApiParameter("rating", int, OpenApiParameter.QUERY),
        ],
    ),
    retrieve=extend_schema(
        tags=["Customer Reviews"],
        summary="Retrieve my review",
    ),
    create=extend_schema(
        tags=["Customer Reviews"],
        summary="Create review for completed order item",
        request=ReviewCreateSerializer,
        responses={
            201: ReviewReadSerializer,
            400: OpenApiResponse(description="Validation error"),
        },
    ),
)
class CustomerReviewViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    permission_classes = [IsCustomerRole]

    def get_queryset(self):
        queryset = get_review_queryset().filter(reviewer=self.request.user)

        return filter_review_queryset(queryset, self.request)

    def get_serializer_class(self):
        if self.action == "create":
            return ReviewCreateSerializer

        return ReviewReadSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(
            data=request.data,
            context=self.get_serializer_context(),
        )
        serializer.is_valid(raise_exception=True)

        review = serializer.save()

        response_serializer = ReviewReadSerializer(
            review,
            context=self.get_serializer_context(),
        )

        return Response(response_serializer.data, status=status.HTTP_201_CREATED)


@extend_schema_view(
    list=extend_schema(
        tags=["Public Reviews"],
        summary="List visible reviews",
        parameters=[
            OpenApiParameter("variant_id", str, OpenApiParameter.QUERY),
            OpenApiParameter("rating", int, OpenApiParameter.QUERY),
        ],
    ),
    retrieve=extend_schema(
        tags=["Public Reviews"],
        summary="Retrieve visible review",
    ),
)
class PublicReviewViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = PublicReviewReadSerializer
    permission_classes = [AllowAny]

    def get_queryset(self):
        queryset = get_review_queryset().filter(is_visible=True)

        return filter_review_queryset(queryset, self.request)

    @extend_schema(
        tags=["Public Reviews"],
        summary="Get rating summary for variant",
        parameters=[
            OpenApiParameter(
                "variant_id",
                str,
                OpenApiParameter.QUERY,
                required=True,
            ),
        ],
        responses={
            200: ReviewRatingSummarySerializer,
            400: OpenApiResponse(description="variant_id is required"),
            404: OpenApiResponse(description="Variant not found"),
        },
    )
    @action(
        detail=False,
        methods=["get"],
        url_path="summary",
    )
    def summary(self, request):
        variant_id = request.query_params.get("variant_id")

        if not variant_id:
            return Response(
                {"variant_id": "variant_id query parameter is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            variant = ProductVariant.objects.get(id=variant_id)
        except ProductVariant.DoesNotExist:
            return Response(
                {"variant_id": "Product variant does not exist."},
                status=status.HTTP_404_NOT_FOUND,
            )

        summary = Review.get_rating_summary_for_variant(variant)

        return Response(
            {
                "variant_id": variant.id,
                "review_count": summary["review_count"],
                "average_rating": summary["average_rating"],
            },
            status=status.HTTP_200_OK,
        )


@extend_schema_view(
    list=extend_schema(
        tags=["Admin Reviews"],
        summary="List all reviews",
        parameters=[
            OpenApiParameter("variant_id", str, OpenApiParameter.QUERY),
            OpenApiParameter("order_item_id", str, OpenApiParameter.QUERY),
            OpenApiParameter("reviewer_id", str, OpenApiParameter.QUERY),
            OpenApiParameter("rating", int, OpenApiParameter.QUERY),
            OpenApiParameter("is_visible", bool, OpenApiParameter.QUERY),
        ],
    ),
    retrieve=extend_schema(
        tags=["Admin Reviews"],
        summary="Retrieve review",
    ),
    partial_update=extend_schema(
        tags=["Admin Reviews"],
        summary="Update review visibility",
        request=ReviewVisibilityUpdateSerializer,
        responses={
            200: ReviewReadSerializer,
            400: OpenApiResponse(description="Validation error"),
        },
    ),
)
class AdminReviewViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    permission_classes = [IsAdminRole]
    http_method_names = [
        "get",
        "patch",
        "post",
        "head",
        "options",
    ]

    def get_queryset(self):
        queryset = get_review_queryset()

        return filter_review_queryset(queryset, self.request)

    def get_serializer_class(self):
        if self.action == "partial_update":
            return ReviewVisibilityUpdateSerializer

        return ReviewReadSerializer

    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()

        serializer = self.get_serializer(
            instance,
            data=request.data,
            partial=True,
        )
        serializer.is_valid(raise_exception=True)

        review = serializer.save()

        response_serializer = ReviewReadSerializer(
            review,
            context=self.get_serializer_context(),
        )

        return Response(response_serializer.data, status=status.HTTP_200_OK)

    @extend_schema(
        tags=["Admin Reviews"],
        summary="Hide review",
        responses={200: ReviewReadSerializer},
    )
    @action(
        detail=True,
        methods=["post"],
        url_path="hide",
    )
    def hide(self, request, pk=None):
        review = self.get_object()

        Review.objects.filter(pk=review.pk).update(is_visible=False)
        review.refresh_from_db()

        serializer = ReviewReadSerializer(
            review,
            context=self.get_serializer_context(),
        )

        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(
        tags=["Admin Reviews"],
        summary="Show review",
        responses={200: ReviewReadSerializer},
    )
    @action(
        detail=True,
        methods=["post"],
        url_path="show",
    )
    def show(self, request, pk=None):
        review = self.get_object()

        Review.objects.filter(pk=review.pk).update(is_visible=True)
        review.refresh_from_db()

        serializer = ReviewReadSerializer(
            review,
            context=self.get_serializer_context(),
        )

        return Response(serializer.data, status=status.HTTP_200_OK)