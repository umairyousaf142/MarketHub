from datetime import timedelta
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.tests.factories import AdminUserFactory, CustomerUserFactory
from apps.cart.tests.factories import CartFactory, CartItemFactory
from apps.catalog.models import Product
from apps.catalog.tests.factories import (
    ApprovedVendorFactory,
    CategoryFactory,
    ProductFactory,
)
from apps.coupons.models import Coupon, CouponUsage
from apps.coupons.tests.factories import CouponFactory
from apps.inventory.tests.factories import InventoryRecordFactory
from apps.orders.models import Order


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
    category=None,
    name="Coupon API Product",
    base_price=Decimal("50.00"),
    quantity_on_hand=100,
    quantity_reserved=0,
    track_inventory=True,
    allow_backorder=False,
    **overrides,
):
    product = ProductFactory(
        vendor=vendor or ApprovedVendorFactory(),
        category=category or CategoryFactory(),
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
    category=None,
    product_name="Coupon API Product",
    base_price=Decimal("50.00"),
    quantity=2,
    quantity_on_hand=100,
):
    customer = customer or CustomerUserFactory()
    cart = CartFactory(customer=customer)

    product, inventory_record = create_active_product_with_inventory(
        vendor=vendor,
        category=category,
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


def coupon_payload(**overrides):
    now = timezone.now()

    payload = {
        "code": "API10",
        "type": Coupon.Type.FIXED,
        "value": "10.00",
        "max_discount": None,
        "scope": Coupon.Scope.GLOBAL,
        "vendor": None,
        "category": None,
        "min_order_value": "0.00",
        "usage_limit": None,
        "per_user_limit": 1,
        "valid_from": (now - timedelta(days=1)).isoformat(),
        "valid_until": (now + timedelta(days=30)).isoformat(),
        "is_active": True,
    }

    payload.update(overrides)

    return payload


def test_unauthenticated_user_cannot_validate_coupon():
    client = api_client()

    response = client.post(
        reverse("customer-coupons-validate-coupon"),
        {
            "code": "ANY",
            "order_id": "00000000-0000-0000-0000-000000000000",
        },
        format="json",
    )

    assert response.status_code in [
        status.HTTP_401_UNAUTHORIZED,
        status.HTTP_403_FORBIDDEN,
    ]


def test_customer_validates_global_fixed_coupon_for_own_order():
    customer = CustomerUserFactory()
    order, _, _, _ = create_order_from_cart(customer=customer)

    coupon = CouponFactory(
        code="SAVE10",
        type=Coupon.Type.FIXED,
        value=Decimal("10.00"),
    )

    client = api_client(customer)

    response = client.post(
        reverse("customer-coupons-validate-coupon"),
        {
            "code": "save10",
            "order_id": str(order.id),
        },
        format="json",
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.data["valid"] is True
    assert str(response.data["coupon_id"]) == str(coupon.id)
    assert response.data["code"] == "SAVE10"
    assert response.data["type"] == Coupon.Type.FIXED
    assert response.data["scope"] == Coupon.Scope.GLOBAL
    assert str(response.data["order_id"]) == str(order.id)
    assert str(response.data["discount_amount"]) == "10.00"


def test_customer_validates_percentage_coupon_with_max_discount():
    customer = CustomerUserFactory()
    order, _, _, _ = create_order_from_cart(
        customer=customer,
        base_price=Decimal("100.00"),
        quantity=2,
    )

    coupon = CouponFactory(
        code="PERCENT50",
        type=Coupon.Type.PERCENTAGE,
        value=Decimal("50.00"),
        max_discount=Decimal("30.00"),
    )

    client = api_client(customer)

    response = client.post(
        reverse("customer-coupons-validate-coupon"),
        {
            "code": coupon.code,
            "order_id": str(order.id),
        },
        format="json",
    )

    assert response.status_code == status.HTTP_200_OK
    assert str(response.data["discount_amount"]) == "30.00"


def test_customer_cannot_validate_coupon_for_another_customer_order():
    customer = CustomerUserFactory()
    other_customer = CustomerUserFactory()

    other_order, _, _, _ = create_order_from_cart(customer=other_customer)

    CouponFactory(code="OTHERORDER")

    client = api_client(customer)

    response = client.post(
        reverse("customer-coupons-validate-coupon"),
        {
            "code": "OTHERORDER",
            "order_id": str(other_order.id),
        },
        format="json",
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert_error_field(response, "order_id")


def test_customer_validate_unknown_coupon_returns_400():
    customer = CustomerUserFactory()
    order, _, _, _ = create_order_from_cart(customer=customer)

    client = api_client(customer)

    response = client.post(
        reverse("customer-coupons-validate-coupon"),
        {
            "code": "MISSING",
            "order_id": str(order.id),
        },
        format="json",
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert_error_field(response, "code")


def test_customer_validate_inactive_coupon_returns_400():
    customer = CustomerUserFactory()
    order, _, _, _ = create_order_from_cart(customer=customer)

    CouponFactory(
        code="INACTIVE10",
        is_active=False,
    )

    client = api_client(customer)

    response = client.post(
        reverse("customer-coupons-validate-coupon"),
        {
            "code": "INACTIVE10",
            "order_id": str(order.id),
        },
        format="json",
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert_error_field(response, "coupon")


def test_customer_validate_min_order_not_met_returns_400():
    customer = CustomerUserFactory()
    order, _, _, _ = create_order_from_cart(
        customer=customer,
        base_price=Decimal("25.00"),
        quantity=2,
    )

    CouponFactory(
        code="MIN200",
        min_order_value=Decimal("200.00"),
    )

    client = api_client(customer)

    response = client.post(
        reverse("customer-coupons-validate-coupon"),
        {
            "code": "MIN200",
            "order_id": str(order.id),
        },
        format="json",
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert_error_field(response, "min_order_value")


def test_customer_validates_matching_vendor_coupon():
    customer = CustomerUserFactory()
    vendor = ApprovedVendorFactory()

    order, _, _, _ = create_order_from_cart(
        customer=customer,
        vendor=vendor,
    )

    coupon = CouponFactory(
        code="VENDOR10",
        scope=Coupon.Scope.VENDOR,
        vendor=vendor,
    )

    client = api_client(customer)

    response = client.post(
        reverse("customer-coupons-validate-coupon"),
        {
            "code": coupon.code,
            "order_id": str(order.id),
            "vendor_id": str(vendor.id),
        },
        format="json",
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.data["valid"] is True
    assert response.data["scope"] == Coupon.Scope.VENDOR


def test_customer_vendor_coupon_rejects_non_matching_vendor():
    customer = CustomerUserFactory()
    vendor = ApprovedVendorFactory()
    other_vendor = ApprovedVendorFactory()

    order, _, _, _ = create_order_from_cart(
        customer=customer,
        vendor=other_vendor,
    )

    coupon = CouponFactory(
        code="VENDORONLY",
        scope=Coupon.Scope.VENDOR,
        vendor=vendor,
    )

    client = api_client(customer)

    response = client.post(
        reverse("customer-coupons-validate-coupon"),
        {
            "code": coupon.code,
            "order_id": str(order.id),
            "vendor_id": str(other_vendor.id),
        },
        format="json",
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert_error_field(response, "vendor")


def test_customer_validates_matching_category_coupon():
    customer = CustomerUserFactory()
    category = CategoryFactory()

    order, _, _, _ = create_order_from_cart(
        customer=customer,
        category=category,
    )

    coupon = CouponFactory(
        code="CATEGORY10",
        scope=Coupon.Scope.CATEGORY,
        category=category,
    )

    client = api_client(customer)

    response = client.post(
        reverse("customer-coupons-validate-coupon"),
        {
            "code": coupon.code,
            "order_id": str(order.id),
            "category_id": str(category.id),
        },
        format="json",
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.data["valid"] is True
    assert response.data["scope"] == Coupon.Scope.CATEGORY


def test_customer_category_coupon_rejects_non_matching_category():
    customer = CustomerUserFactory()
    category = CategoryFactory()
    other_category = CategoryFactory()

    order, _, _, _ = create_order_from_cart(
        customer=customer,
        category=other_category,
    )

    coupon = CouponFactory(
        code="CATEGORYONLY",
        scope=Coupon.Scope.CATEGORY,
        category=category,
    )

    client = api_client(customer)

    response = client.post(
        reverse("customer-coupons-validate-coupon"),
        {
            "code": coupon.code,
            "order_id": str(order.id),
            "category_id": str(other_category.id),
        },
        format="json",
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert_error_field(response, "category")


def test_customer_records_coupon_usage_for_own_order():
    customer = CustomerUserFactory()
    order, _, _, _ = create_order_from_cart(customer=customer)

    coupon = CouponFactory(
        code="USE10",
        usage_limit=10,
        per_user_limit=2,
    )

    client = api_client(customer)

    response = client.post(
        reverse("customer-coupons-usage"),
        {
            "code": coupon.code,
            "order_id": str(order.id),
        },
        format="json",
    )

    assert response.status_code == status.HTTP_201_CREATED
    assert str(response.data["coupon"]) == str(coupon.id)
    assert response.data["coupon_code"] == coupon.code
    assert str(response.data["user"]) == str(customer.id)
    assert str(response.data["order"]) == str(order.id)

    assert CouponUsage.objects.filter(
        coupon=coupon,
        user=customer,
        order=order,
    ).exists()


def test_customer_cannot_record_duplicate_usage_when_per_user_limit_reached():
    customer = CustomerUserFactory()
    order, _, _, _ = create_order_from_cart(customer=customer)

    coupon = CouponFactory(
        code="ONCEONLY",
        usage_limit=10,
        per_user_limit=1,
    )

    client = api_client(customer)

    first_response = client.post(
        reverse("customer-coupons-usage"),
        {
            "code": coupon.code,
            "order_id": str(order.id),
        },
        format="json",
    )

    second_response = client.post(
        reverse("customer-coupons-usage"),
        {
            "code": coupon.code,
            "order_id": str(order.id),
        },
        format="json",
    )

    assert first_response.status_code == status.HTTP_201_CREATED
    assert second_response.status_code == status.HTTP_400_BAD_REQUEST
    assert_error_field(second_response, "per_user_limit")


def test_customer_cannot_record_usage_for_another_customer_order():
    customer = CustomerUserFactory()
    other_customer = CustomerUserFactory()

    other_order, _, _, _ = create_order_from_cart(customer=other_customer)

    CouponFactory(code="NOOTHER")

    client = api_client(customer)

    response = client.post(
        reverse("customer-coupons-usage"),
        {
            "code": "NOOTHER",
            "order_id": str(other_order.id),
        },
        format="json",
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert_error_field(response, "order_id")


def test_customer_cannot_access_admin_coupon_list():
    customer = CustomerUserFactory()
    client = api_client(customer)

    response = client.get(reverse("admin-coupons-list"))

    assert response.status_code == status.HTTP_403_FORBIDDEN


def test_admin_can_create_global_coupon():
    admin = AdminUserFactory()
    client = api_client(admin)

    response = client.post(
        reverse("admin-coupons-list"),
        coupon_payload(code="ADMIN10"),
        format="json",
    )

    assert response.status_code == status.HTTP_201_CREATED
    assert response.data["code"] == "ADMIN10"
    assert response.data["scope"] == Coupon.Scope.GLOBAL
    assert response.data["vendor"] is None
    assert response.data["category"] is None

    assert Coupon.objects.filter(code="ADMIN10").exists()


def test_admin_create_coupon_normalizes_code():
    admin = AdminUserFactory()
    client = api_client(admin)

    response = client.post(
        reverse("admin-coupons-list"),
        coupon_payload(code="  lower10  "),
        format="json",
    )

    assert response.status_code == status.HTTP_201_CREATED
    assert response.data["code"] == "LOWER10"

    assert Coupon.objects.filter(code="LOWER10").exists()


def test_admin_create_vendor_coupon_without_vendor_returns_400():
    admin = AdminUserFactory()
    client = api_client(admin)

    response = client.post(
        reverse("admin-coupons-list"),
        coupon_payload(
            code="BADVENDOR",
            scope=Coupon.Scope.VENDOR,
            vendor=None,
        ),
        format="json",
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert_error_field(response, "vendor")


def test_admin_lists_coupons():
    admin = AdminUserFactory()

    first_coupon = CouponFactory(code="LISTA")
    second_coupon = CouponFactory(code="LISTB")

    client = api_client(admin)

    response = client.get(reverse("admin-coupons-list"))

    assert response.status_code == status.HTTP_200_OK

    ids = {item["id"] for item in get_results(response)}

    assert str(first_coupon.id) in ids
    assert str(second_coupon.id) in ids


def test_admin_filters_coupons_by_code_scope_and_active_status():
    admin = AdminUserFactory()

    matching_coupon = CouponFactory(
        code="FILTERMATCH",
        scope=Coupon.Scope.GLOBAL,
        is_active=True,
    )

    CouponFactory(
        code="FILTERINACTIVE",
        scope=Coupon.Scope.GLOBAL,
        is_active=False,
    )

    vendor = ApprovedVendorFactory()
    CouponFactory(
        code="FILTERVENDOR",
        scope=Coupon.Scope.VENDOR,
        vendor=vendor,
        is_active=True,
    )

    client = api_client(admin)

    response = client.get(
        reverse("admin-coupons-list"),
        {
            "code": "FILTERMATCH",
            "scope": Coupon.Scope.GLOBAL,
            "is_active": "true",
        },
    )

    assert response.status_code == status.HTTP_200_OK

    ids = {item["id"] for item in get_results(response)}

    assert str(matching_coupon.id) in ids


def test_admin_can_retrieve_coupon():
    admin = AdminUserFactory()
    coupon = CouponFactory(code="DETAIL10")

    client = api_client(admin)

    response = client.get(
        reverse("admin-coupons-detail", kwargs={"pk": str(coupon.id)})
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.data["id"] == str(coupon.id)
    assert response.data["code"] == "DETAIL10"


def test_admin_can_update_coupon():
    admin = AdminUserFactory()
    coupon = CouponFactory(code="UPDATE10")

    client = api_client(admin)

    response = client.put(
        reverse("admin-coupons-detail", kwargs={"pk": str(coupon.id)}),
        coupon_payload(
            code="UPDATED20",
            type=Coupon.Type.FIXED,
            value="20.00",
        ),
        format="json",
    )

    assert response.status_code == status.HTTP_200_OK

    coupon.refresh_from_db()

    assert coupon.code == "UPDATED20"
    assert coupon.value == Decimal("20.00")


def test_admin_can_partially_update_coupon_active_status():
    admin = AdminUserFactory()
    coupon = CouponFactory(code="PATCH10", is_active=True)

    client = api_client(admin)

    response = client.patch(
        reverse("admin-coupons-detail", kwargs={"pk": str(coupon.id)}),
        {
            "is_active": False,
        },
        format="json",
    )

    assert response.status_code == status.HTTP_200_OK

    coupon.refresh_from_db()

    assert coupon.is_active is False


def test_admin_can_delete_unused_coupon():
    admin = AdminUserFactory()
    coupon = CouponFactory(code="DELETE10")

    client = api_client(admin)

    response = client.delete(
        reverse("admin-coupons-detail", kwargs={"pk": str(coupon.id)})
    )

    assert response.status_code == status.HTTP_204_NO_CONTENT
    assert not Coupon.objects.filter(id=coupon.id).exists()


def test_admin_can_create_vendor_coupon():
    admin = AdminUserFactory()
    vendor = ApprovedVendorFactory()

    client = api_client(admin)

    response = client.post(
        reverse("admin-coupons-list"),
        coupon_payload(
            code="ADMINVENDOR",
            scope=Coupon.Scope.VENDOR,
            vendor=str(vendor.id),
        ),
        format="json",
    )

    assert response.status_code == status.HTTP_201_CREATED
    assert response.data["scope"] == Coupon.Scope.VENDOR
    assert str(response.data["vendor"]) == str(vendor.id)


def test_admin_can_create_category_coupon():
    admin = AdminUserFactory()
    category = CategoryFactory()

    client = api_client(admin)

    response = client.post(
        reverse("admin-coupons-list"),
        coupon_payload(
            code="ADMINCATEGORY",
            scope=Coupon.Scope.CATEGORY,
            category=str(category.id),
        ),
        format="json",
    )

    assert response.status_code == status.HTTP_201_CREATED
    assert response.data["scope"] == Coupon.Scope.CATEGORY
    assert str(response.data["category"]) == str(category.id)


def test_admin_lists_coupon_usages():
    admin = AdminUserFactory()
    customer = CustomerUserFactory()
    order, _, _, _ = create_order_from_cart(customer=customer)

    coupon = CouponFactory(code="USAGELIST")

    usage = CouponUsage.objects.create(
        coupon=coupon,
        user=customer,
        order=order,
    )

    client = api_client(admin)

    response = client.get(reverse("admin-coupon-usages-list"))

    assert response.status_code == status.HTTP_200_OK

    ids = {item["id"] for item in get_results(response)}

    assert str(usage.id) in ids


def test_admin_filters_coupon_usages():
    admin = AdminUserFactory()
    customer = CustomerUserFactory()
    order, _, _, _ = create_order_from_cart(customer=customer)

    coupon = CouponFactory(code="USAGEFILTER")

    usage = CouponUsage.objects.create(
        coupon=coupon,
        user=customer,
        order=order,
    )

    other_customer = CustomerUserFactory()
    other_order, _, _, _ = create_order_from_cart(customer=other_customer)
    other_coupon = CouponFactory(code="OTHERUSAGE")

    CouponUsage.objects.create(
        coupon=other_coupon,
        user=other_customer,
        order=other_order,
    )

    client = api_client(admin)

    response = client.get(
        reverse("admin-coupon-usages-list"),
        {
            "coupon_id": str(coupon.id),
            "code": "USAGEFILTER",
            "user_id": str(customer.id),
            "order_id": str(order.id),
        },
    )

    assert response.status_code == status.HTTP_200_OK

    ids = {item["id"] for item in get_results(response)}

    assert str(usage.id) in ids


def test_admin_can_retrieve_coupon_usage():
    admin = AdminUserFactory()
    customer = CustomerUserFactory()
    order, _, _, _ = create_order_from_cart(customer=customer)

    coupon = CouponFactory(code="USAGEDETAIL")

    usage = CouponUsage.objects.create(
        coupon=coupon,
        user=customer,
        order=order,
    )

    client = api_client(admin)

    response = client.get(
        reverse("admin-coupon-usages-detail", kwargs={"pk": str(usage.id)})
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.data["id"] == str(usage.id)
    assert response.data["coupon_code"] == coupon.code
    assert str(response.data["user"]) == str(customer.id)
    assert str(response.data["order"]) == str(order.id)


def test_customer_cannot_access_admin_coupon_usage_list():
    customer = CustomerUserFactory()
    client = api_client(customer)

    response = client.get(reverse("admin-coupon-usages-list"))

    assert response.status_code == status.HTTP_403_FORBIDDEN