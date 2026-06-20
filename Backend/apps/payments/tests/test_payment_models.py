from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from apps.accounts.tests.factories import AdminUserFactory, CustomerUserFactory
from apps.cart.tests.factories import CartFactory, CartItemFactory
from apps.catalog.models import Product
from apps.catalog.tests.factories import ApprovedVendorFactory, ProductFactory
from apps.inventory.tests.factories import InventoryRecordFactory
from apps.orders.models import Order, VendorOrder
from apps.payments.models import (
    Payment,
    PaymentTransaction,
    PaymentWebhookEvent,
    Refund,
    get_default_currency,
)
from apps.payments.providers import (
    PaymentProviderError,
    capture_manual_payment,
    create_manual_payment_for_order,
    get_payment_provider,
)
from apps.payments.tests.factories import (
    PaymentFactory,
    PaymentTransactionFactory,
    PaymentWebhookEventFactory,
    RefundFactory,
)


pytestmark = pytest.mark.django_db


def create_active_product_with_inventory(
    *,
    vendor=None,
    name="Payment Product",
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
    product_name="Payment Product",
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


def test_payment_create_for_order_uses_order_total_and_defaults():
    admin = AdminUserFactory()
    order, _, _, _ = create_order_from_cart()

    payment = Payment.create_for_order(
        order=order,
        created_by=admin,
        metadata={"source": "test"},
    )

    assert payment.order == order
    assert payment.provider == Payment.Provider.MANUAL
    assert payment.status == Payment.Status.PENDING
    assert payment.amount == order.total_amount
    assert payment.amount_captured == Decimal("0.00")
    assert payment.currency == get_default_currency()
    assert payment.created_by == admin
    assert payment.metadata == {"source": "test"}


def test_payment_amount_must_match_order_total():
    order, _, _, _ = create_order_from_cart()

    with pytest.raises(ValidationError):
        PaymentFactory(
            order=order,
            amount=order.total_amount + Decimal("1.00"),
        )


def test_payment_amount_cannot_be_negative():
    order, _, _, _ = create_order_from_cart()

    with pytest.raises(ValidationError):
        PaymentFactory(
            order=order,
            amount=Decimal("-1.00"),
        )


def test_payment_cannot_be_active_for_cancelled_order():
    order, _, _, _ = create_order_from_cart()
    order.cancel()
    order.refresh_from_db()

    with pytest.raises(ValidationError):
        Payment.create_for_order(order=order)


def test_payment_sets_timestamps_for_statuses():
    order, _, _, _ = create_order_from_cart()

    authorized = PaymentFactory(
        order=order,
        status=Payment.Status.AUTHORIZED,
    )

    assert authorized.authorized_at is not None

    failed = PaymentFactory(
        order=order,
        status=Payment.Status.FAILED,
    )

    assert failed.failed_at is not None

    cancelled = PaymentFactory(
        order=order,
        status=Payment.Status.CANCELLED,
    )

    assert cancelled.cancelled_at is not None


def test_mark_authorized_creates_authorization_transaction():
    order, _, _, _ = create_order_from_cart()
    payment = Payment.create_for_order(order=order)

    payment.mark_authorized(
        provider_reference="AUTH-123",
        metadata={"gateway": "manual"},
    )

    payment.refresh_from_db()

    assert payment.status == Payment.Status.AUTHORIZED
    assert payment.authorized_at is not None
    assert payment.provider_payment_id == "AUTH-123"
    assert payment.metadata["gateway"] == "manual"

    transaction_obj = payment.transactions.get(
        transaction_type=PaymentTransaction.TransactionType.AUTHORIZATION
    )

    assert transaction_obj.amount == payment.amount
    assert transaction_obj.currency == payment.currency
    assert transaction_obj.provider_reference == "AUTH-123"
    assert transaction_obj.is_successful is True


def test_capture_payment_marks_order_paid_and_commits_inventory():
    order, _, inventory_record, _ = create_order_from_cart(
        quantity=3,
        quantity_on_hand=20,
    )

    payment = Payment.create_for_order(order=order)

    payment.capture(
        provider_reference="CAPTURE-123",
        metadata={"gateway": "manual"},
    )

    payment.refresh_from_db()
    order.refresh_from_db()
    inventory_record.refresh_from_db()

    vendor_order = order.vendor_orders.first()

    assert payment.status == Payment.Status.CAPTURED
    assert payment.amount_captured == payment.amount
    assert payment.captured_at is not None
    assert payment.provider_payment_id == "CAPTURE-123"

    assert order.payment_status == Order.PaymentStatus.PAID
    assert order.status == Order.Status.CONFIRMED
    assert order.inventory_status == Order.InventoryStatus.COMMITTED

    assert inventory_record.quantity_on_hand == 17
    assert inventory_record.quantity_reserved == 0

    assert vendor_order.status == VendorOrder.Status.CONFIRMED

    capture_transaction = payment.transactions.get(
        transaction_type=PaymentTransaction.TransactionType.CAPTURE
    )

    assert capture_transaction.is_successful is True
    assert capture_transaction.amount == payment.amount


def test_capture_is_idempotent_for_already_captured_payment():
    order, _, _, _ = create_order_from_cart()
    payment = Payment.create_for_order(order=order)

    payment.capture(provider_reference="CAPTURE-123")
    payment.refresh_from_db()

    payment.capture(provider_reference="CAPTURE-456")
    payment.refresh_from_db()

    assert payment.status == Payment.Status.CAPTURED
    assert payment.provider_payment_id == "CAPTURE-123"
    assert payment.transactions.filter(
        transaction_type=PaymentTransaction.TransactionType.CAPTURE
    ).count() == 1


def test_capture_rejects_failed_payment():
    order, _, _, _ = create_order_from_cart()
    payment = Payment.create_for_order(order=order)
    payment.mark_failed(reason="Gateway failed.")

    with pytest.raises(ValidationError):
        payment.capture()


def test_capture_rejects_cancelled_order():
    order, _, _, _ = create_order_from_cart()
    payment = Payment.create_for_order(order=order)

    order.cancel()
    order.refresh_from_db()

    with pytest.raises(ValidationError):
        payment.capture()


def test_only_one_successful_payment_allowed_per_order():
    order, _, _, _ = create_order_from_cart()

    first_payment = Payment.create_for_order(order=order)
    first_payment.capture(provider_reference="CAPTURE-1")

    second_payment = Payment.create_for_order(order=order)

    with pytest.raises(ValidationError):
        second_payment.capture(provider_reference="CAPTURE-2")


def test_mark_failed_creates_failed_transaction_and_updates_order_payment_status():
    order, _, _, _ = create_order_from_cart()
    payment = Payment.create_for_order(order=order)

    payment.mark_failed(
        reason="Card declined.",
        provider_reference="FAILED-123",
        metadata={"code": "card_declined"},
    )

    payment.refresh_from_db()
    order.refresh_from_db()

    assert payment.status == Payment.Status.FAILED
    assert payment.failure_reason == "Card declined."
    assert payment.failed_at is not None
    assert payment.provider_payment_id == "FAILED-123"
    assert order.payment_status == Order.PaymentStatus.FAILED

    transaction_obj = payment.transactions.get(
        transaction_type=PaymentTransaction.TransactionType.FAILURE
    )

    assert transaction_obj.is_successful is False
    assert transaction_obj.failure_reason == "Card declined."
    assert transaction_obj.raw_response == {"code": "card_declined"}


def test_successful_payment_cannot_be_marked_failed():
    order, _, _, _ = create_order_from_cart()
    payment = Payment.create_for_order(order=order)

    payment.capture(provider_reference="CAPTURE-123")

    with pytest.raises(ValidationError):
        payment.mark_failed(reason="Should not fail.")


def test_cancel_pending_payment_creates_cancellation_transaction():
    order, _, _, _ = create_order_from_cart()
    payment = Payment.create_for_order(order=order)

    payment.cancel(
        reason="Customer abandoned payment.",
        metadata={"source": "test"},
    )

    payment.refresh_from_db()

    assert payment.status == Payment.Status.CANCELLED
    assert payment.failure_reason == "Customer abandoned payment."
    assert payment.cancelled_at is not None

    transaction_obj = payment.transactions.get(
        transaction_type=PaymentTransaction.TransactionType.CANCELLATION
    )

    assert transaction_obj.is_successful is True
    assert transaction_obj.failure_reason == "Customer abandoned payment."


def test_successful_payment_cannot_be_cancelled():
    order, _, _, _ = create_order_from_cart()
    payment = Payment.create_for_order(order=order)

    payment.capture(provider_reference="CAPTURE-123")

    with pytest.raises(ValidationError):
        payment.cancel(reason="Too late.")


def test_payment_refunded_amount_and_refundable_amount_properties():
    order, _, _, _ = create_order_from_cart()
    payment = Payment.create_for_order(order=order)
    payment.capture(provider_reference="CAPTURE-123")
    payment.refresh_from_db()

    refund = Refund.objects.create(
        payment=payment,
        amount=Decimal("25.00"),
        currency=payment.currency,
    )
    refund.mark_succeeded(provider_reference="REFUND-25")

    payment.refresh_from_db()

    assert payment.refunded_amount == Decimal("25.00")
    assert payment.refundable_amount == payment.amount_captured - Decimal("25.00")


def test_refund_requires_captured_payment():
    order, _, _, _ = create_order_from_cart()
    payment = Payment.create_for_order(order=order)

    with pytest.raises(ValidationError):
        Refund.objects.create(
            payment=payment,
            amount=Decimal("10.00"),
            currency=payment.currency,
        )


def test_refund_amount_cannot_exceed_refundable_amount():
    order, _, _, _ = create_order_from_cart()
    payment = Payment.create_for_order(order=order)
    payment.capture(provider_reference="CAPTURE-123")
    payment.refresh_from_db()

    with pytest.raises(ValidationError):
        Refund.objects.create(
            payment=payment,
            amount=payment.amount_captured + Decimal("1.00"),
            currency=payment.currency,
        )


def test_partial_refund_updates_payment_status():
    order, _, _, _ = create_order_from_cart()
    payment = Payment.create_for_order(order=order)
    payment.capture(provider_reference="CAPTURE-123")
    payment.refresh_from_db()

    refund = Refund.objects.create(
        payment=payment,
        amount=Decimal("40.00"),
        currency=payment.currency,
    )

    refund = refund.mark_succeeded(provider_reference="REFUND-40")
    refund.refresh_from_db()

    payment.refresh_from_db()
    order.refresh_from_db()

    assert refund.status == Refund.Status.SUCCEEDED
    assert payment.status == Payment.Status.PARTIALLY_REFUNDED
    assert payment.refunded_amount == Decimal("40.00")
    assert payment.refundable_amount == payment.amount_captured - Decimal("40.00")
    assert order.payment_status == Order.PaymentStatus.PAID


def test_full_refund_updates_payment_and_order_status():
    order, _, _, _ = create_order_from_cart()
    payment = Payment.create_for_order(order=order)
    payment.capture(provider_reference="CAPTURE-123")
    payment.refresh_from_db()

    first_refund = Refund.objects.create(
        payment=payment,
        amount=Decimal("40.00"),
        currency=payment.currency,
    )
    first_refund.mark_succeeded(provider_reference="REFUND-40")

    payment.refresh_from_db()

    second_refund = Refund.objects.create(
        payment=payment,
        amount=payment.refundable_amount,
        currency=payment.currency,
    )
    second_refund.mark_succeeded(provider_reference="REFUND-REMAINING")

    payment.refresh_from_db()
    order.refresh_from_db()

    assert payment.status == Payment.Status.REFUNDED
    assert payment.refundable_amount == Decimal("0.00")
    assert order.payment_status == Order.PaymentStatus.REFUNDED


def test_succeeded_refund_is_idempotent():
    order, _, _, _ = create_order_from_cart()
    payment = Payment.create_for_order(order=order)
    payment.capture(provider_reference="CAPTURE-123")
    payment.refresh_from_db()

    refund = Refund.objects.create(
        payment=payment,
        amount=Decimal("10.00"),
        currency=payment.currency,
    )

    refund.mark_succeeded(provider_reference="REFUND-10")
    refund.mark_succeeded(provider_reference="REFUND-10-AGAIN")

    refund.refresh_from_db()

    assert refund.status == Refund.Status.SUCCEEDED
    assert refund.provider_refund_id == "REFUND-10"
    assert payment.transactions.filter(
        transaction_type=PaymentTransaction.TransactionType.REFUND
    ).count() == 1


def test_failed_refund_creates_failed_transaction():
    order, _, _, _ = create_order_from_cart()
    payment = Payment.create_for_order(order=order)
    payment.capture(provider_reference="CAPTURE-123")
    payment.refresh_from_db()

    refund = Refund.objects.create(
        payment=payment,
        amount=Decimal("10.00"),
        currency=payment.currency,
    )

    refund.mark_failed(
        reason="Gateway refund failed.",
        metadata={"code": "refund_failed"},
    )

    refund.refresh_from_db()

    assert refund.status == Refund.Status.FAILED
    assert refund.reason == "Gateway refund failed."
    assert refund.failed_at is not None

    transaction_obj = payment.transactions.get(
        transaction_type=PaymentTransaction.TransactionType.REFUND,
        is_successful=False,
    )

    assert transaction_obj.failure_reason == "Gateway refund failed."
    assert transaction_obj.raw_response == {"code": "refund_failed"}


def test_succeeded_refund_cannot_be_marked_failed():
    order, _, _, _ = create_order_from_cart()
    payment = Payment.create_for_order(order=order)
    payment.capture(provider_reference="CAPTURE-123")
    payment.refresh_from_db()

    refund = Refund.objects.create(
        payment=payment,
        amount=Decimal("10.00"),
        currency=payment.currency,
    )
    refund.mark_succeeded(provider_reference="REFUND-10")

    with pytest.raises(ValidationError):
        refund.mark_failed(reason="Should not fail.")


def test_payment_transaction_amount_cannot_be_negative():
    payment = PaymentFactory()

    with pytest.raises(ValidationError):
        PaymentTransactionFactory(
            payment=payment,
            amount=Decimal("-1.00"),
        )


def test_webhook_event_mark_processed_failed_and_ignored():
    event = PaymentWebhookEventFactory(
        event_type="manual.payment.created",
    )

    event.mark_processed()
    event.refresh_from_db()

    assert event.status == PaymentWebhookEvent.Status.PROCESSED
    assert event.processed_at is not None

    failed_event = PaymentWebhookEventFactory()
    failed_event.mark_failed("Invalid signature.")
    failed_event.refresh_from_db()

    assert failed_event.status == PaymentWebhookEvent.Status.FAILED
    assert failed_event.error_message == "Invalid signature."
    assert failed_event.processed_at is not None

    ignored_event = PaymentWebhookEventFactory()
    ignored_event.mark_ignored("Unsupported event.")
    ignored_event.refresh_from_db()

    assert ignored_event.status == PaymentWebhookEvent.Status.IGNORED
    assert ignored_event.error_message == "Unsupported event."
    assert ignored_event.processed_at is not None


def test_webhook_event_provider_event_id_is_unique():
    PaymentWebhookEventFactory(
        provider=Payment.Provider.MANUAL,
        event_id="evt_unique_1",
    )

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            PaymentWebhookEventFactory(
                provider=Payment.Provider.MANUAL,
                event_id="evt_unique_1",
            )


def test_manual_provider_create_payment_creates_initiated_transaction():
    order, _, _, _ = create_order_from_cart()
    payment = Payment.create_for_order(order=order)

    provider = get_payment_provider(Payment.Provider.MANUAL)

    result = provider.create_payment(payment)

    assert result.provider == Payment.Provider.MANUAL
    assert result.payment_id == str(payment.id)
    assert result.status == Payment.Status.PENDING
    assert result.provider_reference == str(payment.id)

    transaction_obj = payment.transactions.get(
        transaction_type=PaymentTransaction.TransactionType.INITIATED
    )

    assert transaction_obj.is_successful is True
    assert transaction_obj.amount == payment.amount
    assert transaction_obj.provider_reference == str(payment.id)


def test_manual_provider_capture_payment_captures_and_syncs_order():
    order, _, _, _ = create_order_from_cart()
    payment = Payment.create_for_order(order=order)

    provider = get_payment_provider(Payment.Provider.MANUAL)

    provider.capture_payment(payment)

    payment.refresh_from_db()
    order.refresh_from_db()

    assert payment.status == Payment.Status.CAPTURED
    assert payment.provider_payment_id == f"MANUAL-{payment.id}"
    assert order.payment_status == Order.PaymentStatus.PAID


def test_manual_provider_refund_payment_marks_refund_succeeded():
    order, _, _, _ = create_order_from_cart()
    payment = Payment.create_for_order(order=order)
    payment.capture(provider_reference="CAPTURE-123")
    payment.refresh_from_db()

    refund = Refund.objects.create(
        payment=payment,
        amount=Decimal("10.00"),
        currency=payment.currency,
    )

    provider = get_payment_provider(Payment.Provider.MANUAL)

    provider.refund_payment(refund)

    refund.refresh_from_db()

    assert refund.status == Refund.Status.SUCCEEDED
    assert refund.provider_refund_id == f"MANUAL-REFUND-{refund.id}"


def test_placeholder_provider_raises_for_non_implemented_gateway():
    order, _, _, _ = create_order_from_cart()

    payment = Payment.create_for_order(
        order=order,
        provider=Payment.Provider.STRIPE,
    )

    provider = get_payment_provider(Payment.Provider.STRIPE)

    with pytest.raises(PaymentProviderError):
        provider.create_payment(payment)


def test_get_payment_provider_rejects_unsupported_provider():
    with pytest.raises(PaymentProviderError):
        get_payment_provider("UNKNOWN")


def test_create_manual_payment_for_order_creates_payment_and_transaction():
    order, _, _, _ = create_order_from_cart()

    payment = create_manual_payment_for_order(
        order=order,
        metadata={"source": "admin"},
    )

    assert payment.order == order
    assert payment.provider == Payment.Provider.MANUAL
    assert payment.status == Payment.Status.PENDING
    assert payment.metadata == {"source": "admin"}

    assert payment.transactions.filter(
        transaction_type=PaymentTransaction.TransactionType.INITIATED
    ).count() == 1


def test_capture_manual_payment_captures_payment():
    order, _, _, _ = create_order_from_cart()
    payment = create_manual_payment_for_order(order=order)

    capture_manual_payment(
        payment=payment,
        provider_reference="MANUAL-CAPTURE-1",
    )

    payment.refresh_from_db()
    order.refresh_from_db()

    assert payment.status == Payment.Status.CAPTURED
    assert payment.provider_payment_id == "MANUAL-CAPTURE-1"
    assert order.payment_status == Order.PaymentStatus.PAID


def test_provider_payment_id_must_be_unique_per_provider_when_present():
    first_order, _, _, _ = create_order_from_cart()
    second_order, _, _, _ = create_order_from_cart()

    Payment.create_for_order(
        order=first_order,
        provider=Payment.Provider.MANUAL,
    )

    PaymentFactory(
        order=first_order,
        provider=Payment.Provider.MANUAL,
        provider_payment_id="PROVIDER-PAYMENT-1",
    )

    with pytest.raises((ValidationError, IntegrityError)):
        with transaction.atomic():
            PaymentFactory(
                order=second_order,
                provider=Payment.Provider.MANUAL,
                provider_payment_id="PROVIDER-PAYMENT-1",
            )


def test_payment_idempotency_key_must_be_unique_when_present():
    first_order, _, _, _ = create_order_from_cart()
    second_order, _, _, _ = create_order_from_cart()

    PaymentFactory(
        order=first_order,
        idempotency_key="payment-idempotency-1",
    )

    with pytest.raises((ValidationError, IntegrityError)):
        with transaction.atomic():
            PaymentFactory(
                order=second_order,
                idempotency_key="payment-idempotency-1",
            )


def test_refund_idempotency_key_must_be_unique_when_present():
    first_order, _, _, _ = create_order_from_cart()
    first_payment = Payment.create_for_order(order=first_order)
    first_payment.capture(provider_reference="CAPTURE-1")
    first_payment.refresh_from_db()

    first_refund = Refund.objects.create(
        payment=first_payment,
        amount=Decimal("10.00"),
        currency=first_payment.currency,
        idempotency_key="refund-idempotency-1",
    )

    assert first_refund.idempotency_key == "refund-idempotency-1"

    second_order, _, _, _ = create_order_from_cart()
    second_payment = Payment.create_for_order(order=second_order)
    second_payment.capture(provider_reference="CAPTURE-2")
    second_payment.refresh_from_db()

    with pytest.raises((ValidationError, IntegrityError)):
        with transaction.atomic():
            Refund.objects.create(
                payment=second_payment,
                amount=Decimal("10.00"),
                currency=second_payment.currency,
                idempotency_key="refund-idempotency-1",
            )