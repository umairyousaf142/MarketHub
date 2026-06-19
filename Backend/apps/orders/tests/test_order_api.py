from decimal import Decimal

import pytest
from django.urls import reverse
from rest_framework import status

from apps.accounts.tests.factories import (
    AdminUserFactory,
    CustomerUserFactory,
    VendorUserFactory,
)
from apps.cart.models import Cart
from apps.cart.tests.factories import CartFactory, CartItemFactory
from apps.catalog.models import Product
from apps.catalog.tests.factories import ApprovedVendorFactory, ProductFactory
from apps.inventory.tests.factories import InventoryRecordFactory
from apps.orders.models import Order, OrderItem, VendorOrder


pytestmark = pytest.mark.django_db


def get_results(response):
    if isinstance(response.data, dict) and "results" in response.data:
        return response.data["results"]

    return response.data


def get_error_details(response):
    if isinstance(response.data, dict) and "error" in response.data:
        return response.data["error"].get("details", {})

    return response.data


def create_active_product_with_inventory(
    *,
    vendor=None,
    name="Order API Product",
    base_price=Decimal("100.00"),
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


def create_cart_with_item(
    *,
    customer=None,
    vendor=None,
    product_name="Order API Product",
    base_price=Decimal("50.00"),
    quantity=2,
    quantity_on_hand=100,
    quantity_reserved=0,
):
    customer = customer or CustomerUserFactory()
    cart = CartFactory(customer=customer)

    product, inventory_record = create_active_product_with_inventory(
        vendor=vendor,
        name=product_name,
        base_price=base_price,
        quantity_on_hand=quantity_on_hand,
        quantity_reserved=quantity_reserved,
    )

    CartItemFactory(
        cart=cart,
        product=product,
        quantity=quantity,
    )

    return cart, product, inventory_record


def create_order_from_cart(
    *,
    customer=None,
    vendor=None,
    product_name="Order API Product",
    base_price=Decimal("50.00"),
    quantity=2,
    quantity_on_hand=100,
    mark_paid=False,
):
    cart, product, inventory_record = create_cart_with_item(
        customer=customer,
        vendor=vendor,
        product_name=product_name,
        base_price=base_price,
        quantity=quantity,
        quantity_on_hand=quantity_on_hand,
    )

    order = Order.create_from_cart(cart)

    if mark_paid:
        order.mark_paid()

    order.refresh_from_db()
    inventory_record.refresh_from_db()

    return order, product, inventory_record, cart


def test_customer_orders_requires_authentication(api_client):
    url = reverse("customer-orders-list")

    response = api_client.get(url)

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_vendor_cannot_access_customer_orders(api_client):
    vendor_user = VendorUserFactory()
    api_client.force_authenticate(user=vendor_user)

    url = reverse("customer-orders-list")

    response = api_client.get(url)

    assert response.status_code == status.HTTP_403_FORBIDDEN


def test_customer_checkout_requires_active_cart(api_client):
    customer = CustomerUserFactory()
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

    assert response.status_code == status.HTTP_400_BAD_REQUEST

    details = get_error_details(response)

    assert "cart" in details


def test_customer_checkout_rejects_empty_cart(api_client):
    customer = CustomerUserFactory()
    CartFactory(customer=customer)

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

    assert response.status_code == status.HTTP_400_BAD_REQUEST

    details = get_error_details(response)

    assert "cart" in details


def test_customer_checkout_creates_order_reserves_inventory_and_converts_cart(api_client):
    customer = CustomerUserFactory()

    cart, product, inventory_record = create_cart_with_item(
        customer=customer,
        product_name="Checkout Product",
        base_price=Decimal("50.00"),
        quantity=2,
        quantity_on_hand=20,
    )

    api_client.force_authenticate(user=customer)

    url = reverse("customer-orders-checkout")

    response = api_client.post(
        url,
        {
            "shipping_address": {
                "city": "Lahore",
                "address": "Test address",
            },
            "billing_address": {
                "city": "Lahore",
                "address": "Test address",
            },
            "shipping_amount": "10.00",
            "tax_amount": "5.00",
            "discount_amount": "0.00",
            "notes": "Test checkout",
        },
        format="json",
    )

    assert response.status_code == status.HTTP_201_CREATED
    assert response.data["customer_id"] == str(customer.id)
    assert response.data["source_cart_id"] == str(cart.id)
    assert response.data["subtotal_amount"] == "100.00"
    assert response.data["shipping_amount"] == "10.00"
    assert response.data["tax_amount"] == "5.00"
    assert response.data["total_amount"] == "115.00"
    assert response.data["inventory_status"] == Order.InventoryStatus.RESERVED
    assert len(response.data["items"]) == 1
    assert len(response.data["vendor_orders"]) == 1

    order = Order.objects.get(id=response.data["id"])

    assert order.items.count() == 1
    assert order.vendor_orders.count() == 1

    cart.refresh_from_db()
    inventory_record.refresh_from_db()

    assert cart.status == Cart.Status.CONVERTED
    assert inventory_record.quantity_reserved == 2
    assert inventory_record.quantity_on_hand == 20


def test_customer_order_list_only_returns_own_orders(api_client):
    own_customer = CustomerUserFactory()
    other_customer = CustomerUserFactory()

    own_order, _, _, _ = create_order_from_cart(
        customer=own_customer,
        product_name="Own Order Product",
    )
    create_order_from_cart(
        customer=other_customer,
        product_name="Other Order Product",
    )

    api_client.force_authenticate(user=own_customer)

    url = reverse("customer-orders-list")

    response = api_client.get(url)

    assert response.status_code == status.HTTP_200_OK

    results = get_results(response)

    assert len(results) == 1
    assert results[0]["id"] == str(own_order.id)


def test_customer_can_retrieve_own_order(api_client):
    customer = CustomerUserFactory()

    order, _, _, _ = create_order_from_cart(customer=customer)

    api_client.force_authenticate(user=customer)

    url = reverse(
        "customer-orders-detail",
        kwargs={"pk": order.id},
    )

    response = api_client.get(url)

    assert response.status_code == status.HTTP_200_OK
    assert response.data["id"] == str(order.id)
    assert response.data["customer_id"] == str(customer.id)


def test_customer_cannot_retrieve_other_customer_order(api_client):
    own_customer = CustomerUserFactory()
    other_customer = CustomerUserFactory()

    other_order, _, _, _ = create_order_from_cart(customer=other_customer)

    api_client.force_authenticate(user=own_customer)

    url = reverse(
        "customer-orders-detail",
        kwargs={"pk": other_order.id},
    )

    response = api_client.get(url)

    assert response.status_code == status.HTTP_404_NOT_FOUND


def test_customer_can_cancel_pending_unpaid_order(api_client):
    customer = CustomerUserFactory()

    order, _, inventory_record, _ = create_order_from_cart(
        customer=customer,
        quantity=3,
        quantity_on_hand=20,
    )

    api_client.force_authenticate(user=customer)

    url = reverse(
        "customer-orders-cancel",
        kwargs={"pk": order.id},
    )

    response = api_client.post(url)

    assert response.status_code == status.HTTP_200_OK
    assert response.data["status"] == Order.Status.CANCELLED
    assert response.data["inventory_status"] == Order.InventoryStatus.RELEASED

    order.refresh_from_db()
    inventory_record.refresh_from_db()

    assert order.status == Order.Status.CANCELLED
    assert inventory_record.quantity_reserved == 0
    assert inventory_record.quantity_on_hand == 20


def test_customer_cannot_cancel_paid_order(api_client):
    customer = CustomerUserFactory()

    order, _, _, _ = create_order_from_cart(
        customer=customer,
        mark_paid=True,
    )

    api_client.force_authenticate(user=customer)

    url = reverse(
        "customer-orders-cancel",
        kwargs={"pk": order.id},
    )

    response = api_client.post(url)

    assert response.status_code == status.HTTP_400_BAD_REQUEST


def test_admin_can_list_orders(api_client):
    admin = AdminUserFactory()
    order, _, _, _ = create_order_from_cart()

    api_client.force_authenticate(user=admin)

    url = reverse("admin-orders-list")

    response = api_client.get(url)

    assert response.status_code == status.HTTP_200_OK

    results = get_results(response)

    assert len(results) == 1
    assert results[0]["id"] == str(order.id)


def test_non_admin_cannot_list_admin_orders(api_client):
    customer = CustomerUserFactory()
    api_client.force_authenticate(user=customer)

    url = reverse("admin-orders-list")

    response = api_client.get(url)

    assert response.status_code == status.HTTP_403_FORBIDDEN


def test_admin_can_filter_orders_by_status(api_client):
    admin = AdminUserFactory()

    pending_order, _, _, _ = create_order_from_cart(
        product_name="Pending Filter Product",
    )
    paid_order, _, _, _ = create_order_from_cart(
        product_name="Paid Filter Product",
        mark_paid=True,
    )

    api_client.force_authenticate(user=admin)

    url = reverse("admin-orders-list")

    response = api_client.get(
        url,
        {
            "status": Order.Status.PENDING,
        },
    )

    assert response.status_code == status.HTTP_200_OK

    results = get_results(response)

    assert len(results) == 1
    assert results[0]["id"] == str(pending_order.id)
    assert results[0]["id"] != str(paid_order.id)


def test_admin_can_filter_orders_by_customer(api_client):
    admin = AdminUserFactory()

    customer = CustomerUserFactory()
    other_customer = CustomerUserFactory()

    matching_order, _, _, _ = create_order_from_cart(customer=customer)
    create_order_from_cart(customer=other_customer)

    api_client.force_authenticate(user=admin)

    url = reverse("admin-orders-list")

    response = api_client.get(
        url,
        {
            "customer": str(customer.id),
        },
    )

    assert response.status_code == status.HTTP_200_OK

    results = get_results(response)

    assert len(results) == 1
    assert results[0]["id"] == str(matching_order.id)
    assert results[0]["customer_id"] == str(customer.id)


def test_admin_can_retrieve_order(api_client):
    admin = AdminUserFactory()
    order, _, _, _ = create_order_from_cart()

    api_client.force_authenticate(user=admin)

    url = reverse(
        "admin-orders-detail",
        kwargs={"pk": order.id},
    )

    response = api_client.get(url)

    assert response.status_code == status.HTTP_200_OK
    assert response.data["id"] == str(order.id)


def test_admin_can_mark_order_paid_and_commit_inventory(api_client):
    admin = AdminUserFactory()

    order, _, inventory_record, _ = create_order_from_cart(
        quantity=3,
        quantity_on_hand=20,
    )

    api_client.force_authenticate(user=admin)

    url = reverse(
        "admin-orders-mark-paid",
        kwargs={"pk": order.id},
    )

    response = api_client.post(url)

    assert response.status_code == status.HTTP_200_OK
    assert response.data["payment_status"] == Order.PaymentStatus.PAID
    assert response.data["status"] == Order.Status.CONFIRMED
    assert response.data["inventory_status"] == Order.InventoryStatus.COMMITTED

    order.refresh_from_db()
    inventory_record.refresh_from_db()

    vendor_order = order.vendor_orders.first()

    assert order.payment_status == Order.PaymentStatus.PAID
    assert inventory_record.quantity_on_hand == 17
    assert inventory_record.quantity_reserved == 0
    assert vendor_order.status == VendorOrder.Status.CONFIRMED


def test_admin_mark_paid_rejects_cancelled_order(api_client):
    admin = AdminUserFactory()

    order, _, _, _ = create_order_from_cart()
    order.cancel()

    api_client.force_authenticate(user=admin)

    url = reverse(
        "admin-orders-mark-paid",
        kwargs={"pk": order.id},
    )

    response = api_client.post(url)

    assert response.status_code == status.HTTP_400_BAD_REQUEST


def test_admin_mark_paid_rejects_already_paid_order(api_client):
    admin = AdminUserFactory()

    order, _, _, _ = create_order_from_cart(mark_paid=True)

    api_client.force_authenticate(user=admin)

    url = reverse(
        "admin-orders-mark-paid",
        kwargs={"pk": order.id},
    )

    response = api_client.post(url)

    assert response.status_code == status.HTTP_400_BAD_REQUEST


def test_admin_can_cancel_order_and_release_inventory(api_client):
    admin = AdminUserFactory()

    order, _, inventory_record, _ = create_order_from_cart(
        quantity=4,
        quantity_on_hand=20,
    )

    api_client.force_authenticate(user=admin)

    url = reverse(
        "admin-orders-cancel",
        kwargs={"pk": order.id},
    )

    response = api_client.post(url)

    assert response.status_code == status.HTTP_200_OK
    assert response.data["status"] == Order.Status.CANCELLED
    assert response.data["inventory_status"] == Order.InventoryStatus.RELEASED

    inventory_record.refresh_from_db()

    assert inventory_record.quantity_reserved == 0
    assert inventory_record.quantity_on_hand == 20


def test_admin_cancel_rejects_delivered_order(api_client):
    admin = AdminUserFactory()

    order, _, _, _ = create_order_from_cart(mark_paid=True)
    order.status = Order.Status.DELIVERED
    order.save(update_fields=["status", "updated_at"])

    api_client.force_authenticate(user=admin)

    url = reverse(
        "admin-orders-cancel",
        kwargs={"pk": order.id},
    )

    response = api_client.post(url)

    assert response.status_code == status.HTTP_400_BAD_REQUEST


def test_admin_can_commit_inventory(api_client):
    admin = AdminUserFactory()

    order, _, inventory_record, _ = create_order_from_cart(
        quantity=5,
        quantity_on_hand=20,
    )

    api_client.force_authenticate(user=admin)

    url = reverse(
        "admin-orders-commit-inventory",
        kwargs={"pk": order.id},
    )

    response = api_client.post(url)

    assert response.status_code == status.HTTP_200_OK
    assert response.data["inventory_status"] == Order.InventoryStatus.COMMITTED

    inventory_record.refresh_from_db()

    assert inventory_record.quantity_on_hand == 15
    assert inventory_record.quantity_reserved == 0


def test_admin_can_release_inventory(api_client):
    admin = AdminUserFactory()

    order, _, inventory_record, _ = create_order_from_cart(
        quantity=5,
        quantity_on_hand=20,
    )

    api_client.force_authenticate(user=admin)

    url = reverse(
        "admin-orders-release-inventory",
        kwargs={"pk": order.id},
    )

    response = api_client.post(url)

    assert response.status_code == status.HTTP_200_OK
    assert response.data["inventory_status"] == Order.InventoryStatus.RELEASED

    inventory_record.refresh_from_db()

    assert inventory_record.quantity_on_hand == 20
    assert inventory_record.quantity_reserved == 0


def test_admin_can_list_vendor_orders_with_filters(api_client):
    admin = AdminUserFactory()

    vendor = ApprovedVendorFactory()
    other_vendor = ApprovedVendorFactory()

    matching_order, _, _, _ = create_order_from_cart(vendor=vendor)
    create_order_from_cart(vendor=other_vendor)

    matching_vendor_order = matching_order.vendor_orders.get(vendor=vendor)

    api_client.force_authenticate(user=admin)

    url = reverse("admin-vendor-orders-list")

    response = api_client.get(
        url,
        {
            "vendor": str(vendor.id),
            "status": VendorOrder.Status.PENDING,
            "order": str(matching_order.id),
        },
    )

    assert response.status_code == status.HTTP_200_OK

    results = get_results(response)

    assert len(results) == 1
    assert results[0]["id"] == str(matching_vendor_order.id)
    assert results[0]["vendor_id"] == str(vendor.id)


def test_admin_can_retrieve_vendor_order(api_client):
    admin = AdminUserFactory()

    order, _, _, _ = create_order_from_cart()
    vendor_order = order.vendor_orders.first()

    api_client.force_authenticate(user=admin)

    url = reverse(
        "admin-vendor-orders-detail",
        kwargs={"pk": vendor_order.id},
    )

    response = api_client.get(url)

    assert response.status_code == status.HTTP_200_OK
    assert response.data["id"] == str(vendor_order.id)


def test_admin_can_list_order_items_with_filters(api_client):
    admin = AdminUserFactory()

    order, product, _, _ = create_order_from_cart()
    item = order.items.first()

    api_client.force_authenticate(user=admin)

    url = reverse("admin-order-items-list")

    response = api_client.get(
        url,
        {
            "order": str(order.id),
            "vendor": str(product.vendor.id),
            "product": str(product.id),
            "customer": str(order.customer.id),
        },
    )

    assert response.status_code == status.HTTP_200_OK

    results = get_results(response)

    assert len(results) == 1
    assert results[0]["id"] == str(item.id)


def test_admin_can_retrieve_order_item(api_client):
    admin = AdminUserFactory()

    order, _, _, _ = create_order_from_cart()
    item = order.items.first()

    api_client.force_authenticate(user=admin)

    url = reverse(
        "admin-order-items-detail",
        kwargs={"pk": item.id},
    )

    response = api_client.get(url)

    assert response.status_code == status.HTTP_200_OK
    assert response.data["id"] == str(item.id)


def test_non_admin_cannot_list_admin_vendor_orders(api_client):
    customer = CustomerUserFactory()
    api_client.force_authenticate(user=customer)

    url = reverse("admin-vendor-orders-list")

    response = api_client.get(url)

    assert response.status_code == status.HTTP_403_FORBIDDEN


def test_non_admin_cannot_list_admin_order_items(api_client):
    vendor_user = VendorUserFactory()
    api_client.force_authenticate(user=vendor_user)

    url = reverse("admin-order-items-list")

    response = api_client.get(url)

    assert response.status_code == status.HTTP_403_FORBIDDEN


def test_vendor_orders_requires_authentication(api_client):
    url = reverse("vendor-orders-list")

    response = api_client.get(url)

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_customer_cannot_access_vendor_orders(api_client):
    customer = CustomerUserFactory()
    api_client.force_authenticate(user=customer)

    url = reverse("vendor-orders-list")

    response = api_client.get(url)

    assert response.status_code == status.HTTP_403_FORBIDDEN


def test_pending_vendor_cannot_access_vendor_orders(api_client):
    vendor = ApprovedVendorFactory()
    vendor.status = "PENDING"
    vendor.save(update_fields=["status"])

    api_client.force_authenticate(user=vendor.user)

    url = reverse("vendor-orders-list")

    response = api_client.get(url)

    assert response.status_code == status.HTTP_403_FORBIDDEN


def test_vendor_can_list_only_own_vendor_orders(api_client):
    own_vendor = ApprovedVendorFactory()
    other_vendor = ApprovedVendorFactory()

    own_order, _, _, _ = create_order_from_cart(
        vendor=own_vendor,
        product_name="Own Vendor Order Product",
    )
    create_order_from_cart(
        vendor=other_vendor,
        product_name="Other Vendor Order Product",
    )

    own_vendor_order = own_order.vendor_orders.get(vendor=own_vendor)

    api_client.force_authenticate(user=own_vendor.user)

    url = reverse("vendor-orders-list")

    response = api_client.get(url)

    assert response.status_code == status.HTTP_200_OK

    results = get_results(response)

    assert len(results) == 1
    assert results[0]["id"] == str(own_vendor_order.id)
    assert results[0]["vendor_id"] == str(own_vendor.id)


def test_vendor_can_retrieve_own_vendor_order(api_client):
    vendor = ApprovedVendorFactory()

    order, _, _, _ = create_order_from_cart(vendor=vendor)
    vendor_order = order.vendor_orders.get(vendor=vendor)

    api_client.force_authenticate(user=vendor.user)

    url = reverse(
        "vendor-orders-detail",
        kwargs={"pk": vendor_order.id},
    )

    response = api_client.get(url)

    assert response.status_code == status.HTTP_200_OK
    assert response.data["id"] == str(vendor_order.id)
    assert response.data["vendor_id"] == str(vendor.id)


def test_vendor_cannot_retrieve_other_vendor_order(api_client):
    own_vendor = ApprovedVendorFactory()
    other_vendor = ApprovedVendorFactory()

    order, _, _, _ = create_order_from_cart(vendor=other_vendor)
    other_vendor_order = order.vendor_orders.get(vendor=other_vendor)

    api_client.force_authenticate(user=own_vendor.user)

    url = reverse(
        "vendor-orders-detail",
        kwargs={"pk": other_vendor_order.id},
    )

    response = api_client.get(url)

    assert response.status_code == status.HTTP_404_NOT_FOUND


def test_vendor_can_mark_confirmed_order_processing(api_client):
    vendor = ApprovedVendorFactory()

    order, _, _, _ = create_order_from_cart(
        vendor=vendor,
        mark_paid=True,
    )
    vendor_order = order.vendor_orders.get(vendor=vendor)

    api_client.force_authenticate(user=vendor.user)

    url = reverse(
        "vendor-orders-mark-processing",
        kwargs={"pk": vendor_order.id},
    )

    response = api_client.post(url)

    assert response.status_code == status.HTTP_200_OK
    assert response.data["status"] == VendorOrder.Status.PROCESSING

    order.refresh_from_db()

    assert order.status == Order.Status.PROCESSING


def test_vendor_invalid_status_transition_returns_400(api_client):
    vendor = ApprovedVendorFactory()

    order, _, _, _ = create_order_from_cart(vendor=vendor)
    vendor_order = order.vendor_orders.get(vendor=vendor)

    api_client.force_authenticate(user=vendor.user)

    url = reverse(
        "vendor-orders-mark-processing",
        kwargs={"pk": vendor_order.id},
    )

    response = api_client.post(url)

    assert response.status_code == status.HTTP_400_BAD_REQUEST


def test_vendor_can_mark_processing_order_shipped(api_client):
    vendor = ApprovedVendorFactory()

    order, _, _, _ = create_order_from_cart(
        vendor=vendor,
        mark_paid=True,
    )
    vendor_order = order.vendor_orders.get(vendor=vendor)
    vendor_order.status = VendorOrder.Status.PROCESSING
    vendor_order.save(update_fields=["status", "updated_at"])

    api_client.force_authenticate(user=vendor.user)

    url = reverse(
        "vendor-orders-mark-shipped",
        kwargs={"pk": vendor_order.id},
    )

    response = api_client.post(url)

    assert response.status_code == status.HTTP_200_OK
    assert response.data["status"] == VendorOrder.Status.SHIPPED

    order.refresh_from_db()

    assert order.status == Order.Status.SHIPPED


def test_vendor_can_mark_shipped_order_delivered(api_client):
    vendor = ApprovedVendorFactory()

    order, _, _, _ = create_order_from_cart(
        vendor=vendor,
        mark_paid=True,
    )
    vendor_order = order.vendor_orders.get(vendor=vendor)
    vendor_order.status = VendorOrder.Status.SHIPPED
    vendor_order.save(update_fields=["status", "updated_at"])

    api_client.force_authenticate(user=vendor.user)

    url = reverse(
        "vendor-orders-mark-delivered",
        kwargs={"pk": vendor_order.id},
    )

    response = api_client.post(url)

    assert response.status_code == status.HTTP_200_OK
    assert response.data["status"] == VendorOrder.Status.DELIVERED

    order.refresh_from_db()

    assert order.status == Order.Status.DELIVERED


def test_orders_schema_contains_orders_endpoints(api_client):
    url = reverse("schema")

    response = api_client.get(url)

    assert response.status_code == status.HTTP_200_OK

    content = response.content.decode()

    assert "/api/v1/orders/my-orders/" in content
    assert "/api/v1/orders/my-orders/checkout/" in content
    assert "/api/v1/orders/my-orders/{id}/cancel/" in content

    assert "/api/v1/orders/vendor/orders/" in content
    assert "/api/v1/orders/vendor/orders/{id}/mark-processing/" in content
    assert "/api/v1/orders/vendor/orders/{id}/mark-shipped/" in content
    assert "/api/v1/orders/vendor/orders/{id}/mark-delivered/" in content

    assert "/api/v1/orders/admin/orders/" in content
    assert "/api/v1/orders/admin/orders/{id}/mark-paid/" in content
    assert "/api/v1/orders/admin/orders/{id}/cancel/" in content
    assert "/api/v1/orders/admin/orders/{id}/commit-inventory/" in content
    assert "/api/v1/orders/admin/orders/{id}/release-inventory/" in content

    assert "/api/v1/orders/admin/vendor-orders/" in content
    assert "/api/v1/orders/admin/items/" in content