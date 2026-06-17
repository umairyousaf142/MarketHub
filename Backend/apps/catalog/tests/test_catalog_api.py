from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse
from rest_framework import status

from apps.accounts.tests.factories import (
    AdminUserFactory,
    CustomerUserFactory,
    VendorUserFactory,
)
from apps.catalog.models import Brand, Category, Product, ProductImage, ProductVariant
from apps.catalog.tests.factories import (
    ApprovedVendorFactory,
    BrandFactory,
    CategoryFactory,
    PendingVendorFactory,
    ProductFactory,
    ProductImageFactory,
    ProductVariantFactory,
)


pytestmark = pytest.mark.django_db


def get_results(response):
    if isinstance(response.data, dict) and "results" in response.data:
        return response.data["results"]

    return response.data


def get_error_details(response):
    if isinstance(response.data, dict) and "error" in response.data:
        return response.data["error"].get("details", {})

    return response.data


def product_payload(category, brand=None, **overrides):
    data = {
        "category": str(category.id),
        "brand": str(brand.id) if brand else None,
        "name": "Test API Product",
        "sku": "API-PRODUCT-001",
        "short_description": "Short API product description",
        "description": "Long API product description",
        "base_price": "100.00",
        "status": Product.Status.DRAFT,
    }

    data.update(overrides)

    return data


def make_image_file(name="product.jpg"):
    return SimpleUploadedFile(
        name,
        b"fake-image-content",
        content_type="image/jpeg",
    )


def test_public_category_list_returns_only_active_categories(api_client):
    active_category = CategoryFactory(name="Active Category", is_active=True)
    CategoryFactory(name="Inactive Category", is_active=False)

    url = reverse("public-categories-list")

    response = api_client.get(url)

    assert response.status_code == status.HTTP_200_OK

    results = get_results(response)

    assert len(results) == 1
    assert results[0]["id"] == str(active_category.id)
    assert results[0]["slug"] == active_category.slug


def test_public_category_detail_by_slug(api_client):
    category = CategoryFactory(name="Mobile Phones", is_active=True)

    url = reverse(
        "public-categories-detail",
        kwargs={"slug": category.slug},
    )

    response = api_client.get(url)

    assert response.status_code == status.HTTP_200_OK
    assert response.data["id"] == str(category.id)
    assert response.data["slug"] == "mobile-phones"


def test_public_brand_list_returns_only_active_brands(api_client):
    active_brand = BrandFactory(name="Active Brand", is_active=True)
    BrandFactory(name="Inactive Brand", is_active=False)

    url = reverse("public-brands-list")

    response = api_client.get(url)

    assert response.status_code == status.HTTP_200_OK

    results = get_results(response)

    assert len(results) == 1
    assert results[0]["id"] == str(active_brand.id)
    assert results[0]["slug"] == active_brand.slug


def test_public_brand_detail_by_slug(api_client):
    brand = BrandFactory(name="Apple Brand", is_active=True)

    url = reverse(
        "public-brands-detail",
        kwargs={"slug": brand.slug},
    )

    response = api_client.get(url)

    assert response.status_code == status.HTTP_200_OK
    assert response.data["id"] == str(brand.id)
    assert response.data["slug"] == "apple-brand"


def test_public_product_list_returns_only_active_products(api_client):
    active_product = ProductFactory(
        name="Public Active Product",
        status=Product.Status.ACTIVE,
    )

    ProductFactory(
        name="Draft Product",
        status=Product.Status.DRAFT,
    )

    url = reverse("public-products-list")

    response = api_client.get(url)

    assert response.status_code == status.HTTP_200_OK

    results = get_results(response)

    assert len(results) == 1
    assert results[0]["id"] == str(active_product.id)
    assert results[0]["slug"] == active_product.slug


def test_public_product_detail_by_slug_includes_images_and_active_variants(api_client):
    product = ProductFactory(
        name="Detailed Product",
        status=Product.Status.ACTIVE,
    )

    ProductImageFactory(
        product=product,
        is_primary=True,
    )

    active_variant = ProductVariantFactory(
        product=product,
        name="Active Variant",
        sku="ACTIVE-VAR-001",
        is_active=True,
    )

    ProductVariantFactory(
        product=product,
        name="Inactive Variant",
        sku="INACTIVE-VAR-001",
        is_active=False,
    )

    url = reverse(
        "public-products-detail",
        kwargs={"slug": product.slug},
    )

    response = api_client.get(url)

    assert response.status_code == status.HTTP_200_OK
    assert response.data["id"] == str(product.id)
    assert response.data["slug"] == product.slug
    assert len(response.data["images"]) == 1
    assert len(response.data["variants"]) == 1
    assert response.data["variants"][0]["id"] == str(active_variant.id)


def test_public_product_filters_work(api_client):
    category = CategoryFactory(name="Phones", is_active=True)
    brand = BrandFactory(name="Apple", is_active=True)

    matching_product = ProductFactory(
        name="iPhone 15",
        category=category,
        brand=brand,
        base_price=Decimal("999.00"),
        status=Product.Status.ACTIVE,
        is_featured=True,
    )

    ProductFactory(
        name="Samsung Phone",
        base_price=Decimal("300.00"),
        status=Product.Status.ACTIVE,
        is_featured=False,
    )

    url = reverse("public-products-list")

    response = api_client.get(
        url,
        {
            "search": "iphone",
            "category": category.slug,
            "brand": brand.slug,
            "featured": "true",
            "min_price": "900",
            "max_price": "1200",
        },
    )

    assert response.status_code == status.HTTP_200_OK

    results = get_results(response)

    assert len(results) == 1
    assert results[0]["id"] == str(matching_product.id)


def test_vendor_product_list_requires_authentication(api_client):
    url = reverse("vendor-products-list")

    response = api_client.get(url)

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_pending_vendor_cannot_create_product(api_client):
    pending_vendor = PendingVendorFactory()
    category = CategoryFactory()
    brand = BrandFactory()

    api_client.force_authenticate(user=pending_vendor.user)

    url = reverse("vendor-products-list")

    response = api_client.post(
        url,
        product_payload(category, brand),
        format="json",
    )

    assert response.status_code == status.HTTP_403_FORBIDDEN


def test_approved_vendor_can_create_product(api_client):
    vendor = ApprovedVendorFactory()
    category = CategoryFactory()
    brand = BrandFactory()

    api_client.force_authenticate(user=vendor.user)

    url = reverse("vendor-products-list")

    response = api_client.post(
        url,
        product_payload(
            category,
            brand,
            name="Vendor API Product",
            sku="VENDOR-API-001",
        ),
        format="json",
    )

    assert response.status_code == status.HTTP_201_CREATED
    assert response.data["name"] == "Vendor API Product"
    assert response.data["sku"] == "VENDOR-API-001"
    assert response.data["status"] == Product.Status.DRAFT

    product = Product.objects.get(id=response.data["id"])

    assert product.vendor == vendor


def test_vendor_cannot_set_product_status_to_active(api_client):
    vendor = ApprovedVendorFactory()
    category = CategoryFactory()
    brand = BrandFactory()

    api_client.force_authenticate(user=vendor.user)

    url = reverse("vendor-products-list")

    response = api_client.post(
        url,
        product_payload(
            category,
            brand,
            status=Product.Status.ACTIVE,
        ),
        format="json",
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST

    details = get_error_details(response)

    assert "status" in details


def test_vendor_product_list_only_returns_own_products(api_client):
    own_vendor = ApprovedVendorFactory()
    other_vendor = ApprovedVendorFactory()

    own_product = ProductFactory(
        vendor=own_vendor,
        name="Own Product",
    )

    ProductFactory(
        vendor=other_vendor,
        name="Other Product",
    )

    api_client.force_authenticate(user=own_vendor.user)

    url = reverse("vendor-products-list")

    response = api_client.get(url)

    assert response.status_code == status.HTTP_200_OK

    results = get_results(response)

    assert len(results) == 1
    assert results[0]["id"] == str(own_product.id)


def test_vendor_can_update_own_product(api_client):
    vendor = ApprovedVendorFactory()
    product = ProductFactory(
        vendor=vendor,
        name="Old Product Name",
        base_price=Decimal("100.00"),
    )

    api_client.force_authenticate(user=vendor.user)

    url = reverse(
        "vendor-products-detail",
        kwargs={"pk": product.id},
    )

    response = api_client.patch(
        url,
        {
            "name": "Updated Product Name",
            "base_price": "120.00",
        },
        format="json",
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.data["name"] == "Updated Product Name"
    assert response.data["base_price"] == "120.00"

    product.refresh_from_db()

    assert product.name == "Updated Product Name"
    assert product.base_price == Decimal("120.00")


def test_vendor_cannot_retrieve_other_vendor_product(api_client):
    own_vendor = ApprovedVendorFactory()
    other_vendor = ApprovedVendorFactory()

    other_product = ProductFactory(vendor=other_vendor)

    api_client.force_authenticate(user=own_vendor.user)

    url = reverse(
        "vendor-products-detail",
        kwargs={"pk": other_product.id},
    )

    response = api_client.get(url)

    assert response.status_code == status.HTTP_404_NOT_FOUND


def test_vendor_can_submit_product_for_review(api_client):
    vendor = ApprovedVendorFactory()

    product = ProductFactory(
        vendor=vendor,
        status=Product.Status.DRAFT,
    )

    api_client.force_authenticate(user=vendor.user)

    url = reverse(
        "vendor-products-submit-for-review",
        kwargs={"pk": product.id},
    )

    response = api_client.post(url)

    assert response.status_code == status.HTTP_200_OK
    assert response.data["status"] == Product.Status.PENDING_REVIEW

    product.refresh_from_db()

    assert product.status == Product.Status.PENDING_REVIEW


def test_vendor_submit_for_review_invalid_status_returns_400(api_client):
    vendor = ApprovedVendorFactory()

    product = ProductFactory(
        vendor=vendor,
        status=Product.Status.PENDING_REVIEW,
    )

    api_client.force_authenticate(user=vendor.user)

    url = reverse(
        "vendor-products-submit-for-review",
        kwargs={"pk": product.id},
    )

    response = api_client.post(url)

    assert response.status_code == status.HTTP_400_BAD_REQUEST


def test_vendor_delete_archives_product(api_client):
    vendor = ApprovedVendorFactory()

    product = ProductFactory(
        vendor=vendor,
        status=Product.Status.DRAFT,
    )

    api_client.force_authenticate(user=vendor.user)

    url = reverse(
        "vendor-products-detail",
        kwargs={"pk": product.id},
    )

    response = api_client.delete(url)

    assert response.status_code == status.HTTP_204_NO_CONTENT

    product.refresh_from_db()

    assert product.status == Product.Status.ARCHIVED


def test_vendor_can_upload_product_image(api_client, tmp_path):
    vendor = ApprovedVendorFactory()
    product = ProductFactory(vendor=vendor)

    api_client.force_authenticate(user=vendor.user)

    url = reverse(
        "vendor-product-images-list",
        kwargs={"product_id": product.id},
    )

    with override_settings(MEDIA_ROOT=tmp_path):
        response = api_client.post(
            url,
            {
                "file": make_image_file(),
                "alt_text": "Front image",
                "is_primary": True,
                "sort_order": 1,
            },
            format="multipart",
        )

    assert response.status_code == status.HTTP_201_CREATED
    assert response.data["alt_text"] == "Front image"
    assert response.data["is_primary"] is True
    assert ProductImage.objects.filter(product=product).count() == 1


def test_vendor_product_images_list_returns_product_images(api_client):
    vendor = ApprovedVendorFactory()
    product = ProductFactory(vendor=vendor)
    other_product = ProductFactory(vendor=vendor)

    image = ProductImageFactory(product=product)
    ProductImageFactory(product=other_product)

    api_client.force_authenticate(user=vendor.user)

    url = reverse(
        "vendor-product-images-list",
        kwargs={"product_id": product.id},
    )

    response = api_client.get(url)

    assert response.status_code == status.HTTP_200_OK

    results = get_results(response)

    assert len(results) == 1
    assert results[0]["id"] == str(image.id)


def test_vendor_cannot_access_images_for_other_vendor_product(api_client):
    own_vendor = ApprovedVendorFactory()
    other_vendor = ApprovedVendorFactory()

    other_product = ProductFactory(vendor=other_vendor)

    api_client.force_authenticate(user=own_vendor.user)

    url = reverse(
        "vendor-product-images-list",
        kwargs={"product_id": other_product.id},
    )

    response = api_client.get(url)

    assert response.status_code == status.HTTP_404_NOT_FOUND


def test_product_image_upload_rejects_invalid_extension(api_client, tmp_path):
    vendor = ApprovedVendorFactory()
    product = ProductFactory(vendor=vendor)

    api_client.force_authenticate(user=vendor.user)

    file = SimpleUploadedFile(
        "image.exe",
        b"fake-content",
        content_type="application/octet-stream",
    )

    url = reverse(
        "vendor-product-images-list",
        kwargs={"product_id": product.id},
    )

    with override_settings(MEDIA_ROOT=tmp_path):
        response = api_client.post(
            url,
            {
                "file": file,
                "alt_text": "Invalid image",
                "is_primary": False,
            },
            format="multipart",
        )

    assert response.status_code == status.HTTP_400_BAD_REQUEST

    details = get_error_details(response)

    assert "file" in details


def test_product_image_primary_switches_previous_primary(api_client, tmp_path):
    vendor = ApprovedVendorFactory()
    product = ProductFactory(vendor=vendor)

    first_image = ProductImageFactory(
        product=product,
        is_primary=True,
    )

    api_client.force_authenticate(user=vendor.user)

    url = reverse(
        "vendor-product-images-list",
        kwargs={"product_id": product.id},
    )

    with override_settings(MEDIA_ROOT=tmp_path):
        response = api_client.post(
            url,
            {
                "file": make_image_file("second.jpg"),
                "alt_text": "Second image",
                "is_primary": True,
            },
            format="multipart",
        )

    assert response.status_code == status.HTTP_201_CREATED

    first_image.refresh_from_db()

    second_image = ProductImage.objects.get(id=response.data["id"])

    assert first_image.is_primary is False
    assert second_image.is_primary is True


def test_vendor_can_create_product_variant(api_client):
    vendor = ApprovedVendorFactory()
    product = ProductFactory(vendor=vendor)

    api_client.force_authenticate(user=vendor.user)

    url = reverse(
        "vendor-product-variants-list",
        kwargs={"product_id": product.id},
    )

    response = api_client.post(
        url,
        {
            "name": "128GB Black",
            "sku": "VAR-128-BLK",
            "price": "150.00",
            "attributes": {
                "storage": "128GB",
                "color": "Black",
            },
            "is_default": True,
            "is_active": True,
            "sort_order": 1,
        },
        format="json",
    )

    assert response.status_code == status.HTTP_201_CREATED
    assert response.data["name"] == "128GB Black"
    assert response.data["sku"] == "VAR-128-BLK"
    assert response.data["is_default"] is True
    assert ProductVariant.objects.filter(product=product).count() == 1


def test_vendor_product_variants_list_returns_product_variants(api_client):
    vendor = ApprovedVendorFactory()
    product = ProductFactory(vendor=vendor)
    other_product = ProductFactory(vendor=vendor)

    variant = ProductVariantFactory(product=product)
    ProductVariantFactory(product=other_product)

    api_client.force_authenticate(user=vendor.user)

    url = reverse(
        "vendor-product-variants-list",
        kwargs={"product_id": product.id},
    )

    response = api_client.get(url)

    assert response.status_code == status.HTTP_200_OK

    results = get_results(response)

    assert len(results) == 1
    assert results[0]["id"] == str(variant.id)


def test_vendor_cannot_access_variants_for_other_vendor_product(api_client):
    own_vendor = ApprovedVendorFactory()
    other_vendor = ApprovedVendorFactory()

    other_product = ProductFactory(vendor=other_vendor)

    api_client.force_authenticate(user=own_vendor.user)

    url = reverse(
        "vendor-product-variants-list",
        kwargs={"product_id": other_product.id},
    )

    response = api_client.get(url)

    assert response.status_code == status.HTTP_404_NOT_FOUND


def test_vendor_variant_duplicate_sku_returns_400(api_client):
    vendor = ApprovedVendorFactory()
    product = ProductFactory(vendor=vendor)

    ProductVariantFactory(
        product=product,
        sku="VAR-DUPLICATE",
    )

    api_client.force_authenticate(user=vendor.user)

    url = reverse(
        "vendor-product-variants-list",
        kwargs={"product_id": product.id},
    )

    response = api_client.post(
        url,
        {
            "name": "Duplicate Variant",
            "sku": "var-duplicate",
            "price": "120.00",
            "attributes": {},
            "is_default": False,
            "is_active": True,
        },
        format="json",
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST

    details = get_error_details(response)

    assert "sku" in details


def test_vendor_variant_attributes_must_be_json_object(api_client):
    vendor = ApprovedVendorFactory()
    product = ProductFactory(vendor=vendor)

    api_client.force_authenticate(user=vendor.user)

    url = reverse(
        "vendor-product-variants-list",
        kwargs={"product_id": product.id},
    )

    response = api_client.post(
        url,
        {
            "name": "Invalid Attributes",
            "sku": "VAR-INVALID-ATTRS",
            "price": "120.00",
            "attributes": ["invalid", "list"],
            "is_default": False,
            "is_active": True,
        },
        format="json",
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST

    details = get_error_details(response)

    assert "attributes" in details


def test_vendor_setting_default_variant_switches_previous_default(api_client):
    vendor = ApprovedVendorFactory()
    product = ProductFactory(vendor=vendor)

    first_variant = ProductVariantFactory(
        product=product,
        sku="VAR-FIRST",
        is_default=True,
    )

    api_client.force_authenticate(user=vendor.user)

    url = reverse(
        "vendor-product-variants-list",
        kwargs={"product_id": product.id},
    )

    response = api_client.post(
        url,
        {
            "name": "Second Variant",
            "sku": "VAR-SECOND",
            "price": "130.00",
            "attributes": {},
            "is_default": True,
            "is_active": True,
        },
        format="json",
    )

    assert response.status_code == status.HTTP_201_CREATED

    first_variant.refresh_from_db()

    second_variant = ProductVariant.objects.get(id=response.data["id"])

    assert first_variant.is_default is False
    assert second_variant.is_default is True


def test_admin_can_create_category(api_client):
    admin = AdminUserFactory()
    api_client.force_authenticate(user=admin)

    url = reverse("admin-categories-list")

    response = api_client.post(
        url,
        {
            "name": "Admin Electronics",
            "description": "Admin category",
            "is_active": True,
            "sort_order": 1,
        },
        format="json",
    )

    assert response.status_code == status.HTTP_201_CREATED
    assert response.data["name"] == "Admin Electronics"
    assert response.data["slug"] == "admin-electronics"


def test_non_admin_cannot_create_category(api_client):
    vendor_user = VendorUserFactory()
    api_client.force_authenticate(user=vendor_user)

    url = reverse("admin-categories-list")

    response = api_client.post(
        url,
        {
            "name": "Blocked Category",
            "is_active": True,
        },
        format="json",
    )

    assert response.status_code == status.HTTP_403_FORBIDDEN


def test_admin_duplicate_category_name_returns_400(api_client):
    admin = AdminUserFactory()
    CategoryFactory(name="Duplicate Category")

    api_client.force_authenticate(user=admin)

    url = reverse("admin-categories-list")

    response = api_client.post(
        url,
        {
            "name": "duplicate category",
            "is_active": True,
        },
        format="json",
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST

    details = get_error_details(response)

    assert "name" in details


def test_admin_can_create_brand(api_client):
    admin = AdminUserFactory()
    api_client.force_authenticate(user=admin)

    url = reverse("admin-brands-list")

    response = api_client.post(
        url,
        {
            "name": "Admin Apple",
            "description": "Admin brand",
            "is_active": True,
        },
        format="json",
    )

    assert response.status_code == status.HTTP_201_CREATED
    assert response.data["name"] == "Admin Apple"
    assert response.data["slug"] == "admin-apple"


def test_non_admin_cannot_create_brand(api_client):
    customer = CustomerUserFactory()
    api_client.force_authenticate(user=customer)

    url = reverse("admin-brands-list")

    response = api_client.post(
        url,
        {
            "name": "Blocked Brand",
            "is_active": True,
        },
        format="json",
    )

    assert response.status_code == status.HTTP_403_FORBIDDEN


def test_admin_can_list_products(api_client):
    admin = AdminUserFactory()
    product = ProductFactory(name="Admin Listed Product")

    api_client.force_authenticate(user=admin)

    url = reverse("admin-products-list")

    response = api_client.get(url)

    assert response.status_code == status.HTTP_200_OK

    results = get_results(response)

    assert len(results) == 1
    assert results[0]["id"] == str(product.id)
    assert results[0]["name"] == "Admin Listed Product"


def test_non_admin_cannot_list_admin_products(api_client):
    vendor_user = VendorUserFactory()
    api_client.force_authenticate(user=vendor_user)

    url = reverse("admin-products-list")

    response = api_client.get(url)

    assert response.status_code == status.HTTP_403_FORBIDDEN


def test_admin_can_approve_pending_review_product(api_client):
    admin = AdminUserFactory()

    product = ProductFactory(
        status=Product.Status.PENDING_REVIEW,
    )

    api_client.force_authenticate(user=admin)

    url = reverse(
        "admin-products-approve",
        kwargs={"pk": product.id},
    )

    response = api_client.post(url)

    assert response.status_code == status.HTTP_200_OK
    assert response.data["status"] == Product.Status.ACTIVE

    product.refresh_from_db()

    assert product.status == Product.Status.ACTIVE


def test_admin_approve_invalid_transition_returns_400(api_client):
    admin = AdminUserFactory()

    product = ProductFactory(
        status=Product.Status.DRAFT,
    )

    api_client.force_authenticate(user=admin)

    url = reverse(
        "admin-products-approve",
        kwargs={"pk": product.id},
    )

    response = api_client.post(url)

    assert response.status_code == status.HTTP_400_BAD_REQUEST


def test_admin_can_reject_pending_review_product(api_client):
    admin = AdminUserFactory()

    product = ProductFactory(
        status=Product.Status.PENDING_REVIEW,
    )

    api_client.force_authenticate(user=admin)

    url = reverse(
        "admin-products-reject",
        kwargs={"pk": product.id},
    )

    response = api_client.post(url)

    assert response.status_code == status.HTTP_200_OK
    assert response.data["status"] == Product.Status.REJECTED

    product.refresh_from_db()

    assert product.status == Product.Status.REJECTED


def test_admin_can_archive_product(api_client):
    admin = AdminUserFactory()

    product = ProductFactory(
        status=Product.Status.ACTIVE,
    )

    api_client.force_authenticate(user=admin)

    url = reverse(
        "admin-products-archive",
        kwargs={"pk": product.id},
    )

    response = api_client.post(url)

    assert response.status_code == status.HTTP_200_OK
    assert response.data["status"] == Product.Status.ARCHIVED

    product.refresh_from_db()

    assert product.status == Product.Status.ARCHIVED


def test_catalog_schema_contains_catalog_endpoints(api_client):
    url = reverse("schema")

    response = api_client.get(url)

    assert response.status_code == status.HTTP_200_OK

    content = response.content.decode()

    assert "/api/v1/catalog/categories/" in content
    assert "/api/v1/catalog/brands/" in content
    assert "/api/v1/catalog/products/" in content

    assert "/api/v1/catalog/vendor/products/" in content
    assert "/api/v1/catalog/vendor/products/{id}/submit-for-review/" in content
    assert "/api/v1/catalog/vendor/products/{product_id}/images/" in content
    assert "/api/v1/catalog/vendor/products/{product_id}/variants/" in content

    assert "/api/v1/catalog/admin/categories/" in content
    assert "/api/v1/catalog/admin/brands/" in content
    assert "/api/v1/catalog/admin/products/" in content
    assert "/api/v1/catalog/admin/products/{id}/approve/" in content
    assert "/api/v1/catalog/admin/products/{id}/reject/" in content
    assert "/api/v1/catalog/admin/products/{id}/archive/" in content