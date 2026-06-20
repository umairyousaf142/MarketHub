from decimal import Decimal

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from apps.orders.models import Order
from apps.payments.models import (
    Payment,
    PaymentTransaction,
    PaymentWebhookEvent,
    Refund,
)
from apps.payments.permissions import is_admin_user
from apps.payments.providers import (
    PaymentProviderError,
    create_manual_payment_for_order,
    get_payment_provider,
)


class PaymentTransactionReadSerializer(serializers.ModelSerializer):
    class Meta:
        model = PaymentTransaction
        fields = [
            "id",
            "transaction_type",
            "amount",
            "currency",
            "provider_reference",
            "is_successful",
            "failure_reason",
            "raw_response",
            "created_at",
        ]
        read_only_fields = fields


class RefundReadSerializer(serializers.ModelSerializer):
    class Meta:
        model = Refund
        fields = [
            "id",
            "amount",
            "currency",
            "status",
            "reason",
            "provider_refund_id",
            "idempotency_key",
            "metadata",
            "processed_at",
            "failed_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class PaymentReadSerializer(serializers.ModelSerializer):
    order_number = serializers.CharField(source="order.order_number", read_only=True)
    customer_email = serializers.EmailField(source="order.customer.email", read_only=True)
    transactions = PaymentTransactionReadSerializer(many=True, read_only=True)
    refunds = RefundReadSerializer(many=True, read_only=True)

    refunded_amount = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        read_only=True,
    )
    refundable_amount = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        read_only=True,
    )

    class Meta:
        model = Payment
        fields = [
            "id",
            "order_id",
            "order_number",
            "customer_email",
            "provider",
            "status",
            "amount",
            "amount_captured",
            "refunded_amount",
            "refundable_amount",
            "currency",
            "provider_payment_id",
            "provider_client_secret",
            "idempotency_key",
            "failure_reason",
            "metadata",
            "authorized_at",
            "captured_at",
            "failed_at",
            "cancelled_at",
            "created_at",
            "updated_at",
            "transactions",
            "refunds",
        ]
        read_only_fields = fields


class CustomerManualPaymentCreateSerializer(serializers.Serializer):
    order_id = serializers.UUIDField()
    idempotency_key = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=255,
    )
    metadata = serializers.JSONField(required=False)

    def validate(self, attrs):
        request = self.context["request"]
        user = request.user
        order_id = attrs["order_id"]

        try:
            order = Order.objects.select_related("customer").get(id=order_id)
        except Order.DoesNotExist as exc:
            raise serializers.ValidationError(
                {"order_id": "Order does not exist."}
            ) from exc

        if not is_admin_user(user) and order.customer_id != user.id:
            raise serializers.ValidationError(
                {"order_id": "You can only create payments for your own orders."}
            )

        if order.status == Order.Status.CANCELLED:
            raise serializers.ValidationError(
                {"order_id": "Cannot create payment for a cancelled order."}
            )

        if Payment.objects.filter(
            order=order,
            status__in=Payment.SUCCESSFUL_STATUSES,
        ).exists():
            raise serializers.ValidationError(
                {"order_id": "This order already has a successful payment."}
            )

        if Payment.objects.filter(
            order=order,
            status__in=[
                Payment.Status.PENDING,
                Payment.Status.AUTHORIZED,
            ],
        ).exists():
            raise serializers.ValidationError(
                {"order_id": "This order already has an active payment."}
            )

        attrs["order"] = order

        return attrs

    def create(self, validated_data):
        order = validated_data["order"]
        request = self.context["request"]

        try:
            payment = create_manual_payment_for_order(
                order=order,
                created_by=request.user,
                metadata=validated_data.get("metadata") or {},
            )

            idempotency_key = validated_data.get("idempotency_key") or ""

            if idempotency_key:
                payment.idempotency_key = idempotency_key
                payment.save(update_fields=["idempotency_key", "updated_at"])

            return payment

        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.message_dict) from exc


class PaymentCaptureSerializer(serializers.Serializer):
    provider_reference = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=255,
    )
    metadata = serializers.JSONField(required=False)


class PaymentFailSerializer(serializers.Serializer):
    reason = serializers.CharField()
    provider_reference = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=255,
    )
    metadata = serializers.JSONField(required=False)


class PaymentCancelSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True)
    metadata = serializers.JSONField(required=False)


class PaymentRefundCreateSerializer(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    reason = serializers.CharField(required=False, allow_blank=True)
    provider_reference = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=255,
    )
    idempotency_key = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=255,
    )
    metadata = serializers.JSONField(required=False)

    def validate_amount(self, value):
        if value <= Decimal("0.00"):
            raise serializers.ValidationError("Refund amount must be greater than zero.")

        return value

    def create_refund(self, payment):
        validated_data = self.validated_data

        try:
            refund = Refund.objects.create(
                payment=payment,
                amount=validated_data["amount"],
                currency=payment.currency,
                reason=validated_data.get("reason") or "",
                idempotency_key=validated_data.get("idempotency_key") or "",
                metadata=validated_data.get("metadata") or {},
                requested_by=self.context["request"].user,
            )

            provider = get_payment_provider(payment.provider)

            refund = provider.refund_payment(
                refund,
                provider_reference=validated_data.get("provider_reference") or "",
                metadata=validated_data.get("metadata") or {},
            )

            return refund

        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.message_dict) from exc
        except PaymentProviderError as exc:
            raise serializers.ValidationError({"provider": str(exc)}) from exc


class PaymentWebhookEventReadSerializer(serializers.ModelSerializer):
    class Meta:
        model = PaymentWebhookEvent
        fields = [
            "id",
            "provider",
            "event_id",
            "event_type",
            "status",
            "payload",
            "headers",
            "related_payment_id",
            "related_refund_id",
            "error_message",
            "received_at",
            "processed_at",
        ]
        read_only_fields = fields