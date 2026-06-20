import uuid
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import Q, Sum
from django.utils import timezone

from apps.orders.models import Order


def normalize_money(value):
    return Decimal(str(value or "0.00")).quantize(Decimal("0.01"))


def get_default_currency():
    return getattr(settings, "MARKETHUB_DEFAULT_CURRENCY", "USD")


class Payment(models.Model):
    class Provider(models.TextChoices):
        MANUAL = "MANUAL", "Manual"
        STRIPE = "STRIPE", "Stripe"
        PAYPAL = "PAYPAL", "PayPal"
        JAZZCASH = "JAZZCASH", "JazzCash"
        EASYPAISA = "EASYPAISA", "Easypaisa"
        HBLPAY = "HBLPAY", "HBLPay"

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        AUTHORIZED = "AUTHORIZED", "Authorized"
        CAPTURED = "CAPTURED", "Captured"
        FAILED = "FAILED", "Failed"
        CANCELLED = "CANCELLED", "Cancelled"
        PARTIALLY_REFUNDED = "PARTIALLY_REFUNDED", "Partially Refunded"
        REFUNDED = "REFUNDED", "Refunded"

    SUCCESSFUL_STATUSES = [
        Status.CAPTURED,
        Status.PARTIALLY_REFUNDED,
        Status.REFUNDED,
    ]

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    order = models.ForeignKey(
        Order,
        on_delete=models.PROTECT,
        related_name="payments",
    )

    provider = models.CharField(
        max_length=30,
        choices=Provider.choices,
        default=Provider.MANUAL,
        db_index=True,
    )

    status = models.CharField(
        max_length=30,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )

    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
    )

    amount_captured = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
    )

    currency = models.CharField(
        max_length=3,
        default=get_default_currency,
        db_index=True,
    )

    provider_payment_id = models.CharField(
        max_length=255,
        blank=True,
        default="",
        db_index=True,
    )

    provider_client_secret = models.CharField(
        max_length=500,
        blank=True,
        default="",
    )

    idempotency_key = models.CharField(
        max_length=255,
        blank=True,
        default="",
        db_index=True,
    )

    failure_reason = models.TextField(
        blank=True,
        default="",
    )

    metadata = models.JSONField(
        default=dict,
        blank=True,
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="created_payments",
        null=True,
        blank=True,
    )

    authorized_at = models.DateTimeField(null=True, blank=True)
    captured_at = models.DateTimeField(null=True, blank=True)
    failed_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["order", "status"]),
            models.Index(fields=["provider", "status"]),
            models.Index(fields=["provider_payment_id"]),
            models.Index(fields=["created_at"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(amount__gte=0),
                name="payments_amount_non_negative",
            ),
            models.CheckConstraint(
                condition=Q(amount_captured__gte=0),
                name="payments_amount_captured_non_negative",
            ),
            models.UniqueConstraint(
                fields=["order"],
                condition=Q(
                    status__in=[
                        "CAPTURED",
                        "PARTIALLY_REFUNDED",
                        "REFUNDED",
                    ]
                ),
                name="payments_one_successful_payment_per_order",
            ),
            models.UniqueConstraint(
                fields=["provider", "provider_payment_id"],
                condition=Q(provider_payment_id__gt=""),
                name="payments_unique_provider_payment_id",
            ),
            models.UniqueConstraint(
                fields=["idempotency_key"],
                condition=Q(idempotency_key__gt=""),
                name="payments_unique_idempotency_key",
            ),
        ]

    def __str__(self):
        return f"{self.order.order_number} - {self.provider} - {self.status}"

    @property
    def refunded_amount(self):
        total = (
            self.refunds.filter(status=Refund.Status.SUCCEEDED).aggregate(
                total=Sum("amount")
            )["total"]
            or Decimal("0.00")
        )

        return normalize_money(total)

    @property
    def refundable_amount(self):
        if self.status not in [
            self.Status.CAPTURED,
            self.Status.PARTIALLY_REFUNDED,
        ]:
            return Decimal("0.00")

        remaining = normalize_money(self.amount_captured) - self.refunded_amount

        if remaining < Decimal("0.00"):
            return Decimal("0.00")

        return normalize_money(remaining)

    def clean(self):
        self.amount = normalize_money(self.amount)
        self.amount_captured = normalize_money(self.amount_captured)

        if self.amount < Decimal("0.00"):
            raise ValidationError({"amount": "Payment amount cannot be negative."})

        if self.amount_captured < Decimal("0.00"):
            raise ValidationError(
                {"amount_captured": "Captured amount cannot be negative."}
            )

        if self.order_id:
            order_total = normalize_money(self.order.total_amount)

            if self.amount != order_total:
                raise ValidationError(
                    {
                        "amount": (
                            "Payment amount must match the order total amount "
                            f"({order_total})."
                        )
                    }
                )

            if self.order.status == Order.Status.CANCELLED and self.status not in [
                self.Status.CANCELLED,
                self.Status.FAILED,
            ]:
                raise ValidationError(
                    {"order": "Cannot create active payment for a cancelled order."}
                )

        if self.status == self.Status.AUTHORIZED and not self.authorized_at:
            self.authorized_at = timezone.now()

        if self.status in self.SUCCESSFUL_STATUSES and not self.captured_at:
            self.captured_at = timezone.now()

        if self.status == self.Status.CAPTURED:
            self.amount_captured = self.amount

        if self.status == self.Status.FAILED and not self.failed_at:
            self.failed_at = timezone.now()

        if self.status == self.Status.CANCELLED and not self.cancelled_at:
            self.cancelled_at = timezone.now()

        if self.status in self.SUCCESSFUL_STATUSES and self.order_id:
            existing_successful_payment = (
                Payment.objects.filter(
                    order_id=self.order_id,
                    status__in=self.SUCCESSFUL_STATUSES,
                )
                .exclude(pk=self.pk)
                .exists()
            )

            if existing_successful_payment:
                raise ValidationError(
                    {"order": "This order already has a successful payment."}
                )

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    @classmethod
    def create_for_order(
        cls,
        *,
        order,
        provider=Provider.MANUAL,
        amount=None,
        currency=None,
        created_by=None,
        idempotency_key="",
        metadata=None,
    ):
        payment_amount = normalize_money(
            order.total_amount if amount is None else amount
        )

        return cls.objects.create(
            order=order,
            provider=provider,
            status=cls.Status.PENDING,
            amount=payment_amount,
            amount_captured=Decimal("0.00"),
            currency=currency or get_default_currency(),
            created_by=created_by,
            idempotency_key=idempotency_key,
            metadata=metadata or {},
        )

    def mark_authorized(self, *, provider_reference="", metadata=None):
        with transaction.atomic():
            payment = (
                Payment.objects.select_for_update()
                .select_related("order")
                .get(pk=self.pk)
            )

            if payment.status in [
                payment.Status.CAPTURED,
                payment.Status.PARTIALLY_REFUNDED,
                payment.Status.REFUNDED,
            ]:
                raise ValidationError(
                    {"status": "Captured/refunded payment cannot be authorized again."}
                )

            if payment.status == payment.Status.CANCELLED:
                raise ValidationError(
                    {"status": "Cancelled payment cannot be authorized."}
                )

            payment.status = payment.Status.AUTHORIZED
            payment.authorized_at = timezone.now()

            if provider_reference:
                payment.provider_payment_id = provider_reference

            if metadata:
                payment.metadata.update(metadata)

            payment.save(
                update_fields=[
                    "status",
                    "authorized_at",
                    "provider_payment_id",
                    "metadata",
                    "updated_at",
                ]
            )

            PaymentTransaction.objects.create(
                payment=payment,
                transaction_type=PaymentTransaction.TransactionType.AUTHORIZATION,
                amount=payment.amount,
                currency=payment.currency,
                provider_reference=provider_reference,
                is_successful=True,
                raw_response=metadata or {},
            )

            return payment

    def capture(
        self,
        *,
        provider_reference="",
        metadata=None,
        commit_order=True,
    ):
        with transaction.atomic():
            payment = (
                Payment.objects.select_for_update()
                .select_related("order")
                .get(pk=self.pk)
            )

            if payment.status == payment.Status.CAPTURED:
                return payment

            if payment.status in [
                payment.Status.CANCELLED,
                payment.Status.FAILED,
                payment.Status.PARTIALLY_REFUNDED,
                payment.Status.REFUNDED,
            ]:
                raise ValidationError(
                    {"status": f"Payment cannot be captured from {payment.status}."}
                )

            if payment.order.status == Order.Status.CANCELLED:
                raise ValidationError(
                    {"order": "Cannot capture payment for a cancelled order."}
                )

            payment.status = payment.Status.CAPTURED
            payment.amount_captured = payment.amount
            payment.captured_at = timezone.now()

            if provider_reference:
                payment.provider_payment_id = provider_reference

            if metadata:
                payment.metadata.update(metadata)

            payment.save(
                update_fields=[
                    "status",
                    "amount_captured",
                    "captured_at",
                    "provider_payment_id",
                    "metadata",
                    "updated_at",
                ]
            )

            PaymentTransaction.objects.create(
                payment=payment,
                transaction_type=PaymentTransaction.TransactionType.CAPTURE,
                amount=payment.amount,
                currency=payment.currency,
                provider_reference=provider_reference,
                is_successful=True,
                raw_response=metadata or {},
            )

            order = payment.order

            if commit_order and order.payment_status != Order.PaymentStatus.PAID:
                order.mark_paid(commit_inventory=True)

            return payment

    def mark_failed(self, *, reason="", provider_reference="", metadata=None):
        with transaction.atomic():
            payment = (
                Payment.objects.select_for_update()
                .select_related("order")
                .get(pk=self.pk)
            )

            if payment.status in payment.SUCCESSFUL_STATUSES:
                raise ValidationError(
                    {"status": "Successful payment cannot be marked as failed."}
                )

            payment.status = payment.Status.FAILED
            payment.failure_reason = reason
            payment.failed_at = timezone.now()

            if provider_reference:
                payment.provider_payment_id = provider_reference

            if metadata:
                payment.metadata.update(metadata)

            payment.save(
                update_fields=[
                    "status",
                    "failure_reason",
                    "failed_at",
                    "provider_payment_id",
                    "metadata",
                    "updated_at",
                ]
            )

            PaymentTransaction.objects.create(
                payment=payment,
                transaction_type=PaymentTransaction.TransactionType.FAILURE,
                amount=payment.amount,
                currency=payment.currency,
                provider_reference=provider_reference,
                is_successful=False,
                failure_reason=reason,
                raw_response=metadata or {},
            )

            if not payment.order.payments.filter(
                status__in=payment.SUCCESSFUL_STATUSES
            ).exists():
                payment.order.payment_status = Order.PaymentStatus.FAILED
                payment.order.save(update_fields=["payment_status", "updated_at"])

            return payment

    def cancel(self, *, reason="", metadata=None):
        with transaction.atomic():
            payment = (
                Payment.objects.select_for_update()
                .select_related("order")
                .get(pk=self.pk)
            )

            if payment.status in payment.SUCCESSFUL_STATUSES:
                raise ValidationError(
                    {"status": "Successful payment cannot be cancelled."}
                )

            payment.status = payment.Status.CANCELLED
            payment.failure_reason = reason
            payment.cancelled_at = timezone.now()

            if metadata:
                payment.metadata.update(metadata)

            payment.save(
                update_fields=[
                    "status",
                    "failure_reason",
                    "cancelled_at",
                    "metadata",
                    "updated_at",
                ]
            )

            PaymentTransaction.objects.create(
                payment=payment,
                transaction_type=PaymentTransaction.TransactionType.CANCELLATION,
                amount=payment.amount,
                currency=payment.currency,
                is_successful=True,
                failure_reason=reason,
                raw_response=metadata or {},
            )

            return payment


class PaymentTransaction(models.Model):
    class TransactionType(models.TextChoices):
        INITIATED = "INITIATED", "Initiated"
        AUTHORIZATION = "AUTHORIZATION", "Authorization"
        CAPTURE = "CAPTURE", "Capture"
        FAILURE = "FAILURE", "Failure"
        CANCELLATION = "CANCELLATION", "Cancellation"
        REFUND = "REFUND", "Refund"
        WEBHOOK = "WEBHOOK", "Webhook"

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    payment = models.ForeignKey(
        Payment,
        on_delete=models.PROTECT,
        related_name="transactions",
    )

    transaction_type = models.CharField(
        max_length=30,
        choices=TransactionType.choices,
        db_index=True,
    )

    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
    )

    currency = models.CharField(
        max_length=3,
        default=get_default_currency,
        db_index=True,
    )

    provider_reference = models.CharField(
        max_length=255,
        blank=True,
        default="",
        db_index=True,
    )

    is_successful = models.BooleanField(default=False, db_index=True)

    failure_reason = models.TextField(
        blank=True,
        default="",
    )

    raw_response = models.JSONField(
        default=dict,
        blank=True,
    )

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["payment", "transaction_type"]),
            models.Index(fields=["provider_reference"]),
            models.Index(fields=["is_successful", "created_at"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(amount__gte=0),
                name="payments_transaction_amount_non_negative",
            ),
        ]

    def __str__(self):
        return f"{self.payment_id} - {self.transaction_type} - {self.amount}"

    def clean(self):
        self.amount = normalize_money(self.amount)

        if self.amount < Decimal("0.00"):
            raise ValidationError({"amount": "Transaction amount cannot be negative."})

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class Refund(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        SUCCEEDED = "SUCCEEDED", "Succeeded"
        FAILED = "FAILED", "Failed"
        CANCELLED = "CANCELLED", "Cancelled"

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    payment = models.ForeignKey(
        Payment,
        on_delete=models.PROTECT,
        related_name="refunds",
    )

    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
    )

    currency = models.CharField(
        max_length=3,
        default=get_default_currency,
        db_index=True,
    )

    status = models.CharField(
        max_length=30,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )

    reason = models.TextField(
        blank=True,
        default="",
    )

    provider_refund_id = models.CharField(
        max_length=255,
        blank=True,
        default="",
        db_index=True,
    )

    idempotency_key = models.CharField(
        max_length=255,
        blank=True,
        default="",
        db_index=True,
    )

    metadata = models.JSONField(
        default=dict,
        blank=True,
    )

    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="requested_refunds",
        null=True,
        blank=True,
    )

    processed_at = models.DateTimeField(null=True, blank=True)
    failed_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["payment", "status"]),
            models.Index(fields=["provider_refund_id"]),
            models.Index(fields=["created_at"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(amount__gte=0),
                name="payments_refund_amount_non_negative",
            ),
            models.UniqueConstraint(
                fields=["provider_refund_id"],
                condition=Q(provider_refund_id__gt=""),
                name="payments_unique_provider_refund_id",
            ),
            models.UniqueConstraint(
                fields=["idempotency_key"],
                condition=Q(idempotency_key__gt=""),
                name="payments_unique_refund_idempotency_key",
            ),
        ]

    def __str__(self):
        return f"{self.payment.order.order_number} - Refund - {self.status}"

    def clean(self):
        self.amount = normalize_money(self.amount)

        if self.amount < Decimal("0.00"):
            raise ValidationError({"amount": "Refund amount cannot be negative."})

        if self.payment_id:
            if self.currency != self.payment.currency:
                raise ValidationError(
                    {"currency": "Refund currency must match payment currency."}
                )

            if self.payment.status not in [
                Payment.Status.CAPTURED,
                Payment.Status.PARTIALLY_REFUNDED,
            ]:
                raise ValidationError(
                    {"payment": "Only captured payments can be refunded."}
                )

            existing_refunded_amount = (
                self.payment.refunds.filter(status=self.Status.SUCCEEDED)
                .exclude(pk=self.pk)
                .aggregate(total=Sum("amount"))["total"]
                or Decimal("0.00")
            )

            available_amount = normalize_money(
                self.payment.amount_captured - existing_refunded_amount
            )

            if self.status not in [self.Status.FAILED, self.Status.CANCELLED]:
                if self.amount > available_amount:
                    raise ValidationError(
                        {
                            "amount": (
                                "Refund amount cannot exceed refundable amount "
                                f"({available_amount})."
                            )
                        }
                    )

        if self.status == self.Status.SUCCEEDED and not self.processed_at:
            self.processed_at = timezone.now()

        if self.status == self.Status.FAILED and not self.failed_at:
            self.failed_at = timezone.now()

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def mark_succeeded(self, *, provider_reference="", metadata=None):
        with transaction.atomic():
            refund = (
                Refund.objects.select_for_update()
                .select_related("payment", "payment__order")
                .get(pk=self.pk)
            )

            if refund.status == refund.Status.SUCCEEDED:
                return refund

            if refund.status in [refund.Status.FAILED, refund.Status.CANCELLED]:
                raise ValidationError(
                    {"status": f"Refund cannot succeed from {refund.status}."}
                )

            if provider_reference:
                refund.provider_refund_id = provider_reference

            if metadata:
                refund.metadata.update(metadata)

            refund.status = refund.Status.SUCCEEDED
            refund.processed_at = timezone.now()
            refund.save(
                update_fields=[
                    "status",
                    "provider_refund_id",
                    "metadata",
                    "processed_at",
                    "updated_at",
                ]
            )

            PaymentTransaction.objects.create(
                payment=refund.payment,
                transaction_type=PaymentTransaction.TransactionType.REFUND,
                amount=refund.amount,
                currency=refund.currency,
                provider_reference=provider_reference,
                is_successful=True,
                raw_response=metadata or {},
            )

            payment = refund.payment
            payment.refresh_from_db()

            if payment.refundable_amount == Decimal("0.00"):
                payment.status = Payment.Status.REFUNDED
                payment.order.payment_status = Order.PaymentStatus.REFUNDED
                payment.order.save(update_fields=["payment_status", "updated_at"])
            else:
                payment.status = Payment.Status.PARTIALLY_REFUNDED

            payment.save(update_fields=["status", "updated_at"])

            return refund

    def mark_failed(self, *, reason="", metadata=None):
        with transaction.atomic():
            refund = Refund.objects.select_for_update().get(pk=self.pk)

            if refund.status == refund.Status.SUCCEEDED:
                raise ValidationError(
                    {"status": "Succeeded refund cannot be marked as failed."}
                )

            refund.status = refund.Status.FAILED
            refund.reason = reason
            refund.failed_at = timezone.now()

            if metadata:
                refund.metadata.update(metadata)

            refund.save(
                update_fields=[
                    "status",
                    "reason",
                    "failed_at",
                    "metadata",
                    "updated_at",
                ]
            )

            PaymentTransaction.objects.create(
                payment=refund.payment,
                transaction_type=PaymentTransaction.TransactionType.REFUND,
                amount=refund.amount,
                currency=refund.currency,
                is_successful=False,
                failure_reason=reason,
                raw_response=metadata or {},
            )

            return refund


class PaymentWebhookEvent(models.Model):
    class Status(models.TextChoices):
        RECEIVED = "RECEIVED", "Received"
        PROCESSED = "PROCESSED", "Processed"
        FAILED = "FAILED", "Failed"
        IGNORED = "IGNORED", "Ignored"

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    provider = models.CharField(
        max_length=30,
        choices=Payment.Provider.choices,
        db_index=True,
    )

    event_id = models.CharField(
        max_length=255,
        blank=True,
        default="",
        db_index=True,
    )

    event_type = models.CharField(
        max_length=255,
        blank=True,
        default="",
        db_index=True,
    )

    status = models.CharField(
        max_length=30,
        choices=Status.choices,
        default=Status.RECEIVED,
        db_index=True,
    )

    payload = models.JSONField(default=dict, blank=True)
    headers = models.JSONField(default=dict, blank=True)

    related_payment = models.ForeignKey(
        Payment,
        on_delete=models.SET_NULL,
        related_name="webhook_events",
        null=True,
        blank=True,
    )

    related_refund = models.ForeignKey(
        Refund,
        on_delete=models.SET_NULL,
        related_name="webhook_events",
        null=True,
        blank=True,
    )

    error_message = models.TextField(
        blank=True,
        default="",
    )

    received_at = models.DateTimeField(auto_now_add=True, db_index=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-received_at"]
        indexes = [
            models.Index(fields=["provider", "event_type"]),
            models.Index(fields=["status", "received_at"]),
            models.Index(fields=["event_id"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["provider", "event_id"],
                condition=Q(event_id__gt=""),
                name="payments_unique_provider_webhook_event",
            ),
        ]

    def __str__(self):
        return f"{self.provider} - {self.event_type or self.event_id} - {self.status}"

    def mark_processed(self):
        self.status = self.Status.PROCESSED
        self.processed_at = timezone.now()
        self.save(update_fields=["status", "processed_at"])

    def mark_failed(self, error_message):
        self.status = self.Status.FAILED
        self.error_message = error_message
        self.processed_at = timezone.now()
        self.save(update_fields=["status", "error_message", "processed_at"])

    def mark_ignored(self, reason=""):
        self.status = self.Status.IGNORED
        self.error_message = reason
        self.processed_at = timezone.now()
        self.save(update_fields=["status", "error_message", "processed_at"])