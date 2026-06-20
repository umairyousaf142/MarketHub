from decimal import Decimal

import factory

from apps.orders.tests.factories import OrderFactory
from apps.payments.models import (
    Payment,
    PaymentTransaction,
    PaymentWebhookEvent,
    Refund,
)


class PaymentFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Payment

    order = factory.SubFactory(OrderFactory)
    provider = Payment.Provider.MANUAL
    status = Payment.Status.PENDING

    amount = factory.LazyAttribute(lambda obj: obj.order.total_amount)
    amount_captured = Decimal("0.00")
    currency = "USD"

    provider_payment_id = ""
    provider_client_secret = ""
    idempotency_key = ""
    failure_reason = ""
    metadata = {}
    created_by = None


class PaymentTransactionFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = PaymentTransaction

    payment = factory.SubFactory(PaymentFactory)
    transaction_type = PaymentTransaction.TransactionType.INITIATED

    amount = factory.LazyAttribute(lambda obj: obj.payment.amount)
    currency = factory.LazyAttribute(lambda obj: obj.payment.currency)

    provider_reference = ""
    is_successful = True
    failure_reason = ""
    raw_response = {}


class RefundFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Refund

    payment = factory.SubFactory(
        PaymentFactory,
        status=Payment.Status.CAPTURED,
    )

    amount = Decimal("10.00")
    currency = factory.LazyAttribute(lambda obj: obj.payment.currency)
    status = Refund.Status.PENDING

    reason = ""
    provider_refund_id = ""
    idempotency_key = ""
    metadata = {}
    requested_by = None


class PaymentWebhookEventFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = PaymentWebhookEvent

    provider = Payment.Provider.MANUAL
    event_id = factory.Sequence(lambda n: f"evt_{n}")
    event_type = "manual.test"
    status = PaymentWebhookEvent.Status.RECEIVED

    payload = {}
    headers = {}
    related_payment = None
    related_refund = None
    error_message = ""