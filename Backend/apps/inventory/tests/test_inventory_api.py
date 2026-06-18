import pytest
from django.urls import reverse
from rest_framework import status

from apps.accounts.tests.factories import (
    AdminUserFactory,
    CustomerUserFactory,
    VendorUserFactory,
)
from apps.catalog.tests.factories import (
    ApprovedVendorFactory,
    PendingVendorFactory,
    ProductFactory,
    ProductVariantFactory,
)
from apps.inventory.models import InventoryRecord, StockMovement
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


def inventory_payload(product, variant=None, **overrides):
    data = {
        "product": str(product.id),
        "variant": str(variant.id) if variant else None,
        "quantity_on_hand": 100,
        "quantity_reserved": 0,
        "low_stock_threshold": 10,
        "track_inventory": True,
        "allow_backorder": False,
    }

    data.update(overrides)

    return data


def stock_operation_payload(**overrides):
    data = {
        "quantity": 5,
        "reason": "Test stock operation",
        "reference": "TEST-REF-001",
    }

    data.update(overrides)

    return data


def test_vendor_inventory_list_requires_authentication(api_client):
    url = reverse("vendor-inventory-records-list")

    response = api_client.get(url)

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_customer_cannot_access_vendor_inventory(api_client):
    customer = CustomerUserFactory()
    api_client.force_authenticate(user=customer)

    url = reverse("vendor-inventory-records-list")

    response = api_client.get(url)

    assert response.status_code == status.HTTP_403_FORBIDDEN


def test_pending_vendor_cannot_create_inventory_record(api_client):
    pending_vendor = PendingVendorFactory()
    product = ProductFactory(vendor=pending_vendor)

    api_client.force_authenticate(user=pending_vendor.user)

    url = reverse("vendor-inventory-records-list")

    response = api_client.post(
        url,
        inventory_payload(product),
        format="json",
    )

    assert response.status_code == status.HTTP_403_FORBIDDEN


def test_approved_vendor_can_create_product_level_inventory_record(api_client):
    vendor = ApprovedVendorFactory()
    product = ProductFactory(vendor=vendor)

    api_client.force_authenticate(user=vendor.user)

    url = reverse("vendor-inventory-records-list")

    response = api_client.post(
        url,
        inventory_payload(
            product,
            quantity_on_hand=120,
            quantity_reserved=10,
            low_stock_threshold=15,
        ),
        format="json",
    )

    assert response.status_code == status.HTTP_201_CREATED
    assert response.data["product_id"] == str(product.id)
    assert response.data["variant_id"] is None
    assert response.data["quantity_on_hand"] == 120
    assert response.data["quantity_reserved"] == 10
    assert response.data["available_quantity"] == 110
    assert response.data["low_stock_threshold"] == 15

    record = InventoryRecord.objects.get(id=response.data["id"])

    assert record.product == product
    assert record.variant is None


def test_approved_vendor_can_create_variant_level_inventory_record(api_client):
    vendor = ApprovedVendorFactory()
    product = ProductFactory(vendor=vendor)
    variant = ProductVariantFactory(product=product)

    api_client.force_authenticate(user=vendor.user)

    url = reverse("vendor-inventory-records-list")

    response = api_client.post(
        url,
        inventory_payload(
            product,
            variant=variant,
            quantity_on_hand=50,
            quantity_reserved=5,
        ),
        format="json",
    )

    assert response.status_code == status.HTTP_201_CREATED
    assert response.data["product_id"] == str(product.id)
    assert response.data["variant_id"] == str(variant.id)
    assert response.data["quantity_on_hand"] == 50
    assert response.data["quantity_reserved"] == 5
    assert response.data["available_quantity"] == 45


def test_vendor_cannot_create_inventory_for_other_vendor_product(api_client):
    own_vendor = ApprovedVendorFactory()
    other_vendor = ApprovedVendorFactory()

    other_product = ProductFactory(vendor=other_vendor)

    api_client.force_authenticate(user=own_vendor.user)

    url = reverse("vendor-inventory-records-list")

    response = api_client.post(
        url,
        inventory_payload(other_product),
        format="json",
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST

    details = get_error_details(response)

    assert "product" in details


def test_vendor_inventory_create_rejects_variant_from_other_product(api_client):
    vendor = ApprovedVendorFactory()
    product = ProductFactory(vendor=vendor)
    other_product = ProductFactory(vendor=vendor)
    other_variant = ProductVariantFactory(product=other_product)

    api_client.force_authenticate(user=vendor.user)

    url = reverse("vendor-inventory-records-list")

    response = api_client.post(
        url,
        inventory_payload(product, variant=other_variant),
        format="json",
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST

    details = get_error_details(response)

    assert "variant" in details


def test_vendor_inventory_create_rejects_reserved_more_than_on_hand(api_client):
    vendor = ApprovedVendorFactory()
    product = ProductFactory(vendor=vendor)

    api_client.force_authenticate(user=vendor.user)

    url = reverse("vendor-inventory-records-list")

    response = api_client.post(
        url,
        inventory_payload(
            product,
            quantity_on_hand=5,
            quantity_reserved=10,
        ),
        format="json",
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST

    details = get_error_details(response)

    assert "quantity_reserved" in details


def test_vendor_inventory_create_rejects_duplicate_product_level_record(api_client):
    vendor = ApprovedVendorFactory()
    product = ProductFactory(vendor=vendor)

    InventoryRecordFactory(
        product=product,
        variant=None,
    )

    api_client.force_authenticate(user=vendor.user)

    url = reverse("vendor-inventory-records-list")

    response = api_client.post(
        url,
        inventory_payload(product),
        format="json",
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST


def test_vendor_inventory_list_only_returns_own_records(api_client):
    own_vendor = ApprovedVendorFactory()
    other_vendor = ApprovedVendorFactory()

    own_product = ProductFactory(vendor=own_vendor)
    other_product = ProductFactory(vendor=other_vendor)

    own_record = InventoryRecordFactory(product=own_product)
    InventoryRecordFactory(product=other_product)

    api_client.force_authenticate(user=own_vendor.user)

    url = reverse("vendor-inventory-records-list")

    response = api_client.get(url)

    assert response.status_code == status.HTTP_200_OK

    results = get_results(response)

    assert len(results) == 1
    assert results[0]["id"] == str(own_record.id)
    assert results[0]["product_id"] == str(own_product.id)


def test_vendor_can_retrieve_own_inventory_record(api_client):
    vendor = ApprovedVendorFactory()
    product = ProductFactory(vendor=vendor)

    record = InventoryRecordFactory(
        product=product,
        quantity_on_hand=30,
        quantity_reserved=5,
    )

    api_client.force_authenticate(user=vendor.user)

    url = reverse(
        "vendor-inventory-records-detail",
        kwargs={"pk": record.id},
    )

    response = api_client.get(url)

    assert response.status_code == status.HTTP_200_OK
    assert response.data["id"] == str(record.id)
    assert response.data["available_quantity"] == 25


def test_vendor_cannot_retrieve_other_vendor_inventory_record(api_client):
    own_vendor = ApprovedVendorFactory()
    other_vendor = ApprovedVendorFactory()

    other_product = ProductFactory(vendor=other_vendor)
    other_record = InventoryRecordFactory(product=other_product)

    api_client.force_authenticate(user=own_vendor.user)

    url = reverse(
        "vendor-inventory-records-detail",
        kwargs={"pk": other_record.id},
    )

    response = api_client.get(url)

    assert response.status_code == status.HTTP_404_NOT_FOUND


def test_vendor_can_update_inventory_settings(api_client):
    vendor = ApprovedVendorFactory()
    product = ProductFactory(vendor=vendor)

    record = InventoryRecordFactory(
        product=product,
        low_stock_threshold=10,
        track_inventory=True,
        allow_backorder=False,
    )

    api_client.force_authenticate(user=vendor.user)

    url = reverse(
        "vendor-inventory-records-detail",
        kwargs={"pk": record.id},
    )

    response = api_client.patch(
        url,
        {
            "low_stock_threshold": 3,
            "track_inventory": False,
            "allow_backorder": True,
        },
        format="json",
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.data["low_stock_threshold"] == 3
    assert response.data["track_inventory"] is False
    assert response.data["allow_backorder"] is True

    record.refresh_from_db()

    assert record.low_stock_threshold == 3
    assert record.track_inventory is False
    assert record.allow_backorder is True


def test_vendor_cannot_update_stock_quantities_directly(api_client):
    vendor = ApprovedVendorFactory()
    product = ProductFactory(vendor=vendor)

    record = InventoryRecordFactory(
        product=product,
        quantity_on_hand=20,
        quantity_reserved=0,
    )

    api_client.force_authenticate(user=vendor.user)

    url = reverse(
        "vendor-inventory-records-detail",
        kwargs={"pk": record.id},
    )

    response = api_client.patch(
        url,
        {
            "quantity_on_hand": 999,
        },
        format="json",
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST

    record.refresh_from_db()

    assert record.quantity_on_hand == 20


def test_vendor_can_increase_stock(api_client):
    vendor = ApprovedVendorFactory()
    product = ProductFactory(vendor=vendor)

    record = InventoryRecordFactory(
        product=product,
        quantity_on_hand=10,
        quantity_reserved=2,
    )

    api_client.force_authenticate(user=vendor.user)

    url = reverse(
        "vendor-inventory-records-increase-stock",
        kwargs={"pk": record.id},
    )

    response = api_client.post(
        url,
        stock_operation_payload(
            quantity=5,
            reason="Vendor restock",
            reference="VENDOR-IN-001",
        ),
        format="json",
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.data["quantity_on_hand"] == 15
    assert response.data["quantity_reserved"] == 2
    assert response.data["available_quantity"] == 13

    record.refresh_from_db()

    assert record.quantity_on_hand == 15
    assert record.movements.count() == 1

    movement = record.movements.first()

    assert movement.movement_type == StockMovement.MovementType.IN
    assert movement.quantity == 5
    assert movement.reason == "Vendor restock"
    assert movement.reference == "VENDOR-IN-001"
    assert movement.created_by == vendor.user


def test_vendor_can_decrease_stock(api_client):
    vendor = ApprovedVendorFactory()
    product = ProductFactory(vendor=vendor)

    record = InventoryRecordFactory(
        product=product,
        quantity_on_hand=20,
        quantity_reserved=5,
    )

    api_client.force_authenticate(user=vendor.user)

    url = reverse(
        "vendor-inventory-records-decrease-stock",
        kwargs={"pk": record.id},
    )

    response = api_client.post(
        url,
        stock_operation_payload(
            quantity=5,
            reason="Damaged stock",
            reference="DAMAGE-001",
        ),
        format="json",
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.data["quantity_on_hand"] == 15
    assert response.data["quantity_reserved"] == 5
    assert response.data["available_quantity"] == 10

    record.refresh_from_db()

    assert record.quantity_on_hand == 15
    assert record.movements.count() == 1

    movement = record.movements.first()

    assert movement.movement_type == StockMovement.MovementType.OUT
    assert movement.quantity == 5


def test_vendor_decrease_stock_cannot_exceed_available_quantity(api_client):
    vendor = ApprovedVendorFactory()
    product = ProductFactory(vendor=vendor)

    record = InventoryRecordFactory(
        product=product,
        quantity_on_hand=10,
        quantity_reserved=8,
    )

    api_client.force_authenticate(user=vendor.user)

    url = reverse(
        "vendor-inventory-records-decrease-stock",
        kwargs={"pk": record.id},
    )

    response = api_client.post(
        url,
        stock_operation_payload(quantity=3),
        format="json",
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST

    record.refresh_from_db()

    assert record.quantity_on_hand == 10
    assert record.quantity_reserved == 8
    assert record.movements.count() == 0


def test_vendor_stock_operation_rejects_zero_quantity(api_client):
    vendor = ApprovedVendorFactory()
    product = ProductFactory(vendor=vendor)

    record = InventoryRecordFactory(product=product)

    api_client.force_authenticate(user=vendor.user)

    url = reverse(
        "vendor-inventory-records-increase-stock",
        kwargs={"pk": record.id},
    )

    response = api_client.post(
        url,
        stock_operation_payload(quantity=0),
        format="json",
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST


def test_vendor_stock_movements_list_only_returns_own_movements(api_client):
    own_vendor = ApprovedVendorFactory()
    other_vendor = ApprovedVendorFactory()

    own_product = ProductFactory(vendor=own_vendor)
    other_product = ProductFactory(vendor=other_vendor)

    own_record = InventoryRecordFactory(product=own_product)
    other_record = InventoryRecordFactory(product=other_product)

    own_movement = own_record.increase_stock(
        5,
        reason="Own restock",
        reference="OWN-001",
        created_by=own_vendor.user,
    )

    other_record.increase_stock(
        5,
        reason="Other restock",
        reference="OTHER-001",
        created_by=other_vendor.user,
    )

    api_client.force_authenticate(user=own_vendor.user)

    url = reverse("vendor-stock-movements-list")

    response = api_client.get(url)

    assert response.status_code == status.HTTP_200_OK

    results = get_results(response)

    assert len(results) == 1
    assert results[0]["id"] == str(own_movement.id)
    assert results[0]["reference"] == "OWN-001"


def test_vendor_can_retrieve_own_stock_movement(api_client):
    vendor = ApprovedVendorFactory()
    product = ProductFactory(vendor=vendor)

    record = InventoryRecordFactory(product=product)

    movement = record.increase_stock(
        5,
        reason="Own movement",
        reference="OWN-MOVE-001",
        created_by=vendor.user,
    )

    api_client.force_authenticate(user=vendor.user)

    url = reverse(
        "vendor-stock-movements-detail",
        kwargs={"pk": movement.id},
    )

    response = api_client.get(url)

    assert response.status_code == status.HTTP_200_OK
    assert response.data["id"] == str(movement.id)
    assert response.data["reference"] == "OWN-MOVE-001"


def test_vendor_cannot_retrieve_other_vendor_stock_movement(api_client):
    own_vendor = ApprovedVendorFactory()
    other_vendor = ApprovedVendorFactory()

    other_product = ProductFactory(vendor=other_vendor)
    other_record = InventoryRecordFactory(product=other_product)

    movement = other_record.increase_stock(
        5,
        reference="OTHER-MOVE-001",
        created_by=other_vendor.user,
    )

    api_client.force_authenticate(user=own_vendor.user)

    url = reverse(
        "vendor-stock-movements-detail",
        kwargs={"pk": movement.id},
    )

    response = api_client.get(url)

    assert response.status_code == status.HTTP_404_NOT_FOUND


def test_admin_can_list_inventory_records(api_client):
    admin = AdminUserFactory()
    record = InventoryRecordFactory()

    api_client.force_authenticate(user=admin)

    url = reverse("admin-inventory-records-list")

    response = api_client.get(url)

    assert response.status_code == status.HTTP_200_OK

    results = get_results(response)

    assert len(results) == 1
    assert results[0]["id"] == str(record.id)


def test_non_admin_cannot_access_admin_inventory_records(api_client):
    vendor_user = VendorUserFactory()
    api_client.force_authenticate(user=vendor_user)

    url = reverse("admin-inventory-records-list")

    response = api_client.get(url)

    assert response.status_code == status.HTTP_403_FORBIDDEN


def test_admin_can_retrieve_inventory_record(api_client):
    admin = AdminUserFactory()
    record = InventoryRecordFactory()

    api_client.force_authenticate(user=admin)

    url = reverse(
        "admin-inventory-records-detail",
        kwargs={"pk": record.id},
    )

    response = api_client.get(url)

    assert response.status_code == status.HTTP_200_OK
    assert response.data["id"] == str(record.id)


def test_admin_can_increase_stock(api_client):
    admin = AdminUserFactory()
    record = InventoryRecordFactory(
        quantity_on_hand=10,
        quantity_reserved=0,
    )

    api_client.force_authenticate(user=admin)

    url = reverse(
        "admin-inventory-records-increase-stock",
        kwargs={"pk": record.id},
    )

    response = api_client.post(
        url,
        stock_operation_payload(
            quantity=15,
            reason="Admin restock",
            reference="ADMIN-IN-001",
        ),
        format="json",
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.data["quantity_on_hand"] == 25

    record.refresh_from_db()

    movement = record.movements.first()

    assert movement.movement_type == StockMovement.MovementType.IN
    assert movement.created_by == admin


def test_admin_can_decrease_stock(api_client):
    admin = AdminUserFactory()
    record = InventoryRecordFactory(
        quantity_on_hand=20,
        quantity_reserved=5,
    )

    api_client.force_authenticate(user=admin)

    url = reverse(
        "admin-inventory-records-decrease-stock",
        kwargs={"pk": record.id},
    )

    response = api_client.post(
        url,
        stock_operation_payload(quantity=5),
        format="json",
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.data["quantity_on_hand"] == 15

    record.refresh_from_db()

    assert record.quantity_on_hand == 15


def test_admin_can_reserve_stock(api_client):
    admin = AdminUserFactory()
    record = InventoryRecordFactory(
        quantity_on_hand=20,
        quantity_reserved=2,
    )

    api_client.force_authenticate(user=admin)

    url = reverse(
        "admin-inventory-records-reserve-stock",
        kwargs={"pk": record.id},
    )

    response = api_client.post(
        url,
        stock_operation_payload(
            quantity=5,
            reason="Admin reserve",
            reference="ADMIN-RESERVE-001",
        ),
        format="json",
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.data["quantity_on_hand"] == 20
    assert response.data["quantity_reserved"] == 7
    assert response.data["available_quantity"] == 13

    record.refresh_from_db()

    movement = record.movements.first()

    assert movement.movement_type == StockMovement.MovementType.RESERVE
    assert movement.created_by == admin


def test_admin_reserve_stock_cannot_exceed_available_quantity(api_client):
    admin = AdminUserFactory()
    record = InventoryRecordFactory(
        quantity_on_hand=10,
        quantity_reserved=8,
    )

    api_client.force_authenticate(user=admin)

    url = reverse(
        "admin-inventory-records-reserve-stock",
        kwargs={"pk": record.id},
    )

    response = api_client.post(
        url,
        stock_operation_payload(quantity=3),
        format="json",
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST

    record.refresh_from_db()

    assert record.quantity_reserved == 8
    assert record.movements.count() == 0


def test_admin_can_release_reservation(api_client):
    admin = AdminUserFactory()
    record = InventoryRecordFactory(
        quantity_on_hand=20,
        quantity_reserved=8,
    )

    api_client.force_authenticate(user=admin)

    url = reverse(
        "admin-inventory-records-release-reservation",
        kwargs={"pk": record.id},
    )

    response = api_client.post(
        url,
        stock_operation_payload(
            quantity=3,
            reason="Admin release",
            reference="ADMIN-RELEASE-001",
        ),
        format="json",
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.data["quantity_reserved"] == 5
    assert response.data["available_quantity"] == 15

    record.refresh_from_db()

    movement = record.movements.first()

    assert movement.movement_type == StockMovement.MovementType.RELEASE
    assert movement.created_by == admin


def test_admin_release_reservation_cannot_exceed_reserved_quantity(api_client):
    admin = AdminUserFactory()
    record = InventoryRecordFactory(
        quantity_on_hand=20,
        quantity_reserved=2,
    )

    api_client.force_authenticate(user=admin)

    url = reverse(
        "admin-inventory-records-release-reservation",
        kwargs={"pk": record.id},
    )

    response = api_client.post(
        url,
        stock_operation_payload(quantity=3),
        format="json",
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST

    record.refresh_from_db()

    assert record.quantity_reserved == 2
    assert record.movements.count() == 0


def test_admin_can_commit_reservation(api_client):
    admin = AdminUserFactory()
    record = InventoryRecordFactory(
        quantity_on_hand=20,
        quantity_reserved=8,
    )

    api_client.force_authenticate(user=admin)

    url = reverse(
        "admin-inventory-records-commit-reservation",
        kwargs={"pk": record.id},
    )

    response = api_client.post(
        url,
        stock_operation_payload(
            quantity=5,
            reason="Order completed",
            reference="ORDER-001",
        ),
        format="json",
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.data["quantity_on_hand"] == 15
    assert response.data["quantity_reserved"] == 3
    assert response.data["available_quantity"] == 12

    record.refresh_from_db()

    movement = record.movements.first()

    assert movement.movement_type == StockMovement.MovementType.SALE
    assert movement.created_by == admin


def test_admin_commit_reservation_cannot_exceed_reserved_quantity(api_client):
    admin = AdminUserFactory()
    record = InventoryRecordFactory(
        quantity_on_hand=20,
        quantity_reserved=2,
    )

    api_client.force_authenticate(user=admin)

    url = reverse(
        "admin-inventory-records-commit-reservation",
        kwargs={"pk": record.id},
    )

    response = api_client.post(
        url,
        stock_operation_payload(quantity=3),
        format="json",
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST

    record.refresh_from_db()

    assert record.quantity_on_hand == 20
    assert record.quantity_reserved == 2
    assert record.movements.count() == 0


def test_admin_can_list_stock_movements(api_client):
    admin = AdminUserFactory()
    record = InventoryRecordFactory()

    movement = record.increase_stock(
        5,
        reason="Admin visible movement",
        reference="ADMIN-MOVE-001",
        created_by=admin,
    )

    api_client.force_authenticate(user=admin)

    url = reverse("admin-stock-movements-list")

    response = api_client.get(url)

    assert response.status_code == status.HTTP_200_OK

    results = get_results(response)

    assert len(results) == 1
    assert results[0]["id"] == str(movement.id)
    assert results[0]["reference"] == "ADMIN-MOVE-001"


def test_admin_can_retrieve_stock_movement(api_client):
    admin = AdminUserFactory()
    record = InventoryRecordFactory()

    movement = record.increase_stock(
        5,
        reference="ADMIN-MOVE-DETAIL-001",
        created_by=admin,
    )

    api_client.force_authenticate(user=admin)

    url = reverse(
        "admin-stock-movements-detail",
        kwargs={"pk": movement.id},
    )

    response = api_client.get(url)

    assert response.status_code == status.HTTP_200_OK
    assert response.data["id"] == str(movement.id)
    assert response.data["reference"] == "ADMIN-MOVE-DETAIL-001"


def test_non_admin_cannot_access_admin_stock_movements(api_client):
    customer = CustomerUserFactory()
    api_client.force_authenticate(user=customer)

    url = reverse("admin-stock-movements-list")

    response = api_client.get(url)

    assert response.status_code == status.HTTP_403_FORBIDDEN


def test_inventory_schema_contains_inventory_endpoints(api_client):
    url = reverse("schema")

    response = api_client.get(url)

    assert response.status_code == status.HTTP_200_OK

    content = response.content.decode()

    assert "/api/v1/inventory/vendor/records/" in content
    assert "/api/v1/inventory/vendor/records/{id}/increase-stock/" in content
    assert "/api/v1/inventory/vendor/records/{id}/decrease-stock/" in content
    assert "/api/v1/inventory/vendor/movements/" in content

    assert "/api/v1/inventory/admin/records/" in content
    assert "/api/v1/inventory/admin/records/{id}/increase-stock/" in content
    assert "/api/v1/inventory/admin/records/{id}/decrease-stock/" in content
    assert "/api/v1/inventory/admin/records/{id}/reserve-stock/" in content
    assert "/api/v1/inventory/admin/records/{id}/release-reservation/" in content
    assert "/api/v1/inventory/admin/records/{id}/commit-reservation/" in content
    assert "/api/v1/inventory/admin/movements/" in content