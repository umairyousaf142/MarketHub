from decimal import Decimal
from unittest.mock import patch

import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.tests.factories import AdminUserFactory, CustomerUserFactory
from apps.cart.tests.factories import CartFactory, CartItemFactory
from apps.catalog.models import Product
from apps.catalog.tests.factories import ApprovedVendorFactory, ProductFactory
from apps.inventory.tests.factories import InventoryRecordFactory
from apps.orders.models import Order
from apps.payments.models import (
    Payment,
    PaymentTransaction,
    PaymentWebhookEvent,
    Refund,
)
from apps.payments.providers import create_manual_payment_for_order


pytestmark = pytest.mark.django_db


def api_client(user=None):
    client = APIClient()

    if user is not None:
        client.force_authenticate(user=user)

    return client


def get_results(response):
    data = response.data

    if isinstance(data, dict) and "results" in data:
        return data["results"]

    return data

def get_error_details(response):
    data = response.data

    if isinstance(data, dict) and "error" in data:
        return data["error"].get("details", {})

    return data


def assert_error_field(response, field_name):
    details = get_error_details(response)

    assert field_name in details


def create_active_product_with_inventory(
    *,
    vendor=None,
    name="API Payment Product",
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
    product_name="API Payment Product",
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


def test_unauthenticated_user_cannot_list_customer_payments():
    client = api_client()

    response = client.get(reverse("customer-payments-list"))

    assert response.status_code in [
        status.HTTP_401_UNAUTHORIZED,
        status.HTTP_403_FORBIDDEN,
    ]


def test_customer_lists_only_own_payments():
    customer = CustomerUserFactory()
    other_customer = CustomerUserFactory()

    own_payment, _, _, _, _ = create_pending_manual_payment(customer=customer)
    other_payment, _, _, _, _ = create_pending_manual_payment(customer=other_customer)

    client = api_client(customer)

    response = client.get(reverse("customer-payments-list"))

    assert response.status_code == status.HTTP_200_OK

    ids = {item["id"] for item in get_results(response)}

    assert str(own_payment.id) in ids
    assert str(other_payment.id) not in ids


def test_customer_payment_list_filters_by_status_provider_and_order():
    customer = CustomerUserFactory()

    pending_payment, _, _, _, _ = create_pending_manual_payment(customer=customer)
    failed_payment, failed_order, _, _, _ = create_pending_manual_payment(
        customer=customer,
    )
    failed_payment.mark_failed(reason="Gateway failed.")
    failed_payment.refresh_from_db()

    client = api_client(customer)

    response = client.get(
        reverse("customer-payments-list"),
        {
            "status": Payment.Status.FAILED,
            "provider": Payment.Provider.MANUAL,
            "order_id": str(failed_order.id),
        },
    )

    assert response.status_code == status.HTTP_200_OK

    ids = {item["id"] for item in get_results(response)}

    assert str(failed_payment.id) in ids
    assert str(pending_payment.id) not in ids


def test_customer_can_retrieve_own_payment():
    customer = CustomerUserFactory()
    payment, order, _, _, _ = create_pending_manual_payment(customer=customer)

    client = api_client(customer)

    response = client.get(
        reverse("customer-payments-detail", kwargs={"pk": str(payment.id)})
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.data["id"] == str(payment.id)
    assert str(response.data["order_id"]) == str(order.id)
    assert response.data["provider"] == Payment.Provider.MANUAL
    assert response.data["status"] == Payment.Status.PENDING


def test_customer_cannot_retrieve_other_customer_payment():
    customer = CustomerUserFactory()
    other_customer = CustomerUserFactory()

    other_payment, _, _, _, _ = create_pending_manual_payment(
        customer=other_customer,
    )

    client = api_client(customer)

    response = client.get(
        reverse("customer-payments-detail", kwargs={"pk": str(other_payment.id)})
    )

    assert response.status_code == status.HTTP_404_NOT_FOUND


def test_customer_creates_manual_payment_for_own_order():
    customer = CustomerUserFactory()
    order, _, _, _ = create_order_from_cart(customer=customer)

    client = api_client(customer)

    response = client.post(
        reverse("customer-payments-manual"),
        {
            "order_id": str(order.id),
        },
        format="json",
    )

    assert response.status_code == status.HTTP_201_CREATED
    assert str(response.data["order_id"]) == str(order.id)
    assert response.data["provider"] == Payment.Provider.MANUAL
    assert response.data["status"] == Payment.Status.PENDING

    payment = Payment.objects.get(id=response.data["id"])

    assert payment.order == order
    assert payment.transactions.filter(
        transaction_type=PaymentTransaction.TransactionType.INITIATED
    ).count() == 1


def test_customer_manual_payment_stores_metadata_and_idempotency_key():
    customer = CustomerUserFactory()
    order, _, _, _ = create_order_from_cart(customer=customer)

    client = api_client(customer)

    response = client.post(
        reverse("customer-payments-manual"),
        {
            "order_id": str(order.id),
            "idempotency_key": "customer-payment-key-1",
            "metadata": {
                "source": "api-test",
            },
        },
        format="json",
    )

    assert response.status_code == status.HTTP_201_CREATED

    payment = Payment.objects.get(id=response.data["id"])

    assert payment.idempotency_key == "customer-payment-key-1"
    assert payment.metadata == {"source": "api-test"}


def test_customer_cannot_create_payment_for_another_customer_order():
    customer = CustomerUserFactory()
    other_customer = CustomerUserFactory()

    other_order, _, _, _ = create_order_from_cart(customer=other_customer)

    client = api_client(customer)

    response = client.post(
        reverse("customer-payments-manual"),
        {
            "order_id": str(other_order.id),
        },
        format="json",
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert_error_field(response, "order_id")


def test_customer_cannot_create_duplicate_active_payment_for_same_order():
    customer = CustomerUserFactory()
    order, _, _, _ = create_order_from_cart(customer=customer)

    create_manual_payment_for_order(order=order)

    client = api_client(customer)

    response = client.post(
        reverse("customer-payments-manual"),
        {
            "order_id": str(order.id),
        },
        format="json",
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert_error_field(response, "order_id")


def test_customer_cannot_create_payment_for_cancelled_order():
    customer = CustomerUserFactory()
    order, _, _, _ = create_order_from_cart(customer=customer)

    order.cancel()
    order.refresh_from_db()

    client = api_client(customer)

    response = client.post(
        reverse("customer-payments-manual"),
        {
            "order_id": str(order.id),
        },
        format="json",
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert_error_field(response, "order_id")


def test_customer_cannot_create_payment_for_already_paid_order():
    customer = CustomerUserFactory()
    payment, order, _, _, _ = create_captured_manual_payment(customer=customer)

    client = api_client(customer)

    response = client.post(
        reverse("customer-payments-manual"),
        {
            "order_id": str(order.id),
        },
        format="json",
    )

    assert payment.status == Payment.Status.CAPTURED
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert_error_field(response, "order_id")


def test_admin_lists_all_payments():
    admin = AdminUserFactory()
    customer = CustomerUserFactory()
    other_customer = CustomerUserFactory()

    first_payment, _, _, _, _ = create_pending_manual_payment(customer=customer)
    second_payment, _, _, _, _ = create_pending_manual_payment(customer=other_customer)

    client = api_client(admin)

    response = client.get(reverse("admin-payments-list"))

    assert response.status_code == status.HTTP_200_OK

    ids = {item["id"] for item in get_results(response)}

    assert str(first_payment.id) in ids
    assert str(second_payment.id) in ids


def test_admin_payment_list_filters_by_status_and_customer_email():
    admin = AdminUserFactory()
    customer = CustomerUserFactory(email="pay-filter-1@example.com")
    other_customer = CustomerUserFactory(email="pay-filter-2@example.com")

    pending_payment, _, _, _, _ = create_pending_manual_payment(customer=customer)

    failed_payment, _, _, _, _ = create_pending_manual_payment(
        customer=other_customer,
    )
    failed_payment.mark_failed(reason="Card declined.")
    failed_payment.refresh_from_db()

    client = api_client(admin)

    response = client.get(
        reverse("admin-payments-list"),
        {
            "status": Payment.Status.FAILED,
            "customer_email": "pay-filter-2@example.com",
        },
    )

    assert response.status_code == status.HTTP_200_OK

    ids = {item["id"] for item in get_results(response)}

    assert str(failed_payment.id) in ids
    assert str(pending_payment.id) not in ids


def test_admin_can_retrieve_payment():
    admin = AdminUserFactory()
    payment, order, _, _, _ = create_pending_manual_payment()

    client = api_client(admin)

    response = client.get(
        reverse("admin-payments-detail", kwargs={"pk": str(payment.id)})
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.data["id"] == str(payment.id)
    assert str(response.data["order_id"]) == str(order.id)


def test_customer_cannot_access_admin_payment_list():
    customer = CustomerUserFactory()
    client = api_client(customer)

    response = client.get(reverse("admin-payments-list"))

    assert response.status_code == status.HTTP_403_FORBIDDEN


def test_admin_capture_payment_marks_paid_and_commits_inventory():
    admin = AdminUserFactory()

    order, _, inventory_record, _ = create_order_from_cart(
        quantity=3,
        quantity_on_hand=20,
    )
    payment = create_manual_payment_for_order(order=order)

    client = api_client(admin)

    with patch("apps.payments.views.send_order_paid_email_task.delay"), patch(
        "apps.payments.views.check_low_stock_after_order_task.delay"
    ):
        response = client.post(
            reverse("admin-payments-capture", kwargs={"pk": str(payment.id)}),
            {
                "provider_reference": "ADMIN-CAPTURE-1",
                "metadata": {
                    "source": "api-test",
                },
            },
            format="json",
        )

    assert response.status_code == status.HTTP_200_OK

    payment.refresh_from_db()
    order.refresh_from_db()
    inventory_record.refresh_from_db()

    assert payment.status == Payment.Status.CAPTURED
    assert payment.provider_payment_id == "ADMIN-CAPTURE-1"

    assert order.payment_status == Order.PaymentStatus.PAID
    assert order.status == Order.Status.CONFIRMED
    assert order.inventory_status == Order.InventoryStatus.COMMITTED

    assert inventory_record.quantity_on_hand == 17
    assert inventory_record.quantity_reserved == 0

    assert payment.transactions.filter(
        transaction_type=PaymentTransaction.TransactionType.CAPTURE
    ).count() == 1


def test_admin_capture_non_implemented_gateway_returns_400():
    admin = AdminUserFactory()
    order, _, _, _ = create_order_from_cart()

    payment = Payment.create_for_order(
        order=order,
        provider=Payment.Provider.STRIPE,
    )

    client = api_client(admin)

    response = client.post(
        reverse("admin-payments-capture", kwargs={"pk": str(payment.id)}),
        {},
        format="json",
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert_error_field(response, "provider")


def test_admin_fail_pending_payment_updates_statuses():
    admin = AdminUserFactory()
    payment, order, _, _, _ = create_pending_manual_payment()

    client = api_client(admin)

    response = client.post(
        reverse("admin-payments-fail", kwargs={"pk": str(payment.id)}),
        {
            "reason": "Card declined.",
            "provider_reference": "FAIL-1",
            "metadata": {
                "code": "card_declined",
            },
        },
        format="json",
    )

    assert response.status_code == status.HTTP_200_OK

    payment.refresh_from_db()
    order.refresh_from_db()

    assert payment.status == Payment.Status.FAILED
    assert payment.failure_reason == "Card declined."
    assert payment.provider_payment_id == "FAIL-1"
    assert order.payment_status == Order.PaymentStatus.FAILED

    assert payment.transactions.filter(
        transaction_type=PaymentTransaction.TransactionType.FAILURE,
        is_successful=False,
    ).count() == 1


def test_admin_cannot_fail_captured_payment():
    admin = AdminUserFactory()
    payment, _, _, _, _ = create_captured_manual_payment()

    client = api_client(admin)

    response = client.post(
        reverse("admin-payments-fail", kwargs={"pk": str(payment.id)}),
        {
            "reason": "Should not fail.",
        },
        format="json",
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST


def test_admin_cancel_pending_payment():
    admin = AdminUserFactory()
    payment, _, _, _, _ = create_pending_manual_payment()

    client = api_client(admin)

    response = client.post(
        reverse("admin-payments-cancel", kwargs={"pk": str(payment.id)}),
        {
            "reason": "Customer abandoned checkout.",
            "metadata": {
                "source": "api-test",
            },
        },
        format="json",
    )

    assert response.status_code == status.HTTP_200_OK

    payment.refresh_from_db()

    assert payment.status == Payment.Status.CANCELLED
    assert payment.failure_reason == "Customer abandoned checkout."

    assert payment.transactions.filter(
        transaction_type=PaymentTransaction.TransactionType.CANCELLATION,
        is_successful=True,
    ).count() == 1


def test_admin_cannot_cancel_captured_payment():
    admin = AdminUserFactory()
    payment, _, _, _, _ = create_captured_manual_payment()

    client = api_client(admin)

    response = client.post(
        reverse("admin-payments-cancel", kwargs={"pk": str(payment.id)}),
        {
            "reason": "Too late.",
        },
        format="json",
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST


def test_admin_partial_refund_payment():
    admin = AdminUserFactory()
    payment, order, _, _, _ = create_captured_manual_payment()

    client = api_client(admin)

    response = client.post(
        reverse("admin-payments-refund", kwargs={"pk": str(payment.id)}),
        {
            "amount": "40.00",
            "reason": "Partial refund.",
            "provider_reference": "REFUND-40",
            "idempotency_key": "refund-key-40",
            "metadata": {
                "source": "api-test",
            },
        },
        format="json",
    )

    assert response.status_code == status.HTTP_201_CREATED

    payment.refresh_from_db()
    order.refresh_from_db()

    refund = Refund.objects.get(
        payment=payment,
        provider_refund_id="REFUND-40",
    )

    assert refund.status == Refund.Status.SUCCEEDED
    assert refund.amount == Decimal("40.00")
    assert refund.idempotency_key == "refund-key-40"

    assert payment.status == Payment.Status.PARTIALLY_REFUNDED
    assert payment.refunded_amount == Decimal("40.00")
    assert order.payment_status == Order.PaymentStatus.PAID


def test_admin_full_refund_updates_order_payment_status():
    admin = AdminUserFactory()
    payment, order, _, _, _ = create_captured_manual_payment()
    payment.refresh_from_db()

    client = api_client(admin)

    response = client.post(
        reverse("admin-payments-refund", kwargs={"pk": str(payment.id)}),
        {
            "amount": str(payment.refundable_amount),
            "reason": "Full refund.",
            "provider_reference": "REFUND-FULL",
        },
        format="json",
    )

    assert response.status_code == status.HTTP_201_CREATED

    payment.refresh_from_db()
    order.refresh_from_db()

    assert payment.status == Payment.Status.REFUNDED
    assert payment.refundable_amount == Decimal("0.00")
    assert order.payment_status == Order.PaymentStatus.REFUNDED

    assert Refund.objects.filter(
        payment=payment,
        status=Refund.Status.SUCCEEDED,
    ).count() == 1


def test_admin_refund_more_than_refundable_amount_returns_400():
    admin = AdminUserFactory()
    payment, _, _, _, _ = create_captured_manual_payment()
    payment.refresh_from_db()

    client = api_client(admin)

    response = client.post(
        reverse("admin-payments-refund", kwargs={"pk": str(payment.id)}),
        {
            "amount": str(payment.refundable_amount + Decimal("1.00")),
            "reason": "Too much.",
        },
        format="json",
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST


def test_admin_refund_pending_payment_returns_400():
    admin = AdminUserFactory()
    payment, _, _, _, _ = create_pending_manual_payment()

    client = api_client(admin)

    response = client.post(
        reverse("admin-payments-refund", kwargs={"pk": str(payment.id)}),
        {
            "amount": "10.00",
            "reason": "Invalid refund.",
        },
        format="json",
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST


def test_customer_cannot_call_admin_refund_endpoint():
    customer = CustomerUserFactory()
    payment, _, _, _, _ = create_captured_manual_payment(customer=customer)

    client = api_client(customer)

    response = client.post(
        reverse("admin-payments-refund", kwargs={"pk": str(payment.id)}),
        {
            "amount": "10.00",
        },
        format="json",
    )

    assert response.status_code == status.HTTP_403_FORBIDDEN


def test_manual_webhook_creates_event():
    client = api_client()

    response = client.post(
        reverse("payment-webhook", kwargs={"provider": "manual"}),
        {
            "event_id": "evt_manual_1",
            "event_type": "manual.payment.created",
            "payment_id": "payment-test",
        },
        format="json",
    )

    assert response.status_code == status.HTTP_201_CREATED
    assert response.data["provider"] == Payment.Provider.MANUAL
    assert response.data["event_id"] == "evt_manual_1"
    assert response.data["event_type"] == "manual.payment.created"
    assert response.data["status"] == PaymentWebhookEvent.Status.RECEIVED

    assert PaymentWebhookEvent.objects.filter(
        provider=Payment.Provider.MANUAL,
        event_id="evt_manual_1",
    ).exists()


def test_duplicate_manual_webhook_is_ignored():
    client = api_client()

    url = reverse("payment-webhook", kwargs={"provider": "manual"})

    first_response = client.post(
        url,
        {
            "event_id": "evt_duplicate_1",
            "event_type": "manual.payment.created",
        },
        format="json",
    )

    second_response = client.post(
        url,
        {
            "event_id": "evt_duplicate_1",
            "event_type": "manual.payment.created",
        },
        format="json",
    )

    assert first_response.status_code == status.HTTP_201_CREATED
    assert second_response.status_code == status.HTTP_200_OK

    event = PaymentWebhookEvent.objects.get(
        provider=Payment.Provider.MANUAL,
        event_id="evt_duplicate_1",
    )

    assert event.status == PaymentWebhookEvent.Status.IGNORED
    assert event.error_message == "Duplicate webhook event."


def test_unsupported_webhook_provider_returns_400():
    client = api_client()

    response = client.post(
        reverse("payment-webhook", kwargs={"provider": "unknown"}),
        {
            "event_id": "evt_unknown_1",
        },
        format="json",
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert_error_field(response, "provider")


def test_placeholder_gateway_webhook_returns_400():
    client = api_client()

    response = client.post(
        reverse("payment-webhook", kwargs={"provider": "stripe"}),
        {
            "event_id": "evt_stripe_1",
            "event_type": "payment_intent.succeeded",
        },
        format="json",
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert_error_field(response, "provider")