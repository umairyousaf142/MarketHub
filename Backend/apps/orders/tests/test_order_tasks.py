from decimal import Decimal

import pytest
from django.core import mail
from django.test import override_settings
from django.urls import reverse
from rest_framework import status

import apps.orders.views as order_views

from apps.accounts.tests.factories import (
    AdminUserFactory,
    CustomerUserFactory,
)
from apps.cart.models import Cart
from apps.cart.tests.factories import CartFactory, CartItemFactory
from apps.catalog.models import Product
from apps.catalog.tests.factories import ApprovedVendorFactory, ProductFactory
from apps.inventory.tests.factories import InventoryRecordFactory
from apps.orders.models import Order, VendorOrder
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


pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture(autouse=True)
def configure_email_backend(settings):
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    settings.DEFAULT_FROM_EMAIL = "no-reply@markethub.test"
    settings.MARKETHUB_ADMIN_NOTIFICATION_EMAILS = ["admin@markethub.test"]

    if hasattr(mail, "outbox"):
        mail.outbox.clear()


class DelayRecorderTask:
    def __init__(self, name, calls):
        self.name = name
        self.calls = calls

    def delay(self, *args, **kwargs):
        self.calls.append(
            {
                "task": self.name,
                "args": args,
                "kwargs": kwargs,
            }
        )


def create_active_product_with_inventory(
    *,
    vendor=None,
    name="Task Order Product",
    base_price=Decimal("100.00"),
    quantity_on_hand=100,
    quantity_reserved=0,
    low_stock_threshold=5,
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
        low_stock_threshold=low_stock_threshold,
        track_inventory=track_inventory,
        allow_backorder=allow_backorder,
    )

    return product, inventory_record


def create_order_from_cart(
    *,
    customer=None,
    vendor=None,
    product_name="Task Order Product",
    base_price=Decimal("50.00"),
    quantity=2,
    quantity_on_hand=100,
    quantity_reserved=0,
    low_stock_threshold=5,
    mark_paid=False,
):
    customer = customer or CustomerUserFactory()
    cart = CartFactory(customer=customer)

    product, inventory_record = create_active_product_with_inventory(
        vendor=vendor,
        name=product_name,
        base_price=base_price,
        quantity_on_hand=quantity_on_hand,
        quantity_reserved=quantity_reserved,
        low_stock_threshold=low_stock_threshold,
    )

    CartItemFactory(
        cart=cart,
        product=product,
        quantity=quantity,
    )

    order = Order.create_from_cart(cart)

    if mark_paid:
        order.mark_paid()

    order.refresh_from_db()
    inventory_record.refresh_from_db()

    return order, product, inventory_record, cart


def test_send_order_confirmation_email_task_sends_email_to_customer():
    order, _, _, _ = create_order_from_cart(
        product_name="Confirmation Product",
    )

    result = send_order_confirmation_email_task.run(str(order.id))

    assert result["sent"] is True
    assert result["order_id"] == str(order.id)
    assert result["order_number"] == order.order_number
    assert result["recipient"] == order.customer.email

    assert len(mail.outbox) == 1
    assert order.order_number in mail.outbox[0].subject
    assert order.customer.email in mail.outbox[0].to
    assert "Confirmation Product" in mail.outbox[0].body


def test_notify_vendors_new_order_task_sends_email_to_vendor():
    vendor = ApprovedVendorFactory()

    order, _, _, _ = create_order_from_cart(
        vendor=vendor,
        product_name="Vendor Notification Product",
    )

    result = notify_vendors_new_order_task.run(str(order.id))

    assert result["order_id"] == str(order.id)
    assert result["order_number"] == order.order_number
    assert len(result["results"]) == 1
    assert result["results"][0]["sent"] is True
    assert result["results"][0]["recipient"] == vendor.user.email

    assert len(mail.outbox) == 1
    assert order.order_number in mail.outbox[0].subject
    assert vendor.user.email in mail.outbox[0].to
    assert "Vendor Notification Product" in mail.outbox[0].body


def test_notify_admin_new_order_task_sends_email_to_configured_admins():
    order, _, _, _ = create_order_from_cart()

    result = notify_admin_new_order_task.run(str(order.id))

    assert result["sent"] is True
    assert result["order_id"] == str(order.id)
    assert result["recipients"] == ["admin@markethub.test"]

    assert len(mail.outbox) == 1
    assert "admin@markethub.test" in mail.outbox[0].to
    assert order.order_number in mail.outbox[0].subject


@override_settings(
    MARKETHUB_ADMIN_NOTIFICATION_EMAILS=[],
    ADMINS=[],
)
def test_notify_admin_new_order_task_returns_false_when_no_admin_emails():
    order, _, _, _ = create_order_from_cart()

    result = notify_admin_new_order_task.run(str(order.id))

    assert result["sent"] is False
    assert result["reason"] == "No admin notification emails configured."
    assert result["order_id"] == str(order.id)
    assert len(getattr(mail, "outbox", [])) == 0


def test_send_order_paid_email_task_sends_email_to_customer():
    order, _, _, _ = create_order_from_cart(mark_paid=True)

    result = send_order_paid_email_task.run(str(order.id))

    assert result["sent"] is True
    assert result["recipient"] == order.customer.email

    assert len(mail.outbox) == 1
    assert order.order_number in mail.outbox[0].subject
    assert "payment has been confirmed" in mail.outbox[0].body.lower()


def test_send_order_cancelled_email_task_sends_email_to_customer():
    order, _, _, _ = create_order_from_cart()

    order.cancel()
    order.refresh_from_db()

    result = send_order_cancelled_email_task.run(str(order.id))

    assert result["sent"] is True
    assert result["recipient"] == order.customer.email

    assert len(mail.outbox) == 1
    assert order.order_number in mail.outbox[0].subject
    assert "cancelled" in mail.outbox[0].subject.lower()


def test_notify_vendors_order_cancelled_task_sends_email_to_vendor():
    vendor = ApprovedVendorFactory()

    order, _, _, _ = create_order_from_cart(vendor=vendor)

    order.cancel()
    order.refresh_from_db()

    result = notify_vendors_order_cancelled_task.run(str(order.id))

    assert result["order_id"] == str(order.id)
    assert len(result["results"]) == 1
    assert result["results"][0]["sent"] is True
    assert result["results"][0]["recipient"] == vendor.user.email

    assert len(mail.outbox) == 1
    assert vendor.user.email in mail.outbox[0].to
    assert order.order_number in mail.outbox[0].subject


def test_send_vendor_order_status_update_email_task_sends_email_to_customer():
    vendor = ApprovedVendorFactory()

    order, _, _, _ = create_order_from_cart(
        vendor=vendor,
        mark_paid=True,
    )

    vendor_order = order.vendor_orders.get(vendor=vendor)
    vendor_order.status = VendorOrder.Status.PROCESSING
    vendor_order.save(update_fields=["status", "updated_at"])

    result = send_vendor_order_status_update_email_task.run(str(vendor_order.id))

    assert result["sent"] is True
    assert result["vendor_order_id"] == str(vendor_order.id)
    assert result["recipient"] == order.customer.email

    assert len(mail.outbox) == 1
    assert order.customer.email in mail.outbox[0].to
    assert order.order_number in mail.outbox[0].subject
    assert vendor.store_name in mail.outbox[0].body


def test_check_low_stock_after_order_task_sends_alert_to_vendor_and_admin():
    vendor = ApprovedVendorFactory()

    order, _, inventory_record, _ = create_order_from_cart(
        vendor=vendor,
        product_name="Low Stock Product",
        quantity=4,
        quantity_on_hand=5,
        quantity_reserved=0,
        low_stock_threshold=2,
    )

    inventory_record.refresh_from_db()

    assert inventory_record.available_quantity == 1
    assert inventory_record.is_low_stock is True

    result = check_low_stock_after_order_task.run(str(order.id))

    assert result["order_id"] == str(order.id)
    assert len(result["alerts"]) == 1
    assert result["alerts"][0]["sent"] is True
    assert result["alerts"][0]["product"] == "Low Stock Product"

    assert len(mail.outbox) == 1
    assert vendor.user.email in mail.outbox[0].to
    assert "admin@markethub.test" in mail.outbox[0].to
    assert "Low Stock Product" in mail.outbox[0].subject


def test_check_low_stock_after_order_task_does_not_send_when_stock_is_not_low():
    order, _, inventory_record, _ = create_order_from_cart(
        quantity=2,
        quantity_on_hand=100,
        quantity_reserved=0,
        low_stock_threshold=5,
    )

    inventory_record.refresh_from_db()

    assert inventory_record.is_low_stock is False

    result = check_low_stock_after_order_task.run(str(order.id))

    assert result["order_id"] == str(order.id)
    assert result["alerts"] == []
    assert len(getattr(mail, "outbox", [])) == 0


def test_checkout_view_enqueues_order_background_tasks(api_client, monkeypatch):
    customer = CustomerUserFactory()

    cart = CartFactory(customer=customer)

    product, _ = create_active_product_with_inventory(
        name="Checkout Hook Product",
        quantity_on_hand=20,
    )

    CartItemFactory(
        cart=cart,
        product=product,
        quantity=2,
    )

    calls = []

    monkeypatch.setattr(
        order_views,
        "send_order_confirmation_email_task",
        DelayRecorderTask("order-confirmation", calls),
    )
    monkeypatch.setattr(
        order_views,
        "notify_vendors_new_order_task",
        DelayRecorderTask("vendor-new-order", calls),
    )
    monkeypatch.setattr(
        order_views,
        "notify_admin_new_order_task",
        DelayRecorderTask("admin-new-order", calls),
    )
    monkeypatch.setattr(
        order_views,
        "check_low_stock_after_order_task",
        DelayRecorderTask("low-stock", calls),
    )

    api_client.force_authenticate(user=customer)

    url = reverse("customer-orders-checkout")

    response = api_client.post(
        url,
        {
            "shipping_address": {"city": "Lahore"},
            "billing_address": {"city": "Lahore"},
        },
        format="json",
    )

    assert response.status_code == status.HTTP_201_CREATED

    order_id = response.data["id"]

    assert calls == [
        {
            "task": "order-confirmation",
            "args": (order_id,),
            "kwargs": {},
        },
        {
            "task": "vendor-new-order",
            "args": (order_id,),
            "kwargs": {},
        },
        {
            "task": "admin-new-order",
            "args": (order_id,),
            "kwargs": {},
        },
        {
            "task": "low-stock",
            "args": (order_id,),
            "kwargs": {},
        },
    ]


def test_customer_cancel_view_enqueues_cancel_background_tasks(api_client, monkeypatch):
    customer = CustomerUserFactory()

    order, _, _, _ = create_order_from_cart(customer=customer)

    calls = []

    monkeypatch.setattr(
        order_views,
        "send_order_cancelled_email_task",
        DelayRecorderTask("order-cancelled", calls),
    )
    monkeypatch.setattr(
        order_views,
        "notify_vendors_order_cancelled_task",
        DelayRecorderTask("vendors-cancelled", calls),
    )

    api_client.force_authenticate(user=customer)

    url = reverse(
        "customer-orders-cancel",
        kwargs={"pk": order.id},
    )

    response = api_client.post(url)

    assert response.status_code == status.HTTP_200_OK

    assert calls == [
        {
            "task": "order-cancelled",
            "args": (str(order.id),),
            "kwargs": {},
        },
        {
            "task": "vendors-cancelled",
            "args": (str(order.id),),
            "kwargs": {},
        },
    ]


def test_admin_mark_paid_view_enqueues_paid_and_low_stock_tasks(api_client, monkeypatch):
    admin = AdminUserFactory()

    order, _, _, _ = create_order_from_cart()

    calls = []

    monkeypatch.setattr(
        order_views,
        "send_order_paid_email_task",
        DelayRecorderTask("order-paid", calls),
    )
    monkeypatch.setattr(
        order_views,
        "check_low_stock_after_order_task",
        DelayRecorderTask("low-stock", calls),
    )

    api_client.force_authenticate(user=admin)

    url = reverse(
        "admin-orders-mark-paid",
        kwargs={"pk": order.id},
    )

    response = api_client.post(url)

    assert response.status_code == status.HTTP_200_OK

    assert calls == [
        {
            "task": "order-paid",
            "args": (str(order.id),),
            "kwargs": {},
        },
        {
            "task": "low-stock",
            "args": (str(order.id),),
            "kwargs": {},
        },
    ]


def test_admin_cancel_view_enqueues_cancel_background_tasks(api_client, monkeypatch):
    admin = AdminUserFactory()

    order, _, _, _ = create_order_from_cart()

    calls = []

    monkeypatch.setattr(
        order_views,
        "send_order_cancelled_email_task",
        DelayRecorderTask("order-cancelled", calls),
    )
    monkeypatch.setattr(
        order_views,
        "notify_vendors_order_cancelled_task",
        DelayRecorderTask("vendors-cancelled", calls),
    )

    api_client.force_authenticate(user=admin)

    url = reverse(
        "admin-orders-cancel",
        kwargs={"pk": order.id},
    )

    response = api_client.post(url)

    assert response.status_code == status.HTTP_200_OK

    assert calls == [
        {
            "task": "order-cancelled",
            "args": (str(order.id),),
            "kwargs": {},
        },
        {
            "task": "vendors-cancelled",
            "args": (str(order.id),),
            "kwargs": {},
        },
    ]


def test_vendor_status_update_view_enqueues_status_update_email_task(
    api_client,
    monkeypatch,
):
    vendor = ApprovedVendorFactory()

    order, _, _, _ = create_order_from_cart(
        vendor=vendor,
        mark_paid=True,
    )

    vendor_order = order.vendor_orders.get(vendor=vendor)

    calls = []

    monkeypatch.setattr(
        order_views,
        "send_vendor_order_status_update_email_task",
        DelayRecorderTask("vendor-status-update", calls),
    )

    api_client.force_authenticate(user=vendor.user)

    url = reverse(
        "vendor-orders-mark-processing",
        kwargs={"pk": vendor_order.id},
    )

    response = api_client.post(url)

    assert response.status_code == status.HTTP_200_OK

    assert calls == [
        {
            "task": "vendor-status-update",
            "args": (str(vendor_order.id),),
            "kwargs": {},
        },
    ]