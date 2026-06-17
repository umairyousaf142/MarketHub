from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from apps.catalog.models import Brand, Category, Product, ProductImage, ProductVariant
from apps.vendors.models import Vendor

from .factories import (
    ApprovedVendorFactory,
    BrandFactory,
    CategoryFactory,
    PendingVendorFactory,
    ProductFactory,
    ProductImageFactory,
    ProductVariantFactory,
)


pytestmark = pytest.mark.django_db


def test_category_slug_is_generated_from_name():
    category = CategoryFactory(name="Mobile Phones")

    assert category.slug == "mobile-phones"
    assert str(category) == "Mobile Phones"


def test_category_name_is_case_insensitive_unique():
    CategoryFactory(name="Electronics")

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            CategoryFactory(name="electronics")


def test_category_cannot_be_own_parent():
    category = CategoryFactory(name="Parent Category")

    category.parent = category

    with pytest.raises(ValidationError):
        category.save()


def test_category_circular_hierarchy_is_not_allowed():
    parent = CategoryFactory(name="Parent")
    child = CategoryFactory(name="Child", parent=parent)

    parent.parent = child

    with pytest.raises(ValidationError):
        parent.save()


def test_brand_slug_is_generated_from_name():
    brand = BrandFactory(name="Apple Brand")

    assert brand.slug == "apple-brand"
    assert str(brand) == "Apple Brand"


def test_brand_name_is_case_insensitive_unique():
    BrandFactory(name="Nike")

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            BrandFactory(name="nike")


def test_product_can_be_created():
    product = ProductFactory(
        name="Test Product",
        sku="TEST-SKU-001",
        base_price=Decimal("99.99"),
    )

    assert product.name == "Test Product"
    assert product.sku == "TEST-SKU-001"
    assert product.base_price == Decimal("99.99")
    assert product.status == Product.Status.DRAFT
    assert product.slug == "test-product"
    assert str(product) == "Test Product"


def test_product_slug_is_unique_when_names_are_same():
    first_product = ProductFactory(
        name="Same Product",
        sku="SKU-SAME-1",
    )

    second_product = ProductFactory(
        name="Same Product",
        sku="SKU-SAME-2",
    )

    assert first_product.slug == "same-product"
    assert second_product.slug == "same-product-2"


def test_product_sku_must_be_unique_per_vendor_case_insensitive():
    vendor = ApprovedVendorFactory()

    ProductFactory(
        vendor=vendor,
        sku="ABC-123",
    )

    with pytest.raises(ValidationError):
        ProductFactory(
            vendor=vendor,
            sku="abc-123",
        )


def test_same_product_sku_allowed_for_different_vendors():
    first_vendor = ApprovedVendorFactory()
    second_vendor = ApprovedVendorFactory()

    first_product = ProductFactory(
        vendor=first_vendor,
        sku="SHARED-SKU",
    )

    second_product = ProductFactory(
        vendor=second_vendor,
        sku="SHARED-SKU",
    )

    assert first_product.sku == "SHARED-SKU"
    assert second_product.sku == "SHARED-SKU"
    assert Product.objects.count() == 2


def test_product_base_price_cannot_be_negative():
    with pytest.raises(ValidationError):
        ProductFactory(
            base_price=Decimal("-1.00"),
        )


def test_active_product_requires_approved_vendor():
    pending_vendor = PendingVendorFactory()

    with pytest.raises(ValidationError):
        ProductFactory(
            vendor=pending_vendor,
            status=Product.Status.ACTIVE,
        )


def test_active_product_requires_active_category():
    inactive_category = CategoryFactory(
        name="Inactive Category",
        is_active=False,
    )

    with pytest.raises(ValidationError):
        ProductFactory(
            category=inactive_category,
            status=Product.Status.ACTIVE,
        )


def test_active_product_requires_active_brand():
    inactive_brand = BrandFactory(
        name="Inactive Brand",
        is_active=False,
    )

    with pytest.raises(ValidationError):
        ProductFactory(
            brand=inactive_brand,
            status=Product.Status.ACTIVE,
        )


def test_active_product_can_be_created_for_approved_vendor_active_category_and_brand():
    vendor = ApprovedVendorFactory()
    category = CategoryFactory(is_active=True)
    brand = BrandFactory(is_active=True)

    product = ProductFactory(
        vendor=vendor,
        category=category,
        brand=brand,
        status=Product.Status.ACTIVE,
    )

    assert product.status == Product.Status.ACTIVE
    assert product.vendor.status == Vendor.Status.APPROVED
    assert product.category.is_active is True
    assert product.brand.is_active is True


def test_product_image_can_be_created():
    product = ProductFactory(name="Image Product")

    image = ProductImageFactory(
        product=product,
        alt_text="Front image",
        is_primary=False,
    )

    assert image.product == product
    assert image.alt_text == "Front image"
    assert image.is_primary is False
    assert str(image) == "Image Product image"


def test_only_one_primary_image_allowed_per_product():
    product = ProductFactory()

    first_image = ProductImageFactory(
        product=product,
        is_primary=True,
    )

    second_image = ProductImageFactory(
        product=product,
        is_primary=True,
    )

    first_image.refresh_from_db()
    second_image.refresh_from_db()

    assert first_image.is_primary is False
    assert second_image.is_primary is True
    assert ProductImage.objects.filter(product=product, is_primary=True).count() == 1


def test_product_variant_can_be_created():
    product = ProductFactory(name="Variant Product")

    variant = ProductVariantFactory(
        product=product,
        name="Large",
        sku="VAR-LARGE",
        price=Decimal("120.00"),
        attributes={"size": "L"},
    )

    assert variant.product == product
    assert variant.name == "Large"
    assert variant.sku == "VAR-LARGE"
    assert variant.price == Decimal("120.00")
    assert variant.attributes == {"size": "L"}
    assert str(variant) == "Variant Product - Large"


def test_product_variant_price_cannot_be_negative():
    with pytest.raises(ValidationError):
        ProductVariantFactory(
            price=Decimal("-5.00"),
        )


def test_product_variant_sku_must_be_unique_per_product_case_insensitive():
    product = ProductFactory()

    ProductVariantFactory(
        product=product,
        sku="VAR-ABC",
    )

    with pytest.raises(ValidationError):
        ProductVariantFactory(
            product=product,
            sku="var-abc",
        )


def test_same_variant_sku_allowed_for_different_products():
    first_product = ProductFactory()
    second_product = ProductFactory()

    first_variant = ProductVariantFactory(
        product=first_product,
        sku="SHARED-VAR-SKU",
    )

    second_variant = ProductVariantFactory(
        product=second_product,
        sku="SHARED-VAR-SKU",
    )

    assert first_variant.sku == "SHARED-VAR-SKU"
    assert second_variant.sku == "SHARED-VAR-SKU"
    assert ProductVariant.objects.count() == 2


def test_only_one_default_variant_allowed_per_product():
    product = ProductFactory()

    first_variant = ProductVariantFactory(
        product=product,
        sku="VAR-001",
        is_default=True,
    )

    second_variant = ProductVariantFactory(
        product=product,
        sku="VAR-002",
        is_default=True,
    )

    first_variant.refresh_from_db()
    second_variant.refresh_from_db()

    assert first_variant.is_default is False
    assert second_variant.is_default is True
    assert ProductVariant.objects.filter(product=product, is_default=True).count() == 1


def test_product_variant_attributes_must_be_json_object():
    with pytest.raises(ValidationError):
        ProductVariantFactory(
            attributes=["invalid", "list"],
        )


def test_product_variant_attributes_defaults_to_empty_dict_when_none():
    variant = ProductVariantFactory(attributes=None)

    assert variant.attributes == {}