import uuid
from decimal import Decimal, InvalidOperation
from pathlib import Path

from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import Q
from django.db.models.functions import Lower
from django.utils.text import slugify

from apps.vendors.models import Vendor


def generate_unique_slug(instance, value, slug_field="slug", max_length=180):
    base_slug = slugify(value)[:max_length] or "item"
    slug = base_slug
    counter = 2

    model_class = instance.__class__
    queryset = model_class.objects.all()

    if instance.pk:
        queryset = queryset.exclude(pk=instance.pk)

    while queryset.filter(**{f"{slug_field}__iexact": slug}).exists():
        suffix = f"-{counter}"
        slug = f"{base_slug[: max_length - len(suffix)]}{suffix}"
        counter += 1

    return slug


def catalog_product_image_upload_path(instance, filename):
    extension = Path(filename).suffix.lower()
    product_id = instance.product_id or "unassigned"
    return f"catalog/products/{product_id}/{uuid.uuid4()}{extension}"


class Category(models.Model):
    """
    Product category.

    Supports parent-child hierarchy.
    Used for public product browsing and filtering.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=180, unique=True, blank=True)

    description = models.TextField(blank=True)

    parent = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="children",
    )

    is_active = models.BooleanField(default=True, db_index=True)
    sort_order = models.PositiveIntegerField(default=0, db_index=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["sort_order", "name"]
        verbose_name_plural = "Categories"
        constraints = [
            models.UniqueConstraint(
                Lower("name"),
                name="catalog_category_name_case_insensitive_unique",
            ),
        ]

    def clean(self):
        if self.name:
            self.name = self.name.strip()

        if not self.name:
            raise ValidationError({"name": "Category name is required."})

        if self.slug:
            self.slug = slugify(self.slug)

        if self.parent_id and self.pk and self.parent_id == self.pk:
            raise ValidationError({"parent": "Category cannot be its own parent."})

        parent = self.parent
        seen_parent_ids = set()

        while parent:
            if self.pk and parent.pk == self.pk:
                raise ValidationError(
                    {"parent": "Circular category hierarchy is not allowed."}
                )

            if parent.pk in seen_parent_ids:
                raise ValidationError(
                    {"parent": "Circular category hierarchy is not allowed."}
                )

            seen_parent_ids.add(parent.pk)
            parent = parent.parent

    def save(self, *args, **kwargs):
        self.clean()

        if not self.slug:
            self.slug = generate_unique_slug(self, self.name)

        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class Brand(models.Model):
    """
    Product brand.

    Brands are optional on products.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=180, unique=True, blank=True)

    description = models.TextField(blank=True)

    is_active = models.BooleanField(default=True, db_index=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                Lower("name"),
                name="catalog_brand_name_case_insensitive_unique",
            ),
        ]

    def clean(self):
        if self.name:
            self.name = self.name.strip()

        if not self.name:
            raise ValidationError({"name": "Brand name is required."})

        if self.slug:
            self.slug = slugify(self.slug)

    def save(self, *args, **kwargs):
        self.clean()

        if not self.slug:
            self.slug = generate_unique_slug(self, self.name)

        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class Product(models.Model):
    """
    Vendor-owned product.

    Inventory will be handled in the inventory module.
    This model only stores catalog/product information.
    """

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        PENDING_REVIEW = "PENDING_REVIEW", "Pending Review"
        ACTIVE = "ACTIVE", "Active"
        REJECTED = "REJECTED", "Rejected"
        ARCHIVED = "ARCHIVED", "Archived"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    vendor = models.ForeignKey(
        Vendor,
        on_delete=models.CASCADE,
        related_name="products",
    )

    category = models.ForeignKey(
        Category,
        on_delete=models.PROTECT,
        related_name="products",
    )

    brand = models.ForeignKey(
        Brand,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="products",
    )

    name = models.CharField(max_length=180)
    slug = models.SlugField(max_length=220, unique=True, blank=True)

    sku = models.CharField(max_length=80)

    short_description = models.CharField(max_length=300, blank=True)
    description = models.TextField(blank=True)

    base_price = models.DecimalField(max_digits=12, decimal_places=2)

    status = models.CharField(
        max_length=30,
        choices=Status.choices,
        default=Status.DRAFT,
        db_index=True,
    )

    is_featured = models.BooleanField(default=False, db_index=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["vendor", "status"]),
            models.Index(fields=["category", "status"]),
            models.Index(fields=["brand", "status"]),
            models.Index(fields=["created_at"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["vendor", "sku"],
                name="catalog_product_vendor_sku_unique",
            ),
            models.CheckConstraint(
                condition=Q(base_price__gte=Decimal("0.00")),
                name="catalog_product_base_price_non_negative",
            ),
        ]

    def clean(self):
        if self.name:
            self.name = self.name.strip()

        if not self.name:
            raise ValidationError({"name": "Product name is required."})

        if self.sku:
            self.sku = self.sku.strip()

        if not self.sku:
            raise ValidationError({"sku": "Product SKU is required."})

        if self.slug:
            self.slug = slugify(self.slug)

        if self.base_price is not None:
            try:
                self.base_price = Decimal(str(self.base_price)).quantize(
                    Decimal("0.01")
                )
            except (InvalidOperation, ValueError, TypeError):
                raise ValidationError({"base_price": "Enter a valid price."})

            if self.base_price < Decimal("0.00"):
                raise ValidationError(
                    {"base_price": "Product base price cannot be negative."}
                )

        if self.vendor_id and self.sku:
            queryset = Product.objects.filter(
                vendor_id=self.vendor_id,
                sku__iexact=self.sku,
            )

            if self.pk:
                queryset = queryset.exclude(pk=self.pk)

            if queryset.exists():
                raise ValidationError(
                    {"sku": "This vendor already has a product with this SKU."}
                )

        if self.status == self.Status.ACTIVE:
            if self.vendor_id and self.vendor.status != Vendor.Status.APPROVED:
                raise ValidationError(
                    {"status": "Only approved vendors can have active products."}
                )

            if self.category_id and not self.category.is_active:
                raise ValidationError(
                    {"category": "Product category must be active."}
                )

            if self.brand_id and self.brand and not self.brand.is_active:
                raise ValidationError(
                    {"brand": "Product brand must be active."}
                )

    def save(self, *args, **kwargs):
        self.clean()

        if not self.slug:
            self.slug = generate_unique_slug(self, self.name, max_length=220)

        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class ProductImage(models.Model):
    """
    Product image.

    FileField is used so storage can be local in development
    and S3/private storage in production.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="images",
    )

    file = models.FileField(upload_to=catalog_product_image_upload_path)

    alt_text = models.CharField(max_length=180, blank=True)

    is_primary = models.BooleanField(default=False, db_index=True)
    sort_order = models.PositiveIntegerField(default=0, db_index=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["sort_order", "created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["product"],
                condition=Q(is_primary=True),
                name="catalog_one_primary_image_per_product",
            ),
        ]

    def clean(self):
        if self.alt_text:
            self.alt_text = self.alt_text.strip()

    def save(self, *args, **kwargs):
        self.clean()

        with transaction.atomic():
            if self.is_primary and self.product_id:
                ProductImage.objects.filter(
                    product_id=self.product_id,
                    is_primary=True,
                ).exclude(pk=self.pk).update(is_primary=False)

            super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.product.name} image"


class ProductVariant(models.Model):
    """
    Product variant.

    Inventory quantities will be handled in inventory module.
    Variant stores SKU, price, and attributes like size/color.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="variants",
    )

    name = models.CharField(max_length=120)
    sku = models.CharField(max_length=80)

    price = models.DecimalField(max_digits=12, decimal_places=2)

    attributes = models.JSONField(default=dict, blank=True)

    is_default = models.BooleanField(default=False, db_index=True)
    is_active = models.BooleanField(default=True, db_index=True)
    sort_order = models.PositiveIntegerField(default=0, db_index=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["sort_order", "name"]
        indexes = [
            models.Index(fields=["product", "is_active"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["product", "sku"],
                name="catalog_product_variant_sku_unique",
            ),
            models.UniqueConstraint(
                fields=["product"],
                condition=Q(is_default=True),
                name="catalog_one_default_variant_per_product",
            ),
            models.CheckConstraint(
                condition=Q(price__gte=Decimal("0.00")),
                name="catalog_product_variant_price_non_negative",
            ),
        ]

    def clean(self):
        if self.name:
            self.name = self.name.strip()

        if not self.name:
            raise ValidationError({"name": "Variant name is required."})

        if self.sku:
            self.sku = self.sku.strip()

        if not self.sku:
            raise ValidationError({"sku": "Variant SKU is required."})

        if self.price is not None:
            try:
                self.price = Decimal(str(self.price)).quantize(Decimal("0.01"))
            except (InvalidOperation, ValueError, TypeError):
                raise ValidationError({"price": "Enter a valid variant price."})

            if self.price < Decimal("0.00"):
                raise ValidationError(
                    {"price": "Variant price cannot be negative."}
                )

        if self.product_id and self.sku:
            queryset = ProductVariant.objects.filter(
                product_id=self.product_id,
                sku__iexact=self.sku,
            )

            if self.pk:
                queryset = queryset.exclude(pk=self.pk)

            if queryset.exists():
                raise ValidationError(
                    {"sku": "This product already has a variant with this SKU."}
                )

        if self.attributes is None:
            self.attributes = {}

        if not isinstance(self.attributes, dict):
            raise ValidationError(
                {"attributes": "Variant attributes must be a JSON object."}
            )

    def save(self, *args, **kwargs):
        self.clean()

        with transaction.atomic():
            if self.is_default and self.product_id:
                ProductVariant.objects.filter(
                    product_id=self.product_id,
                    is_default=True,
                ).exclude(pk=self.pk).update(is_default=False)

            super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.product.name} - {self.name}"