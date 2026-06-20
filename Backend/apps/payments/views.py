from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from drf_spectacular.utils import (
    OpenApiParameter,
    OpenApiResponse,
    extend_schema,
    extend_schema_view,
)
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.orders.tasks import (
    check_low_stock_after_order_task,
    send_order_paid_email_task,
)
from apps.payments.models import Payment, PaymentWebhookEvent
from apps.payments.permissions import IsPaymentAdmin, IsPaymentCustomer
from apps.payments.providers import PaymentProviderError, get_payment_provider
from apps.payments.serializers import (
    CustomerManualPaymentCreateSerializer,
    PaymentCancelSerializer,
    PaymentCaptureSerializer,
    PaymentFailSerializer,
    PaymentReadSerializer,
    PaymentRefundCreateSerializer,
    PaymentWebhookEventReadSerializer,
)


def get_payment_queryset():
    return (
        Payment.objects.select_related(
            "order",
            "order__customer",
            "created_by",
        )
        .prefetch_related(
            "transactions",
            "refunds",
        )
        .order_by("-created_at")
    )


def filter_payment_queryset(queryset, request):
    status_value = request.query_params.get("status")
    provider = request.query_params.get("provider")
    order_id = request.query_params.get("order_id")
    order_number = request.query_params.get("order_number")
    customer_email = request.query_params.get("customer_email")

    if status_value:
        queryset = queryset.filter(status=status_value)

    if provider:
        queryset = queryset.filter(provider=provider)

    if order_id:
        queryset = queryset.filter(order_id=order_id)

    if order_number:
        queryset = queryset.filter(order__order_number__icontains=order_number)

    if customer_email:
        queryset = queryset.filter(order__customer__email__icontains=customer_email)

    return queryset


def enqueue_order_paid_tasks_once(old_payment_status, payment):
    payment.refresh_from_db()
    order = payment.order
    order.refresh_from_db()

    if (
        old_payment_status != Payment.Status.CAPTURED
        and payment.status == Payment.Status.CAPTURED
    ):
        transaction.on_commit(
            lambda: send_order_paid_email_task.delay(str(order.id))
        )
        transaction.on_commit(
            lambda: check_low_stock_after_order_task.delay(str(order.id))
        )


@extend_schema_view(
    list=extend_schema(
        tags=["Customer Payments"],
        summary="List my payments",
        parameters=[
            OpenApiParameter("status", str, OpenApiParameter.QUERY),
            OpenApiParameter("provider", str, OpenApiParameter.QUERY),
            OpenApiParameter("order_id", str, OpenApiParameter.QUERY),
            OpenApiParameter("order_number", str, OpenApiParameter.QUERY),
        ],
    ),
    retrieve=extend_schema(
        tags=["Customer Payments"],
        summary="Retrieve my payment",
    ),
)
class CustomerPaymentViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = PaymentReadSerializer
    permission_classes = [IsPaymentCustomer]

    def get_queryset(self):
        queryset = get_payment_queryset().filter(order__customer=self.request.user)

        return filter_payment_queryset(queryset, self.request)

    @extend_schema(
        tags=["Customer Payments"],
        summary="Create manual payment for my order",
        request=CustomerManualPaymentCreateSerializer,
        responses={
            201: PaymentReadSerializer,
            400: OpenApiResponse(description="Validation error"),
        },
    )
    @action(
        detail=False,
        methods=["post"],
        url_path="manual",
    )
    def manual(self, request):
        serializer = CustomerManualPaymentCreateSerializer(
            data=request.data,
            context=self.get_serializer_context(),
        )
        serializer.is_valid(raise_exception=True)

        payment = serializer.save()

        response_serializer = PaymentReadSerializer(
            payment,
            context=self.get_serializer_context(),
        )

        return Response(response_serializer.data, status=status.HTTP_201_CREATED)


@extend_schema_view(
    list=extend_schema(
        tags=["Admin Payments"],
        summary="List all payments",
        parameters=[
            OpenApiParameter("status", str, OpenApiParameter.QUERY),
            OpenApiParameter("provider", str, OpenApiParameter.QUERY),
            OpenApiParameter("order_id", str, OpenApiParameter.QUERY),
            OpenApiParameter("order_number", str, OpenApiParameter.QUERY),
            OpenApiParameter("customer_email", str, OpenApiParameter.QUERY),
        ],
    ),
    retrieve=extend_schema(
        tags=["Admin Payments"],
        summary="Retrieve payment",
    ),
)
class AdminPaymentViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = PaymentReadSerializer
    permission_classes = [IsPaymentAdmin]

    def get_queryset(self):
        queryset = get_payment_queryset()

        return filter_payment_queryset(queryset, self.request)

    @extend_schema(
        tags=["Admin Payments"],
        summary="Capture payment",
        request=PaymentCaptureSerializer,
        responses={
            200: PaymentReadSerializer,
            400: OpenApiResponse(description="Validation error"),
        },
    )
    @action(
        detail=True,
        methods=["post"],
        url_path="capture",
    )
    def capture(self, request, pk=None):
        payment = self.get_object()
        old_payment_status = payment.status

        serializer = PaymentCaptureSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            provider = get_payment_provider(payment.provider)

            payment = provider.capture_payment(
                payment,
                provider_reference=serializer.validated_data.get(
                    "provider_reference",
                    "",
                ),
                metadata=serializer.validated_data.get("metadata") or {},
            )

            enqueue_order_paid_tasks_once(old_payment_status, payment)

        except DjangoValidationError as exc:
            raise ValidationError(exc.message_dict) from exc
        except PaymentProviderError as exc:
            raise ValidationError({"provider": str(exc)}) from exc

        response_serializer = self.get_serializer(payment)

        return Response(response_serializer.data, status=status.HTTP_200_OK)

    @extend_schema(
        tags=["Admin Payments"],
        summary="Mark payment as failed",
        request=PaymentFailSerializer,
        responses={
            200: PaymentReadSerializer,
            400: OpenApiResponse(description="Validation error"),
        },
    )
    @action(
        detail=True,
        methods=["post"],
        url_path="fail",
    )
    def fail(self, request, pk=None):
        payment = self.get_object()

        serializer = PaymentFailSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            payment = payment.mark_failed(
                reason=serializer.validated_data["reason"],
                provider_reference=serializer.validated_data.get(
                    "provider_reference",
                    "",
                ),
                metadata=serializer.validated_data.get("metadata") or {},
            )
        except DjangoValidationError as exc:
            raise ValidationError(exc.message_dict) from exc

        response_serializer = self.get_serializer(payment)

        return Response(response_serializer.data, status=status.HTTP_200_OK)

    @extend_schema(
        tags=["Admin Payments"],
        summary="Cancel payment",
        request=PaymentCancelSerializer,
        responses={
            200: PaymentReadSerializer,
            400: OpenApiResponse(description="Validation error"),
        },
    )
    @action(
        detail=True,
        methods=["post"],
        url_path="cancel",
    )
    def cancel(self, request, pk=None):
        payment = self.get_object()

        serializer = PaymentCancelSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            payment = payment.cancel(
                reason=serializer.validated_data.get("reason") or "",
                metadata=serializer.validated_data.get("metadata") or {},
            )
        except DjangoValidationError as exc:
            raise ValidationError(exc.message_dict) from exc

        response_serializer = self.get_serializer(payment)

        return Response(response_serializer.data, status=status.HTTP_200_OK)

    @extend_schema(
        tags=["Admin Payments"],
        summary="Refund payment",
        request=PaymentRefundCreateSerializer,
        responses={
            201: PaymentReadSerializer,
            400: OpenApiResponse(description="Validation error"),
        },
    )
    @action(
        detail=True,
        methods=["post"],
        url_path="refund",
    )
    def refund(self, request, pk=None):
        payment = self.get_object()

        serializer = PaymentRefundCreateSerializer(
            data=request.data,
            context=self.get_serializer_context(),
        )
        serializer.is_valid(raise_exception=True)

        serializer.create_refund(payment)

        payment.refresh_from_db()

        response_serializer = self.get_serializer(payment)

        return Response(response_serializer.data, status=status.HTTP_201_CREATED)


class PaymentWebhookAPIView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(
        tags=["Payment Webhooks"],
        summary="Receive payment webhook event",
        request=dict,
        responses={
            201: PaymentWebhookEventReadSerializer,
            200: PaymentWebhookEventReadSerializer,
            400: OpenApiResponse(description="Invalid provider or webhook payload"),
        },
    )
    def post(self, request, provider):
        provider = provider.upper()

        if provider not in Payment.Provider.values:
            raise ValidationError({"provider": "Unsupported payment provider."})

        payload = request.data if isinstance(request.data, dict) else {"raw": request.data}
        headers = dict(request.headers)

        try:
            provider_adapter = get_payment_provider(provider)
            parsed_event = provider_adapter.parse_webhook(payload, headers=headers)
        except PaymentProviderError as exc:
            raise ValidationError({"provider": str(exc)}) from exc

        event_id = parsed_event.get("event_id", "")
        event_type = parsed_event.get("event_type", "")

        if event_id:
            webhook_event, created = PaymentWebhookEvent.objects.get_or_create(
                provider=provider,
                event_id=event_id,
                defaults={
                    "event_type": event_type,
                    "payload": parsed_event.get("payload") or payload,
                    "headers": parsed_event.get("headers") or headers,
                },
            )

            if not created:
                webhook_event.mark_ignored("Duplicate webhook event.")
                status_code = status.HTTP_200_OK
            else:
                status_code = status.HTTP_201_CREATED
        else:
            webhook_event = PaymentWebhookEvent.objects.create(
                provider=provider,
                event_id="",
                event_type=event_type,
                payload=parsed_event.get("payload") or payload,
                headers=parsed_event.get("headers") or headers,
            )
            status_code = status.HTTP_201_CREATED

        response_serializer = PaymentWebhookEventReadSerializer(webhook_event)

        return Response(response_serializer.data, status=status_code)