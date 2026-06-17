from decimal import Decimal

import factory
from django.utils import timezone

from apps.accounts.tests.factories import AdminUserFactory, VendorUserFactory
from apps.catalog.models import (
    Brand,
    Category,
    Product,
    ProductImage,
    ProductVariant,
)
from apps.vendors.models import Vendor


class CategoryFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Category

    name = factory.Sequence(lambda n: f"Category {n}")
    description = "Test category description"
    parent = None
    is_active = True
    sort_order = 0


class BrandFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Brand

    name = factory.Sequence(lambda n: f"Brand {n}")
    description = "Test brand description"
    is_active = True


class ApprovedVendorFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Vendor

    user = factory.SubFactory(VendorUserFactory)
    store_name = factory.Sequence(lambda n: f"Approved Vendor Store {n}")
    status = Vendor.Status.APPROVED
    approved_at = factory.LazyFunction(timezone.now)
    approved_by = factory.SubFactory(AdminUserFactory)
    commission_plan = None


class PendingVendorFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Vendor

    user = factory.SubFactory(VendorUserFactory)
    store_name = factory.Sequence(lambda n: f"Pending Vendor Store {n}")
    status = Vendor.Status.PENDING
    approved_at = None
    approved_by = None
    commission_plan = None


class ProductFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Product

    vendor = factory.SubFactory(ApprovedVendorFactory)
    category = factory.SubFactory(CategoryFactory)
    brand = factory.SubFactory(BrandFactory)

    name = factory.Sequence(lambda n: f"Product {n}")
    sku = factory.Sequence(lambda n: f"SKU-{n}")
    short_description = "Short product description"
    description = "Long product description"
    base_price = Decimal("100.00")
    status = Product.Status.DRAFT
    is_featured = False


class ProductImageFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ProductImage

    product = factory.SubFactory(ProductFactory)
    file = "catalog/products/test-product-image.jpg"
    alt_text = "Product image"
    is_primary = False
    sort_order = 0


class ProductVariantFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ProductVariant

    product = factory.SubFactory(ProductFactory)
    name = factory.Sequence(lambda n: f"Variant {n}")
    sku = factory.Sequence(lambda n: f"VAR-SKU-{n}")
    price = Decimal("100.00")
    attributes = {"size": "M", "color": "Black"}
    is_default = False
    is_active = True
    sort_order = 0