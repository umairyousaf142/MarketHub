from django.core.exceptions import ValidationError as DjangoValidationError
from django.shortcuts import get_object_or_404

from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_view
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError as DRFValidationError
from rest_framework.response import Response

from core.permissions.base import IsAdmin, IsCustomer, IsVendor

from apps.cart.models import Cart
from apps.orders.models import Order, OrderItem, VendorOrder
from apps.vendors.models import Vendor
from django.db import transaction

from .serializers import (
    CheckoutSerializer,
    DetailResponseSerializer,
    OrderItemReadSerializer,
    OrderReadSerializer,
    VendorOrderReadSerializer,
)

from apps.orders.tasks import (
    check_low_stock_after_order_task,
    notify_admin_new_order_task,
    notify_vendors_new_order_task,
    notify_vendors_order_cancelled_task,
    send_order_cancelled_email_task,
    send_order_confirmation_email_task,
    send_order_paid_email_task,
    send_vendor_order_status_update_email_task,
)

def raise_drf_validation_error(exc):
    if hasattr(exc, "message_dict"):
        raise DRFValidationError(exc.message_dict)

    if hasattr(exc, "messages"):
        raise DRFValidationError({"detail": exc.messages})

    raise DRFValidationError({"detail": str(exc)})


def get_approved_vendor_for_user(user):
    vendor = Vendor.objects.filter(user=user).first()

    if not vendor:
        raise NotFound("Vendor profile not found. Complete vendor onboarding first.")

    if vendor.status != Vendor.Status.APPROVED:
        raise PermissionDenied(
            "Vendor profile must be approved before managing vendor orders."
        )

    return vendor


def get_active_cart_for_customer(user):
    cart = (
        Cart.objects.filter(
            customer=user,
            status=Cart.Status.ACTIVE,
        )
        .prefetch_related(
            "items",
            "items__product",
            "items__product__vendor",
            "items__variant",
        )
        .first()
    )

    if not cart:
        raise DRFValidationError({"cart": "No active cart found."})

    return cart


def get_order_queryset():
    return (
        Order.objects.select_related(
            "customer",
            "source_cart",
        )
        .prefetch_related(
            "items",
            "items__vendor",
            "items__product",
            "items__variant",
            "items__inventory_record",
            "vendor_orders",
            "vendor_orders__vendor",
        )
    )


@extend_schema_view(
    list=extend_schema(
        tags=["Customer Orders"],
        summary="List my orders",
        description="Returns orders owned by the authenticated customer.",
    ),
    retrieve=extend_schema(
        tags=["Customer Orders"],
        summary="Retrieve my order",
        description="Returns one order owned by the authenticated customer.",
    ),
)
class CustomerOrderViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = OrderReadSerializer
    permission_classes = [
        permissions.IsAuthenticated,
        IsCustomer,
    ]

    http_method_names = [
        "get",
        "post",
        "head",
        "options",
    ]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Order.objects.none()

        return get_order_queryset().filter(customer=self.request.user)

    @extend_schema(
        tags=["Customer Orders"],
        request=CheckoutSerializer,
        responses={
            201: OrderReadSerializer,
            400: OpenApiResponse(description="Invalid checkout request."),
        },
        summary="Create order from active cart",
        description=(
            "Creates an order from the authenticated customer's active cart. "
            "Cart items are snapshotted and inventory is reserved when applicable."
        ),
    )
    @action(
        detail=False,
        methods=["post"],
        url_path="checkout",
        url_name="checkout",
    )
    def checkout(self, request):
        cart = get_active_cart_for_customer(request.user)

        serializer = CheckoutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            order = Order.create_from_cart(
                cart,
                shipping_address=serializer.validated_data.get(
                    "shipping_address",
                    {},
                ),
                billing_address=serializer.validated_data.get(
                    "billing_address",
                    {},
                ),
                shipping_amount=serializer.validated_data.get(
                    "shipping_amount",
                    0,
                ),
                tax_amount=serializer.validated_data.get(
                    "tax_amount",
                    0,
                ),
                discount_amount=serializer.validated_data.get(
                    "discount_amount",
                    0,
                ),
                notes=serializer.validated_data.get("notes", ""),
            )
        except DjangoValidationError as exc:
            raise_drf_validation_error(exc)

        order = get_order_queryset().get(pk=order.pk)

        transaction.on_commit(
            lambda: send_order_confirmation_email_task.delay(str(order.id))
        )
        transaction.on_commit(
            lambda: notify_vendors_new_order_task.delay(str(order.id))
        )
        transaction.on_commit(
            lambda: notify_admin_new_order_task.delay(str(order.id))
        )
        transaction.on_commit(
            lambda: check_low_stock_after_order_task.delay(str(order.id))
        )

        response_serializer = OrderReadSerializer(
            order,
            context={"request": request},
        )

        return Response(response_serializer.data, status=status.HTTP_201_CREATED)

    @extend_schema(
        tags=["Customer Orders"],
        responses={
            200: OrderReadSerializer,
            400: OpenApiResponse(description="Order cannot be cancelled."),
        },
        summary="Cancel my order",
        description=(
            "Allows a customer to cancel a pending unpaid order. "
            "Reserved inventory is released."
        ),
    )
    @action(
        detail=True,
        methods=["post"],
        url_path="cancel",
        url_name="cancel",
    )
    def cancel(self, request, pk=None):
        order = self.get_object()

        if order.status != Order.Status.PENDING:
            raise DRFValidationError(
                {"status": "Only pending orders can be cancelled by customer."}
            )

        if order.payment_status != Order.PaymentStatus.PENDING:
            raise DRFValidationError(
                {"payment_status": "Paid orders cannot be cancelled by customer."}
            )

        try:
            order.cancel()
        except DjangoValidationError as exc:
            raise_drf_validation_error(exc)

        order = get_order_queryset().get(pk=order.pk)

        transaction.on_commit(
            lambda: send_order_cancelled_email_task.delay(str(order.id))
        )
        transaction.on_commit(
            lambda: notify_vendors_order_cancelled_task.delay(str(order.id))
        )

        serializer = self.get_serializer(order)

        return Response(serializer.data, status=status.HTTP_200_OK)


@extend_schema_view(
    list=extend_schema(
        tags=["Vendor Orders"],
        summary="List my vendor orders",
        description="Returns vendor-level sub-orders for the authenticated approved vendor.",
    ),
    retrieve=extend_schema(
        tags=["Vendor Orders"],
        summary="Retrieve my vendor order",
        description="Returns one vendor-level sub-order for the authenticated approved vendor.",
    ),
)
class VendorOrderViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = VendorOrderReadSerializer
    permission_classes = [
        permissions.IsAuthenticated,
        IsVendor,
    ]

    http_method_names = [
        "get",
        "post",
        "head",
        "options",
    ]

    def get_vendor(self):
        return get_approved_vendor_for_user(self.request.user)

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return VendorOrder.objects.none()

        vendor = self.get_vendor()

        return (
            VendorOrder.objects.select_related(
                "order",
                "order__customer",
                "vendor",
            )
            .prefetch_related(
                "order__items",
                "order__items__vendor",
                "order__items__product",
                "order__items__variant",
                "order__items__inventory_record",
            )
            .filter(vendor=vendor)
        )

    def update_vendor_order_status(self, vendor_order, next_status):
        current_status = vendor_order.status

        valid_transitions = {
            VendorOrder.Status.CONFIRMED: [VendorOrder.Status.PROCESSING],
            VendorOrder.Status.PROCESSING: [VendorOrder.Status.SHIPPED],
            VendorOrder.Status.SHIPPED: [VendorOrder.Status.DELIVERED],
        }

        allowed_next_statuses = valid_transitions.get(current_status, [])

        if next_status not in allowed_next_statuses:
            raise DRFValidationError(
                {
                    "status": (
                        f"Vendor order cannot move from {current_status} "
                        f"to {next_status}."
                    )
                }
            )

        vendor_order.status = next_status
        vendor_order.save(update_fields=["status", "updated_at"])

        self.sync_parent_order_status(vendor_order.order)

        vendor_order.refresh_from_db()

        return vendor_order

    def sync_parent_order_status(self, order):
        vendor_statuses = list(
            order.vendor_orders.values_list("status", flat=True)
        )

        if not vendor_statuses:
            return

        if all(status == VendorOrder.Status.DELIVERED for status in vendor_statuses):
            order.status = Order.Status.DELIVERED
            order.save(update_fields=["status", "updated_at"])
            return

        if all(
            status in [VendorOrder.Status.SHIPPED, VendorOrder.Status.DELIVERED]
            for status in vendor_statuses
        ):
            order.status = Order.Status.SHIPPED
            order.save(update_fields=["status", "updated_at"])
            return

        if any(
            status
            in [
                VendorOrder.Status.PROCESSING,
                VendorOrder.Status.SHIPPED,
                VendorOrder.Status.DELIVERED,
            ]
            for status in vendor_statuses
        ):
            order.status = Order.Status.PROCESSING
            order.save(update_fields=["status", "updated_at"])

    @extend_schema(
        tags=["Vendor Orders"],
        responses={
            200: VendorOrderReadSerializer,
            400: OpenApiResponse(description="Invalid status transition."),
        },
        summary="Mark vendor order processing",
        description="Moves a confirmed vendor order to processing.",
    )
    @action(
        detail=True,
        methods=["post"],
        url_path="mark-processing",
        url_name="mark-processing",
    )
    def mark_processing(self, request, pk=None):
        vendor_order = self.get_object()

        vendor_order = self.update_vendor_order_status(
            vendor_order,
            VendorOrder.Status.PROCESSING,
        )

        transaction.on_commit(
            lambda: send_vendor_order_status_update_email_task.delay(str(vendor_order.id))
        )

        serializer = self.get_serializer(vendor_order)

        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(
        tags=["Vendor Orders"],
        responses={
            200: VendorOrderReadSerializer,
            400: OpenApiResponse(description="Invalid status transition."),
        },
        summary="Mark vendor order shipped",
        description="Moves a processing vendor order to shipped.",
    )
    @action(
        detail=True,
        methods=["post"],
        url_path="mark-shipped",
        url_name="mark-shipped",
    )
    def mark_shipped(self, request, pk=None):
        vendor_order = self.get_object()

        vendor_order = self.update_vendor_order_status(
            vendor_order,
            VendorOrder.Status.SHIPPED,
        )

        transaction.on_commit(
            lambda: send_vendor_order_status_update_email_task.delay(str(vendor_order.id))
        )

        serializer = self.get_serializer(vendor_order)

        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(
        tags=["Vendor Orders"],
        responses={
            200: VendorOrderReadSerializer,
            400: OpenApiResponse(description="Invalid status transition."),
        },
        summary="Mark vendor order delivered",
        description="Moves a shipped vendor order to delivered.",
    )
    @action(
        detail=True,
        methods=["post"],
        url_path="mark-delivered",
        url_name="mark-delivered",
    )
    def mark_delivered(self, request, pk=None):
        vendor_order = self.get_object()

        vendor_order = self.update_vendor_order_status(
            vendor_order,
            VendorOrder.Status.DELIVERED,
        )

        transaction.on_commit(
            lambda: send_vendor_order_status_update_email_task.delay(str(vendor_order.id))
        )

        serializer = self.get_serializer(vendor_order)

        return Response(serializer.data, status=status.HTTP_200_OK)


@extend_schema_view(
    list=extend_schema(
        tags=["Admin Orders"],
        summary="List orders",
        description="Admin-only endpoint to list all orders.",
    ),
    retrieve=extend_schema(
        tags=["Admin Orders"],
        summary="Retrieve order",
        description="Admin-only endpoint to retrieve one order.",
    ),
)
class AdminOrderViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = OrderReadSerializer
    permission_classes = [
        permissions.IsAuthenticated,
        IsAdmin,
    ]

    http_method_names = [
        "get",
        "post",
        "head",
        "options",
    ]

    def get_queryset(self):
        queryset = get_order_queryset().all()

        status_param = self.request.query_params.get("status")
        payment_status = self.request.query_params.get("payment_status")
        inventory_status = self.request.query_params.get("inventory_status")
        customer = self.request.query_params.get("customer")

        if status_param:
            queryset = queryset.filter(status=status_param)

        if payment_status:
            queryset = queryset.filter(payment_status=payment_status)

        if inventory_status:
            queryset = queryset.filter(inventory_status=inventory_status)

        if customer:
            queryset = queryset.filter(customer_id=customer)

        return queryset

    @extend_schema(
        tags=["Admin Orders"],
        responses={
            200: OrderReadSerializer,
            400: OpenApiResponse(description="Order cannot be marked as paid."),
        },
        summary="Mark order paid",
        description="Marks an order as paid, confirms the order, and commits reserved inventory.",
    )
    @action(
        detail=True,
        methods=["post"],
        url_path="mark-paid",
        url_name="mark-paid",
    )
    def mark_paid(self, request, pk=None):
        order = self.get_object()

        if order.status == Order.Status.CANCELLED:
            raise DRFValidationError(
                {"status": "Cancelled orders cannot be marked as paid."}
            )

        if order.payment_status == Order.PaymentStatus.PAID:
            raise DRFValidationError(
                {"payment_status": "Order is already paid."}
            )

        try:
            order.mark_paid()
        except DjangoValidationError as exc:
            raise_drf_validation_error(exc)

        order = get_order_queryset().get(pk=order.pk)

        transaction.on_commit(
            lambda: send_order_paid_email_task.delay(str(order.id))
        )
        transaction.on_commit(
            lambda: check_low_stock_after_order_task.delay(str(order.id))
        )

        serializer = self.get_serializer(order)

        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(
        tags=["Admin Orders"],
        responses={
            200: OrderReadSerializer,
            400: OpenApiResponse(description="Order cannot be cancelled."),
        },
        summary="Cancel order",
        description="Admin-only order cancellation. Reserved inventory is released when applicable.",
    )
    @action(
        detail=True,
        methods=["post"],
        url_path="cancel",
        url_name="cancel",
    )
    def cancel(self, request, pk=None):
        order = self.get_object()

        if order.status == Order.Status.CANCELLED:
            raise DRFValidationError(
                {"status": "Order is already cancelled."}
            )

        if order.status == Order.Status.DELIVERED:
            raise DRFValidationError(
                {"status": "Delivered orders cannot be cancelled."}
            )

        try:
            order.cancel()
        except DjangoValidationError as exc:
            raise_drf_validation_error(exc)

        order = get_order_queryset().get(pk=order.pk)

        transaction.on_commit(
            lambda: send_order_cancelled_email_task.delay(str(order.id))
        )
        transaction.on_commit(
            lambda: notify_vendors_order_cancelled_task.delay(str(order.id))
        )

        serializer = self.get_serializer(order)

        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(
        tags=["Admin Orders"],
        responses={
            200: OrderReadSerializer,
            400: OpenApiResponse(description="Inventory cannot be committed."),
        },
        summary="Commit reserved inventory",
        description="Admin-only operation to commit reserved stock for an order.",
    )
    @action(
        detail=True,
        methods=["post"],
        url_path="commit-inventory",
        url_name="commit-inventory",
    )
    def commit_inventory(self, request, pk=None):
        order = self.get_object()

        try:
            order.commit_inventory()
        except DjangoValidationError as exc:
            raise_drf_validation_error(exc)

        order = get_order_queryset().get(pk=order.pk)

        transaction.on_commit(
            lambda: check_low_stock_after_order_task.delay(str(order.id))
        )

        serializer = self.get_serializer(order)

        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(
        tags=["Admin Orders"],
        responses={
            200: OrderReadSerializer,
            400: OpenApiResponse(description="Inventory cannot be released."),
        },
        summary="Release reserved inventory",
        description="Admin-only operation to release reserved stock for an order.",
    )
    @action(
        detail=True,
        methods=["post"],
        url_path="release-inventory",
        url_name="release-inventory",
    )
    def release_inventory(self, request, pk=None):
        order = self.get_object()

        try:
            order.release_inventory()
        except DjangoValidationError as exc:
            raise_drf_validation_error(exc)

        order = get_order_queryset().get(pk=order.pk)

        serializer = self.get_serializer(order)

        return Response(serializer.data, status=status.HTTP_200_OK)


@extend_schema_view(
    list=extend_schema(
        tags=["Admin Orders"],
        summary="List vendor orders",
        description="Admin-only endpoint to list all vendor-level sub-orders.",
    ),
    retrieve=extend_schema(
        tags=["Admin Orders"],
        summary="Retrieve vendor order",
        description="Admin-only endpoint to retrieve one vendor-level sub-order.",
    ),
)
class AdminVendorOrderViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = VendorOrderReadSerializer
    permission_classes = [
        permissions.IsAuthenticated,
        IsAdmin,
    ]

    def get_queryset(self):
        queryset = (
            VendorOrder.objects.select_related(
                "order",
                "order__customer",
                "vendor",
            )
            .prefetch_related(
                "order__items",
                "order__items__vendor",
                "order__items__product",
                "order__items__variant",
                "order__items__inventory_record",
            )
            .all()
        )

        vendor = self.request.query_params.get("vendor")
        status_param = self.request.query_params.get("status")
        order = self.request.query_params.get("order")

        if vendor:
            queryset = queryset.filter(vendor_id=vendor)

        if status_param:
            queryset = queryset.filter(status=status_param)

        if order:
            queryset = queryset.filter(order_id=order)

        return queryset


@extend_schema_view(
    list=extend_schema(
        tags=["Admin Orders"],
        summary="List order items",
        description="Admin-only endpoint to list all order items.",
    ),
    retrieve=extend_schema(
        tags=["Admin Orders"],
        summary="Retrieve order item",
        description="Admin-only endpoint to retrieve one order item.",
    ),
)
class AdminOrderItemViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = OrderItemReadSerializer
    permission_classes = [
        permissions.IsAuthenticated,
        IsAdmin,
    ]

    def get_queryset(self):
        queryset = (
            OrderItem.objects.select_related(
                "order",
                "vendor",
                "product",
                "variant",
                "inventory_record",
            )
            .all()
        )

        order = self.request.query_params.get("order")
        vendor = self.request.query_params.get("vendor")
        product = self.request.query_params.get("product")
        customer = self.request.query_params.get("customer")

        if order:
            queryset = queryset.filter(order_id=order)

        if vendor:
            queryset = queryset.filter(vendor_id=vendor)

        if product:
            queryset = queryset.filter(product_id=product)

        if customer:
            queryset = queryset.filter(order__customer_id=customer)

        return queryset