from decimal import Decimal

import pytest
from django.urls import reverse
from rest_framework import status

from apps.accounts.tests.factories import (
    AdminUserFactory,
    CustomerUserFactory,
    VendorUserFactory,
)
from apps.cart.models import Cart, CartItem
from apps.cart.tests.factories import CartFactory, CartItemFactory
from apps.catalog.models import Product
from apps.catalog.tests.factories import (
    PendingVendorFactory,
    ProductFactory,
    ProductVariantFactory,
)
from apps.inventory.tests.factories import InventoryRecordFactory


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
    name="API Active Product",
    base_price=Decimal("100.00"),
    quantity_on_hand=100,
    quantity_reserved=0,
    track_inventory=True,
    allow_backorder=False,
    **overrides,
):
    product = ProductFactory(
        name=name,
        base_price=base_price,
        status=Product.Status.ACTIVE,
        **overrides,
    )

    InventoryRecordFactory(
        product=product,
        variant=None,
        quantity_on_hand=quantity_on_hand,
        quantity_reserved=quantity_reserved,
        track_inventory=track_inventory,
        allow_backorder=allow_backorder,
    )

    return product


def create_active_variant_with_inventory(
    product,
    *,
    name="API Variant",
    price=Decimal("120.00"),
    quantity_on_hand=100,
    quantity_reserved=0,
    is_active=True,
    track_inventory=True,
    allow_backorder=False,
    **overrides,
):
    variant = ProductVariantFactory(
        product=product,
        name=name,
        price=price,
        is_active=is_active,
        **overrides,
    )

    InventoryRecordFactory(
        product=product,
        variant=variant,
        quantity_on_hand=quantity_on_hand,
        quantity_reserved=quantity_reserved,
        track_inventory=track_inventory,
        allow_backorder=allow_backorder,
    )

    return variant


def add_item_payload(product, variant=None, quantity=1):
    return {
        "product": str(product.id),
        "variant": str(variant.id) if variant else None,
        "quantity": quantity,
    }


def test_customer_cart_requires_authentication(api_client):
    url = reverse("customer-cart-list")

    response = api_client.get(url)

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_vendor_cannot_access_customer_cart(api_client):
    vendor_user = VendorUserFactory()
    api_client.force_authenticate(user=vendor_user)

    url = reverse("customer-cart-list")

    response = api_client.get(url)

    assert response.status_code == status.HTTP_403_FORBIDDEN


def test_customer_get_my_cart_creates_active_cart(api_client):
    customer = CustomerUserFactory()
    api_client.force_authenticate(user=customer)

    assert Cart.objects.filter(customer=customer).count() == 0

    url = reverse("customer-cart-list")

    response = api_client.get(url)

    assert response.status_code == status.HTTP_200_OK
    assert response.data["customer_id"] == str(customer.id)
    assert response.data["status"] == Cart.Status.ACTIVE
    assert response.data["items"] == []
    assert response.data["item_count"] == 0
    assert response.data["total_quantity"] == 0
    assert response.data["subtotal_amount"] == "0.00"

    assert Cart.objects.filter(customer=customer, status=Cart.Status.ACTIVE).count() == 1


def test_customer_get_my_cart_returns_existing_cart_with_totals(api_client):
    customer = CustomerUserFactory()
    cart = CartFactory(customer=customer)

    first_product = create_active_product_with_inventory(
        name="API First Product",
        base_price=Decimal("10.00"),
    )
    second_product = create_active_product_with_inventory(
        name="API Second Product",
        base_price=Decimal("20.00"),
    )

    CartItemFactory(
        cart=cart,
        product=first_product,
        quantity=2,
    )
    CartItemFactory(
        cart=cart,
        product=second_product,
        quantity=3,
    )

    api_client.force_authenticate(user=customer)

    url = reverse("customer-cart-list")

    response = api_client.get(url)

    assert response.status_code == status.HTTP_200_OK
    assert response.data["id"] == str(cart.id)
    assert response.data["item_count"] == 2
    assert response.data["total_quantity"] == 5
    assert response.data["subtotal_amount"] == "80.00"
    assert len(response.data["items"]) == 2


def test_customer_add_item_creates_cart_when_missing(api_client):
    customer = CustomerUserFactory()
    product = create_active_product_with_inventory()

    api_client.force_authenticate(user=customer)

    url = reverse("customer-cart-items")

    response = api_client.post(
        url,
        add_item_payload(product, quantity=2),
        format="json",
    )

    assert response.status_code == status.HTTP_201_CREATED
    assert response.data["product_id"] == str(product.id)
    assert response.data["quantity"] == 2

    cart = Cart.objects.get(customer=customer, status=Cart.Status.ACTIVE)

    assert cart.items.count() == 1


def test_customer_can_add_product_level_item(api_client):
    customer = CustomerUserFactory()
    cart = CartFactory(customer=customer)

    product = create_active_product_with_inventory(
        base_price=Decimal("50.00"),
    )

    api_client.force_authenticate(user=customer)

    url = reverse("customer-cart-items")

    response = api_client.post(
        url,
        add_item_payload(product, quantity=2),
        format="json",
    )

    assert response.status_code == status.HTTP_201_CREATED
    assert response.data["product_id"] == str(product.id)
    assert response.data["variant_id"] is None
    assert response.data["quantity"] == 2
    assert response.data["unit_price"] == "50.00"
    assert response.data["line_total"] == "100.00"

    item = CartItem.objects.get(cart=cart, product=product)

    assert item.quantity == 2


def test_customer_add_same_product_merges_quantity(api_client):
    customer = CustomerUserFactory()
    cart = CartFactory(customer=customer)

    product = create_active_product_with_inventory(
        quantity_on_hand=10,
    )

    CartItemFactory(
        cart=cart,
        product=product,
        quantity=2,
    )

    api_client.force_authenticate(user=customer)

    url = reverse("customer-cart-items")

    response = api_client.post(
        url,
        add_item_payload(product, quantity=3),
        format="json",
    )

    assert response.status_code == status.HTTP_201_CREATED
    assert response.data["quantity"] == 5

    assert cart.items.count() == 1

    item = cart.items.first()

    assert item.quantity == 5


def test_customer_can_add_variant_level_item(api_client):
    customer = CustomerUserFactory()
    CartFactory(customer=customer)

    product = create_active_product_with_inventory()
    variant = create_active_variant_with_inventory(
        product,
        name="128GB Black",
        price=Decimal("150.00"),
    )

    api_client.force_authenticate(user=customer)

    url = reverse("customer-cart-items")

    response = api_client.post(
        url,
        add_item_payload(product, variant=variant, quantity=2),
        format="json",
    )

    assert response.status_code == status.HTTP_201_CREATED
    assert response.data["product_id"] == str(product.id)
    assert response.data["variant_id"] == str(variant.id)
    assert response.data["variant_name"] == "128GB Black"
    assert response.data["quantity"] == 2
    assert response.data["unit_price"] == "150.00"
    assert response.data["line_total"] == "300.00"


def test_customer_add_item_rejects_inactive_product(api_client):
    customer = CustomerUserFactory()
    CartFactory(customer=customer)

    product = ProductFactory(status=Product.Status.DRAFT)

    api_client.force_authenticate(user=customer)

    url = reverse("customer-cart-items")

    response = api_client.post(
        url,
        add_item_payload(product, quantity=1),
        format="json",
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST

    details = get_error_details(response)

    assert "product" in details


def test_customer_add_item_rejects_product_from_pending_vendor(api_client):
    customer = CustomerUserFactory()
    CartFactory(customer=customer)

    pending_vendor = PendingVendorFactory()

    product = ProductFactory(
        vendor=pending_vendor,
        status=Product.Status.DRAFT,
    )

    Product.objects.filter(pk=product.pk).update(status=Product.Status.ACTIVE)
    product.refresh_from_db()

    api_client.force_authenticate(user=customer)

    url = reverse("customer-cart-items")

    response = api_client.post(
        url,
        add_item_payload(product, quantity=1),
        format="json",
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST

    details = get_error_details(response)

    assert "product" in details


def test_customer_add_item_rejects_inactive_category(api_client):
    customer = CustomerUserFactory()
    CartFactory(customer=customer)

    product = create_active_product_with_inventory()

    product.category.is_active = False
    product.category.save(update_fields=["is_active"])

    api_client.force_authenticate(user=customer)

    url = reverse("customer-cart-items")

    response = api_client.post(
        url,
        add_item_payload(product, quantity=1),
        format="json",
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST

    details = get_error_details(response)

    assert "product" in details


def test_customer_add_item_rejects_inactive_brand(api_client):
    customer = CustomerUserFactory()
    CartFactory(customer=customer)

    product = create_active_product_with_inventory()

    product.brand.is_active = False
    product.brand.save(update_fields=["is_active"])

    api_client.force_authenticate(user=customer)

    url = reverse("customer-cart-items")

    response = api_client.post(
        url,
        add_item_payload(product, quantity=1),
        format="json",
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST

    details = get_error_details(response)

    assert "product" in details


def test_customer_add_item_rejects_variant_from_other_product(api_client):
    customer = CustomerUserFactory()
    CartFactory(customer=customer)

    product = create_active_product_with_inventory(name="Main API Product")
    other_product = create_active_product_with_inventory(name="Other API Product")

    other_variant = create_active_variant_with_inventory(
        other_product,
        name="Other Variant",
    )

    api_client.force_authenticate(user=customer)

    url = reverse("customer-cart-items")

    response = api_client.post(
        url,
        add_item_payload(product, variant=other_variant, quantity=1),
        format="json",
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST

    details = get_error_details(response)

    assert "variant" in details


def test_customer_add_item_rejects_inactive_variant(api_client):
    customer = CustomerUserFactory()
    CartFactory(customer=customer)

    product = create_active_product_with_inventory()
    variant = create_active_variant_with_inventory(
        product,
        name="Inactive API Variant",
        is_active=False,
    )

    api_client.force_authenticate(user=customer)

    url = reverse("customer-cart-items")

    response = api_client.post(
        url,
        add_item_payload(product, variant=variant, quantity=1),
        format="json",
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST

    details = get_error_details(response)

    assert "variant" in details


def test_customer_add_item_rejects_missing_inventory_record(api_client):
    customer = CustomerUserFactory()
    CartFactory(customer=customer)

    product = ProductFactory(
        name="No Inventory API Product",
        status=Product.Status.ACTIVE,
    )

    api_client.force_authenticate(user=customer)

    url = reverse("customer-cart-items")

    response = api_client.post(
        url,
        add_item_payload(product, quantity=1),
        format="json",
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST

    details = get_error_details(response)

    assert "inventory" in details


def test_customer_add_item_rejects_quantity_exceeding_available_stock(api_client):
    customer = CustomerUserFactory()
    CartFactory(customer=customer)

    product = create_active_product_with_inventory(
        quantity_on_hand=5,
        quantity_reserved=2,
    )

    api_client.force_authenticate(user=customer)

    url = reverse("customer-cart-items")

    response = api_client.post(
        url,
        add_item_payload(product, quantity=4),
        format="json",
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST

    details = get_error_details(response)

    assert "quantity" in details


def test_customer_can_update_cart_item_quantity(api_client):
    customer = CustomerUserFactory()
    cart = CartFactory(customer=customer)

    product = create_active_product_with_inventory(
        quantity_on_hand=10,
        base_price=Decimal("25.00"),
    )

    item = CartItemFactory(
        cart=cart,
        product=product,
        quantity=2,
    )

    api_client.force_authenticate(user=customer)

    url = reverse(
        "customer-cart-item-detail",
        kwargs={"item_id": item.id},
    )

    response = api_client.patch(
        url,
        {
            "quantity": 5,
        },
        format="json",
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.data["id"] == str(item.id)
    assert response.data["quantity"] == 5
    assert response.data["unit_price"] == "25.00"
    assert response.data["line_total"] == "125.00"

    item.refresh_from_db()

    assert item.quantity == 5


def test_customer_update_cart_item_rejects_quantity_exceeding_stock(api_client):
    customer = CustomerUserFactory()
    cart = CartFactory(customer=customer)

    product = create_active_product_with_inventory(
        quantity_on_hand=5,
        quantity_reserved=0,
    )

    item = CartItemFactory(
        cart=cart,
        product=product,
        quantity=2,
    )

    api_client.force_authenticate(user=customer)

    url = reverse(
        "customer-cart-item-detail",
        kwargs={"item_id": item.id},
    )

    response = api_client.patch(
        url,
        {
            "quantity": 6,
        },
        format="json",
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST

    item.refresh_from_db()

    assert item.quantity == 2


def test_customer_update_cart_item_rejects_zero_quantity(api_client):
    customer = CustomerUserFactory()
    cart = CartFactory(customer=customer)

    product = create_active_product_with_inventory()

    item = CartItemFactory(
        cart=cart,
        product=product,
        quantity=2,
    )

    api_client.force_authenticate(user=customer)

    url = reverse(
        "customer-cart-item-detail",
        kwargs={"item_id": item.id},
    )

    response = api_client.patch(
        url,
        {
            "quantity": 0,
        },
        format="json",
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST

    item.refresh_from_db()

    assert item.quantity == 2


def test_customer_cannot_update_other_customer_cart_item(api_client):
    own_customer = CustomerUserFactory()
    other_customer = CustomerUserFactory()

    other_cart = CartFactory(customer=other_customer)
    product = create_active_product_with_inventory()

    item = CartItemFactory(
        cart=other_cart,
        product=product,
        quantity=1,
    )

    api_client.force_authenticate(user=own_customer)

    url = reverse(
        "customer-cart-item-detail",
        kwargs={"item_id": item.id},
    )

    response = api_client.patch(
        url,
        {
            "quantity": 2,
        },
        format="json",
    )

    assert response.status_code == status.HTTP_404_NOT_FOUND


def test_customer_can_delete_cart_item(api_client):
    customer = CustomerUserFactory()
    cart = CartFactory(customer=customer)

    product = create_active_product_with_inventory()

    item = CartItemFactory(
        cart=cart,
        product=product,
        quantity=1,
    )

    api_client.force_authenticate(user=customer)

    url = reverse(
        "customer-cart-item-detail",
        kwargs={"item_id": item.id},
    )

    response = api_client.delete(url)

    assert response.status_code == status.HTTP_204_NO_CONTENT
    assert CartItem.objects.filter(id=item.id).exists() is False


def test_customer_cannot_delete_other_customer_cart_item(api_client):
    own_customer = CustomerUserFactory()
    other_customer = CustomerUserFactory()

    other_cart = CartFactory(customer=other_customer)
    product = create_active_product_with_inventory()

    item = CartItemFactory(
        cart=other_cart,
        product=product,
        quantity=1,
    )

    api_client.force_authenticate(user=own_customer)

    url = reverse(
        "customer-cart-item-detail",
        kwargs={"item_id": item.id},
    )

    response = api_client.delete(url)

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert CartItem.objects.filter(id=item.id).exists() is True


def test_customer_can_clear_cart(api_client):
    customer = CustomerUserFactory()
    cart = CartFactory(customer=customer)

    first_product = create_active_product_with_inventory(name="Clear Product One")
    second_product = create_active_product_with_inventory(name="Clear Product Two")

    CartItemFactory(
        cart=cart,
        product=first_product,
        quantity=1,
    )
    CartItemFactory(
        cart=cart,
        product=second_product,
        quantity=2,
    )

    api_client.force_authenticate(user=customer)

    url = reverse("customer-cart-clear")

    response = api_client.post(url)

    assert response.status_code == status.HTTP_200_OK
    assert response.data["detail"] == "Cart cleared successfully."
    assert cart.items.count() == 0


def test_admin_can_list_carts(api_client):
    admin = AdminUserFactory()
    cart = CartFactory()

    api_client.force_authenticate(user=admin)

    url = reverse("admin-carts-list")

    response = api_client.get(url)

    assert response.status_code == status.HTTP_200_OK

    results = get_results(response)

    assert len(results) == 1
    assert results[0]["id"] == str(cart.id)


def test_admin_can_filter_carts_by_status(api_client):
    admin = AdminUserFactory()

    active_cart = CartFactory(status=Cart.Status.ACTIVE)
    CartFactory(status=Cart.Status.ABANDONED)

    api_client.force_authenticate(user=admin)

    url = reverse("admin-carts-list")

    response = api_client.get(
        url,
        {
            "status": Cart.Status.ACTIVE,
        },
    )

    assert response.status_code == status.HTTP_200_OK

    results = get_results(response)

    assert len(results) == 1
    assert results[0]["id"] == str(active_cart.id)
    assert results[0]["status"] == Cart.Status.ACTIVE


def test_admin_can_filter_carts_by_customer(api_client):
    admin = AdminUserFactory()

    customer = CustomerUserFactory()
    other_customer = CustomerUserFactory()

    matching_cart = CartFactory(customer=customer)
    CartFactory(customer=other_customer)

    api_client.force_authenticate(user=admin)

    url = reverse("admin-carts-list")

    response = api_client.get(
        url,
        {
            "customer": str(customer.id),
        },
    )

    assert response.status_code == status.HTTP_200_OK

    results = get_results(response)

    assert len(results) == 1
    assert results[0]["id"] == str(matching_cart.id)
    assert results[0]["customer_id"] == str(customer.id)


def test_admin_can_retrieve_cart(api_client):
    admin = AdminUserFactory()
    cart = CartFactory()

    api_client.force_authenticate(user=admin)

    url = reverse(
        "admin-carts-detail",
        kwargs={"pk": cart.id},
    )

    response = api_client.get(url)

    assert response.status_code == status.HTTP_200_OK
    assert response.data["id"] == str(cart.id)


def test_non_admin_cannot_list_admin_carts(api_client):
    customer = CustomerUserFactory()
    api_client.force_authenticate(user=customer)

    url = reverse("admin-carts-list")

    response = api_client.get(url)

    assert response.status_code == status.HTTP_403_FORBIDDEN


def test_admin_can_list_cart_items(api_client):
    admin = AdminUserFactory()
    product = create_active_product_with_inventory()

    item = CartItemFactory(
        product=product,
        quantity=1,
    )

    api_client.force_authenticate(user=admin)

    url = reverse("admin-cart-items-list")

    response = api_client.get(url)

    assert response.status_code == status.HTTP_200_OK

    results = get_results(response)

    assert len(results) == 1
    assert results[0]["id"] == str(item.id)


def test_admin_can_filter_cart_items_by_cart(api_client):
    admin = AdminUserFactory()

    first_cart = CartFactory()
    second_cart = CartFactory()

    first_product = create_active_product_with_inventory(name="Cart Filter Product One")
    second_product = create_active_product_with_inventory(name="Cart Filter Product Two")

    matching_item = CartItemFactory(
        cart=first_cart,
        product=first_product,
    )
    CartItemFactory(
        cart=second_cart,
        product=second_product,
    )

    api_client.force_authenticate(user=admin)

    url = reverse("admin-cart-items-list")

    response = api_client.get(
        url,
        {
            "cart": str(first_cart.id),
        },
    )

    assert response.status_code == status.HTTP_200_OK

    results = get_results(response)

    assert len(results) == 1
    assert results[0]["id"] == str(matching_item.id)


def test_admin_can_filter_cart_items_by_customer(api_client):
    admin = AdminUserFactory()

    customer = CustomerUserFactory()
    other_customer = CustomerUserFactory()

    first_cart = CartFactory(customer=customer)
    second_cart = CartFactory(customer=other_customer)

    first_product = create_active_product_with_inventory(name="Customer Filter One")
    second_product = create_active_product_with_inventory(name="Customer Filter Two")

    matching_item = CartItemFactory(
        cart=first_cart,
        product=first_product,
    )
    CartItemFactory(
        cart=second_cart,
        product=second_product,
    )

    api_client.force_authenticate(user=admin)

    url = reverse("admin-cart-items-list")

    response = api_client.get(
        url,
        {
            "customer": str(customer.id),
        },
    )

    assert response.status_code == status.HTTP_200_OK

    results = get_results(response)

    assert len(results) == 1
    assert results[0]["id"] == str(matching_item.id)


def test_admin_can_filter_cart_items_by_product(api_client):
    admin = AdminUserFactory()

    first_product = create_active_product_with_inventory(name="Product Filter One")
    second_product = create_active_product_with_inventory(name="Product Filter Two")

    matching_item = CartItemFactory(
        product=first_product,
    )
    CartItemFactory(
        product=second_product,
    )

    api_client.force_authenticate(user=admin)

    url = reverse("admin-cart-items-list")

    response = api_client.get(
        url,
        {
            "product": str(first_product.id),
        },
    )

    assert response.status_code == status.HTTP_200_OK

    results = get_results(response)

    assert len(results) == 1
    assert results[0]["id"] == str(matching_item.id)


def test_admin_can_retrieve_cart_item(api_client):
    admin = AdminUserFactory()
    product = create_active_product_with_inventory()

    item = CartItemFactory(
        product=product,
    )

    api_client.force_authenticate(user=admin)

    url = reverse(
        "admin-cart-items-detail",
        kwargs={"pk": item.id},
    )

    response = api_client.get(url)

    assert response.status_code == status.HTTP_200_OK
    assert response.data["id"] == str(item.id)
    assert response.data["product_id"] == str(product.id)


def test_non_admin_cannot_list_admin_cart_items(api_client):
    vendor_user = VendorUserFactory()
    api_client.force_authenticate(user=vendor_user)

    url = reverse("admin-cart-items-list")

    response = api_client.get(url)

    assert response.status_code == status.HTTP_403_FORBIDDEN


def test_cart_schema_contains_cart_endpoints(api_client):
    url = reverse("schema")

    response = api_client.get(url)

    assert response.status_code == status.HTTP_200_OK

    content = response.content.decode()

    assert "/api/v1/cart/my-cart/" in content
    assert "/api/v1/cart/my-cart/items/" in content
    assert "/api/v1/cart/my-cart/items/{item_id}/" in content
    assert "/api/v1/cart/my-cart/clear/" in content

    assert "/api/v1/cart/admin/carts/" in content
    assert "/api/v1/cart/admin/carts/{id}/" in content
    assert "/api/v1/cart/admin/items/" in content
    assert "/api/v1/cart/admin/items/{id}/" in content