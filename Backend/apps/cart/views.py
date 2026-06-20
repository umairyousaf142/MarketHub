from django.core.exceptions import ValidationError as DjangoValidationError
from django.shortcuts import get_object_or_404

from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_view
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError as DRFValidationError
from rest_framework.response import Response

from core.permissions.base import IsAdmin, IsCustomer

from apps.cart.models import Cart, CartItem

from .serializers import (
    CartClearResponseSerializer,
    CartItemAddSerializer,
    CartItemQuantityUpdateSerializer,
    CartItemReadSerializer,
    CartReadSerializer,
)


def raise_drf_validation_error(exc):
    if hasattr(exc, "message_dict"):
        raise DRFValidationError(exc.message_dict)

    if hasattr(exc, "messages"):
        raise DRFValidationError({"detail": exc.messages})

    raise DRFValidationError({"detail": str(exc)})


def get_or_create_active_cart_for_customer(user):
    cart, _ = Cart.objects.get_or_create(
        customer=user,
        status=Cart.Status.ACTIVE,
    )

    return cart


@extend_schema_view(
    list=extend_schema(
        tags=["Customer Cart"],
        responses={200: CartReadSerializer},
        summary="Get my active cart",
        description="Returns the authenticated customer's active cart. Creates one if it does not exist.",
    ),
)
class CustomerCartViewSet(viewsets.ViewSet):
    serializer_class = CartReadSerializer
    permission_classes = [
        permissions.IsAuthenticated,
        IsCustomer,
    ]

    def get_cart(self):
        return get_or_create_active_cart_for_customer(self.request.user)

    def get_cart_with_related_data(self):
        cart = self.get_cart()

        return (
            Cart.objects.prefetch_related(
                "items",
                "items__product",
                "items__product__vendor",
                "items__variant",
            )
            .select_related("customer")
            .get(pk=cart.pk)
        )

    def list(self, request):
        cart = self.get_cart_with_related_data()

        serializer = CartReadSerializer(
            cart,
            context={"request": request},
        )

        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(
        tags=["Customer Cart"],
        request=CartItemAddSerializer,
        responses={201: CartItemReadSerializer},
        summary="Add item to cart",
        description="Adds product or variant to the active customer cart. Existing matching item quantity is increased.",
    )
    @action(
        detail=False,
        methods=["post"],
        url_path="items",
        url_name="items",
    )
    def add_item(self, request):
        cart = self.get_cart()

        serializer = CartItemAddSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        product = serializer.validated_data["product"]
        variant = serializer.validated_data.get("variant")
        quantity = serializer.validated_data["quantity"]

        try:
            item = cart.add_item(
                product=product,
                variant=variant,
                quantity=quantity,
            )
        except DjangoValidationError as exc:
            raise_drf_validation_error(exc)

        item.refresh_from_db()

        response_serializer = CartItemReadSerializer(
            item,
            context={"request": request},
        )

        return Response(response_serializer.data, status=status.HTTP_201_CREATED)

    @extend_schema(
        tags=["Customer Cart"],
        request=CartItemQuantityUpdateSerializer,
        responses={
            200: CartItemReadSerializer,
            204: OpenApiResponse(description="Cart item removed."),
        },
        summary="Update or remove cart item",
        description="PATCH updates cart item quantity. DELETE removes cart item from active cart.",
    )
    @action(
        detail=False,
        methods=["patch", "delete"],
        url_path=r"items/(?P<item_id>[^/.]+)",
        url_name="item-detail",
    )
    def item_detail(self, request, item_id=None):
        cart = self.get_cart()

        item = get_object_or_404(
            CartItem.objects.select_related(
                "cart",
                "product",
                "product__vendor",
                "product__category",
                "product__brand",
                "variant",
            ),
            id=item_id,
            cart=cart,
        )

        if request.method == "DELETE":
            item.delete()
            return Response(status=status.HTTP_204_NO_CONTENT)

        serializer = CartItemQuantityUpdateSerializer(
            data=request.data,
            context={"item": item},
        )
        serializer.is_valid(raise_exception=True)

        item.quantity = serializer.validated_data["quantity"]

        try:
            item.save(update_fields=["quantity", "updated_at"])
        except DjangoValidationError as exc:
            raise_drf_validation_error(exc)

        item.refresh_from_db()

        response_serializer = CartItemReadSerializer(
            item,
            context={"request": request},
        )

        return Response(response_serializer.data, status=status.HTTP_200_OK)

    @extend_schema(
        tags=["Customer Cart"],
        responses={200: CartClearResponseSerializer},
        summary="Clear cart",
        description="Removes all items from the authenticated customer's active cart.",
    )
    @action(
        detail=False,
        methods=["post"],
        url_path="clear",
        url_name="clear",
    )
    def clear(self, request):
        cart = self.get_cart()

        try:
            cart.clear()
        except DjangoValidationError as exc:
            raise_drf_validation_error(exc)

        return Response(
            {"detail": "Cart cleared successfully."},
            status=status.HTTP_200_OK,
        )


@extend_schema_view(
    list=extend_schema(
        tags=["Admin Cart"],
        summary="List carts",
        description="Admin-only endpoint to list all carts.",
    ),
    retrieve=extend_schema(
        tags=["Admin Cart"],
        summary="Retrieve cart",
        description="Admin-only endpoint to retrieve one cart.",
    ),
)
class AdminCartViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = CartReadSerializer
    permission_classes = [
        permissions.IsAuthenticated,
        IsAdmin,
    ]

    queryset = (
        Cart.objects.select_related("customer")
        .prefetch_related(
            "items",
            "items__product",
            "items__product__vendor",
            "items__variant",
        )
        .all()
    )

    def get_queryset(self):
        queryset = super().get_queryset()

        status_param = self.request.query_params.get("status")
        customer = self.request.query_params.get("customer")

        if status_param:
            queryset = queryset.filter(status=status_param)

        if customer:
            queryset = queryset.filter(customer_id=customer)

        return queryset


@extend_schema_view(
    list=extend_schema(
        tags=["Admin Cart"],
        summary="List cart items",
        description="Admin-only endpoint to list all cart items.",
    ),
    retrieve=extend_schema(
        tags=["Admin Cart"],
        summary="Retrieve cart item",
        description="Admin-only endpoint to retrieve one cart item.",
    ),
)
class AdminCartItemViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = CartItemReadSerializer
    permission_classes = [
        permissions.IsAuthenticated,
        IsAdmin,
    ]

    queryset = (
        CartItem.objects.select_related(
            "cart",
            "cart__customer",
            "product",
            "product__vendor",
            "variant",
        )
        .all()
    )

    def get_queryset(self):
        queryset = super().get_queryset()

        cart = self.request.query_params.get("cart")
        customer = self.request.query_params.get("customer")
        product = self.request.query_params.get("product")

        if cart:
            queryset = queryset.filter(cart_id=cart)

        if customer:
            queryset = queryset.filter(cart__customer_id=customer)

        if product:
            queryset = queryset.filter(product_id=product)

        return queryset