from decimal import Decimal
from unittest.mock import patch

import pytest

from apps.accounts.tests.factories import CustomerUserFactory
from apps.cart.tests.factories import CartFactory, CartItemFactory
from apps.catalog.models import Product
from apps.catalog.tests.factories import ApprovedVendorFactory, ProductFactory
from apps.inventory.tests.factories import InventoryRecordFactory
from apps.orders.models import Order
from apps.payments.models import Payment, PaymentWebhookEvent, Refund
from apps.payments.providers import create_manual_payment_for_order
from apps.payments.tasks import (
    process_payment_webhook_event_task,
    send_payment_captured_email_task,
    send_payment_failed_email_task,
    send_refund_processed_email_task,
)


pytestmark = pytest.mark.django_db


def create_active_product_with_inventory(
    *,
    vendor=None,
    name="Task Payment Product",
    base_price=Decimal("50.00"),
    quantity_on_hand=100,
    quantity_reserved=0,
    track_inventory=True,
    allow_backorder=False,
    **overrides,
):
    product = ProductFactory(
        vendor=vendor or ApprovedVendorFactory(),
        name=name,
        base_price=base_price,
        status=Product.Status.ACTIVE,
        **overrides,
    )

    inventory_record = InventoryRecordFactory(
        product=product,
        variant=None,
        quantity_on_hand=quantity_on_hand,
        quantity_reserved=quantity_reserved,
        track_inventory=track_inventory,
        allow_backorder=allow_backorder,
    )

    return product, inventory_record


def create_order_from_cart(
    *,
    customer=None,
    vendor=None,
    product_name="Task Payment Product",
    base_price=Decimal("50.00"),
    quantity=2,
    quantity_on_hand=100,
):
    customer = customer or CustomerUserFactory()
    cart = CartFactory(customer=customer)

    product, inventory_record = create_active_product_with_inventory(
        vendor=vendor,
        name=product_name,
        base_price=base_price,
        quantity_on_hand=quantity_on_hand,
    )

    CartItemFactory(
        cart=cart,
        product=product,
        quantity=quantity,
    )

    order = Order.create_from_cart(cart)

    order.refresh_from_db()
    inventory_record.refresh_from_db()

    return order, product, inventory_record, cart


def create_pending_manual_payment(*, customer=None):
    order, product, inventory_record, cart = create_order_from_cart(
        customer=customer,
    )

    payment = create_manual_payment_for_order(order=order)
    payment.refresh_from_db()

    return payment, order, product, inventory_record, cart


def create_captured_manual_payment(*, customer=None):
    payment, order, product, inventory_record, cart = create_pending_manual_payment(
        customer=customer,
    )

    payment.capture(provider_reference=f"CAPTURE-{payment.id}")
    payment.refresh_from_db()
    order.refresh_from_db()
    inventory_record.refresh_from_db()

    return payment, order, product, inventory_record, cart


def test_send_payment_captured_email_task_sends_email(mailoutbox):
    customer = CustomerUserFactory(email="captured-payment@example.com")
    payment, order, _, _, _ = create_captured_manual_payment(customer=customer)

    result = send_payment_captured_email_task(str(payment.id))

    assert result["sent"] is True
    assert result["payment_id"] == str(payment.id)
    assert result["order_id"] == str(order.id)
    assert result["recipient"] == "captured-payment@example.com"

    assert len(mailoutbox) == 1
    assert mailoutbox[0].to == ["captured-payment@example.com"]
    assert order.order_number in mailoutbox[0].subject
    assert "Payment received" in mailoutbox[0].subject
    assert str(payment.amount_captured) in mailoutbox[0].body


def test_send_payment_failed_email_task_sends_email(mailoutbox):
    customer = CustomerUserFactory(email="failed-payment@example.com")
    payment, order, _, _, _ = create_pending_manual_payment(customer=customer)

    payment.mark_failed(reason="Card declined.")
    payment.refresh_from_db()

    result = send_payment_failed_email_task(str(payment.id))

    assert result["sent"] is True
    assert result["payment_id"] == str(payment.id)
    assert result["order_id"] == str(order.id)
    assert result["recipient"] == "failed-payment@example.com"

    assert len(mailoutbox) == 1
    assert mailoutbox[0].to == ["failed-payment@example.com"]
    assert order.order_number in mailoutbox[0].subject
    assert "Payment failed" in mailoutbox[0].subject
    assert "Card declined." in mailoutbox[0].body


def test_send_refund_processed_email_task_sends_email(mailoutbox):
    customer = CustomerUserFactory(email="refund-payment@example.com")
    payment, order, _, _, _ = create_captured_manual_payment(customer=customer)

    refund = Refund.objects.create(
        payment=payment,
        amount=Decimal("10.00"),
        currency=payment.currency,
    )
    refund.mark_succeeded(provider_reference="REFUND-10")
    refund.refresh_from_db()

    result = send_refund_processed_email_task(str(refund.id))

    assert result["sent"] is True
    assert result["refund_id"] == str(refund.id)
    assert result["payment_id"] == str(payment.id)
    assert result["order_id"] == str(order.id)
    assert result["recipient"] == "refund-payment@example.com"

    assert len(mailoutbox) == 1
    assert mailoutbox[0].to == ["refund-payment@example.com"]
    assert order.order_number in mailoutbox[0].subject
    assert "Refund processed" in mailoutbox[0].subject
    assert str(refund.amount) in mailoutbox[0].body


def test_email_tasks_return_false_for_missing_objects(mailoutbox):
    missing_id = "00000000-0000-0000-0000-000000000000"

    captured_result = send_payment_captured_email_task(missing_id)
    failed_result = send_payment_failed_email_task(missing_id)
    refund_result = send_refund_processed_email_task(missing_id)

    assert captured_result["sent"] is False
    assert captured_result["reason"] == "payment_not_found"

    assert failed_result["sent"] is False
    assert failed_result["reason"] == "payment_not_found"

    assert refund_result["sent"] is False
    assert refund_result["reason"] == "refund_not_found"

    assert len(mailoutbox) == 0


def test_process_manual_payment_captured_webhook_captures_payment():
    payment, order, _, inventory_record, _ = create_pending_manual_payment()

    event = PaymentWebhookEvent.objects.create(
        provider=Payment.Provider.MANUAL,
        event_id="evt_payment_captured_1",
        event_type="manual.payment.captured",
        payload={
            "payment_id": str(payment.id),
            "provider_reference": "WEBHOOK-CAPTURE-1",
        },
    )

    with patch("apps.payments.tasks.send_payment_captured_email_task.delay") as email_task:
        result = process_payment_webhook_event_task(str(event.id))

    payment.refresh_from_db()
    order.refresh_from_db()
    inventory_record.refresh_from_db()
    event.refresh_from_db()

    assert result["processed"] is True
    assert result["action"] == "payment_captured"

    assert payment.status == Payment.Status.CAPTURED
    assert payment.provider_payment_id == "WEBHOOK-CAPTURE-1"

    assert order.payment_status == Order.PaymentStatus.PAID
    assert order.status == Order.Status.CONFIRMED
    assert order.inventory_status == Order.InventoryStatus.COMMITTED

    assert inventory_record.quantity_reserved == 0

    assert event.status == PaymentWebhookEvent.Status.PROCESSED
    assert event.related_payment == payment

    email_task.assert_called_once_with(str(payment.id))


def test_process_manual_payment_failed_webhook_marks_payment_failed():
    payment, order, _, _, _ = create_pending_manual_payment()

    event = PaymentWebhookEvent.objects.create(
        provider=Payment.Provider.MANUAL,
        event_id="evt_payment_failed_1",
        event_type="manual.payment.failed",
        payload={
            "payment_id": str(payment.id),
            "provider_reference": "WEBHOOK-FAILED-1",
            "reason": "Gateway declined payment.",
        },
    )

    with patch("apps.payments.tasks.send_payment_failed_email_task.delay") as email_task:
        result = process_payment_webhook_event_task(str(event.id))

    payment.refresh_from_db()
    order.refresh_from_db()
    event.refresh_from_db()

    assert result["processed"] is True
    assert result["action"] == "payment_failed"

    assert payment.status == Payment.Status.FAILED
    assert payment.provider_payment_id == "WEBHOOK-FAILED-1"
    assert payment.failure_reason == "Gateway declined payment."

    assert order.payment_status == Order.PaymentStatus.FAILED

    assert event.status == PaymentWebhookEvent.Status.PROCESSED
    assert event.related_payment == payment

    email_task.assert_called_once_with(str(payment.id))


def test_process_manual_refund_succeeded_webhook_marks_refund_succeeded():
    payment, order, _, _, _ = create_captured_manual_payment()

    refund = Refund.objects.create(
        payment=payment,
        amount=Decimal("10.00"),
        currency=payment.currency,
    )

    event = PaymentWebhookEvent.objects.create(
        provider=Payment.Provider.MANUAL,
        event_id="evt_refund_succeeded_1",
        event_type="manual.refund.succeeded",
        payload={
            "refund_id": str(refund.id),
            "provider_reference": "WEBHOOK-REFUND-1",
        },
    )

    with patch("apps.payments.tasks.send_refund_processed_email_task.delay") as email_task:
        result = process_payment_webhook_event_task(str(event.id))

    refund.refresh_from_db()
    payment.refresh_from_db()
    order.refresh_from_db()
    event.refresh_from_db()

    assert result["processed"] is True
    assert result["action"] == "refund_succeeded"

    assert refund.status == Refund.Status.SUCCEEDED
    assert refund.provider_refund_id == "WEBHOOK-REFUND-1"

    assert payment.status == Payment.Status.PARTIALLY_REFUNDED
    assert order.payment_status == Order.PaymentStatus.PAID

    assert event.status == PaymentWebhookEvent.Status.PROCESSED
    assert event.related_refund == refund
    assert event.related_payment == payment

    email_task.assert_called_once_with(str(refund.id))


def test_process_manual_webhook_with_missing_payment_marks_event_failed():
    event = PaymentWebhookEvent.objects.create(
        provider=Payment.Provider.MANUAL,
        event_id="evt_missing_payment_1",
        event_type="manual.payment.captured",
        payload={
            "payment_id": "00000000-0000-0000-0000-000000000000",
        },
    )

    result = process_payment_webhook_event_task(str(event.id))

    event.refresh_from_db()

    assert result["processed"] is False
    assert result["reason"] == "payment_not_found"
    assert event.status == PaymentWebhookEvent.Status.FAILED
    assert "Payment not found" in event.error_message


def test_process_unsupported_manual_webhook_marks_event_ignored():
    event = PaymentWebhookEvent.objects.create(
        provider=Payment.Provider.MANUAL,
        event_id="evt_unsupported_manual_1",
        event_type="manual.unknown.event",
        payload={
            "event_id": "evt_unsupported_manual_1",
        },
    )

    result = process_payment_webhook_event_task(str(event.id))

    event.refresh_from_db()

    assert result["processed"] is False
    assert result["reason"] == "unsupported_manual_webhook_event_type"
    assert event.status == PaymentWebhookEvent.Status.IGNORED
    assert event.error_message == "Unsupported manual webhook event type."


def test_process_non_manual_provider_webhook_is_ignored():
    event = PaymentWebhookEvent.objects.create(
        provider=Payment.Provider.STRIPE,
        event_id="evt_stripe_ignored_1",
        event_type="payment_intent.succeeded",
        payload={
            "event_id": "evt_stripe_ignored_1",
        },
    )

    result = process_payment_webhook_event_task(str(event.id))

    event.refresh_from_db()

    assert result["processed"] is False
    assert result["reason"] == "provider_processing_not_implemented"
    assert event.status == PaymentWebhookEvent.Status.IGNORED
    assert "not implemented" in event.error_message