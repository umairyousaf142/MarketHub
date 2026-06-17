from decimal import Decimal
from pathlib import Path

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from apps.catalog.models import Brand, Category, Product, ProductImage, ProductVariant


class DetailResponseSerializer(serializers.Serializer):
    detail = serializers.CharField()


def raise_serializer_validation_error(exc):
    if hasattr(exc, "message_dict"):
        raise serializers.ValidationError(exc.message_dict)

    if hasattr(exc, "messages"):
        raise serializers.ValidationError({"detail": exc.messages})

    raise serializers.ValidationError({"detail": str(exc)})


class CategorySerializer(serializers.ModelSerializer):
    parent_name = serializers.CharField(source="parent.name", read_only=True)
    parent_slug = serializers.CharField(source="parent.slug", read_only=True)

    class Meta:
        model = Category
        fields = [
            "id",
            "name",
            "slug",
            "description",
            "parent",
            "parent_name",
            "parent_slug",
            "is_active",
            "sort_order",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "slug",
            "parent_name",
            "parent_slug",
            "created_at",
            "updated_at",
        ]

    def validate_name(self, value):
        value = value.strip()

        queryset = Category.objects.filter(name__iexact=value)

        if self.instance:
            queryset = queryset.exclude(pk=self.instance.pk)

        if queryset.exists():
            raise serializers.ValidationError(
                "A category with this name already exists."
            )

        return value

    def create(self, validated_data):
        try:
            return super().create(validated_data)
        except DjangoValidationError as exc:
            raise_serializer_validation_error(exc)

    def update(self, instance, validated_data):
        try:
            return super().update(instance, validated_data)
        except DjangoValidationError as exc:
            raise_serializer_validation_error(exc)


class PublicCategorySerializer(serializers.ModelSerializer):
    parent_slug = serializers.CharField(source="parent.slug", read_only=True)

    class Meta:
        model = Category
        fields = [
            "id",
            "name",
            "slug",
            "description",
            "parent_slug",
            "sort_order",
        ]


class BrandSerializer(serializers.ModelSerializer):
    class Meta:
        model = Brand
        fields = [
            "id",
            "name",
            "slug",
            "description",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "slug",
            "created_at",
            "updated_at",
        ]

    def validate_name(self, value):
        value = value.strip()

        queryset = Brand.objects.filter(name__iexact=value)

        if self.instance:
            queryset = queryset.exclude(pk=self.instance.pk)

        if queryset.exists():
            raise serializers.ValidationError(
                "A brand with this name already exists."
            )

        return value

    def create(self, validated_data):
        try:
            return super().create(validated_data)
        except DjangoValidationError as exc:
            raise_serializer_validation_error(exc)

    def update(self, instance, validated_data):
        try:
            return super().update(instance, validated_data)
        except DjangoValidationError as exc:
            raise_serializer_validation_error(exc)


class PublicBrandSerializer(serializers.ModelSerializer):
    class Meta:
        model = Brand
        fields = [
            "id",
            "name",
            "slug",
            "description",
        ]


class ProductImageSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductImage
        fields = [
            "id",
            "file",
            "alt_text",
            "is_primary",
            "sort_order",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "created_at",
        ]

    def validate_file(self, value):
        max_size = 5 * 1024 * 1024
        allowed_extensions = {".jpg", ".jpeg", ".png", ".webp"}

        if hasattr(value, "size") and value.size > max_size:
            raise serializers.ValidationError(
                "Product image size cannot exceed 5MB."
            )

        extension = Path(value.name).suffix.lower()

        if extension not in allowed_extensions:
            raise serializers.ValidationError(
                "Only JPG, JPEG, PNG, and WEBP images are allowed."
            )

        return value

    def create(self, validated_data):
        try:
            return super().create(validated_data)
        except DjangoValidationError as exc:
            raise_serializer_validation_error(exc)

    def update(self, instance, validated_data):
        try:
            return super().update(instance, validated_data)
        except DjangoValidationError as exc:
            raise_serializer_validation_error(exc)


class ProductVariantSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductVariant
        fields = [
            "id",
            "name",
            "sku",
            "price",
            "attributes",
            "is_default",
            "is_active",
            "sort_order",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "created_at",
            "updated_at",
        ]

    def validate_sku(self, value):
        value = value.strip()

        product = self.context.get("product")
        queryset = ProductVariant.objects.filter(
            product=product,
            sku__iexact=value,
        )

        if self.instance:
            queryset = queryset.exclude(pk=self.instance.pk)

        if product and queryset.exists():
            raise serializers.ValidationError(
                "This product already has a variant with this SKU."
            )

        return value

    def validate_price(self, value):
        if value < Decimal("0.00"):
            raise serializers.ValidationError(
                "Variant price cannot be negative."
            )

        return value

    def validate_attributes(self, value):
        if value is None:
            return {}

        if not isinstance(value, dict):
            raise serializers.ValidationError(
                "Variant attributes must be a JSON object."
            )

        return value

    def create(self, validated_data):
        try:
            return super().create(validated_data)
        except DjangoValidationError as exc:
            raise_serializer_validation_error(exc)

    def update(self, instance, validated_data):
        try:
            return super().update(instance, validated_data)
        except DjangoValidationError as exc:
            raise_serializer_validation_error(exc)


class ProductCategoryCompactSerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = [
            "id",
            "name",
            "slug",
        ]


class ProductBrandCompactSerializer(serializers.ModelSerializer):
    class Meta:
        model = Brand
        fields = [
            "id",
            "name",
            "slug",
        ]


class PublicProductListSerializer(serializers.ModelSerializer):
    category = ProductCategoryCompactSerializer(read_only=True)
    brand = ProductBrandCompactSerializer(read_only=True)
    vendor_id = serializers.UUIDField(source="vendor.id", read_only=True)
    vendor_store_name = serializers.CharField(source="vendor.store_name", read_only=True)
    primary_image = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = [
            "id",
            "name",
            "slug",
            "short_description",
            "base_price",
            "category",
            "brand",
            "vendor_id",
            "vendor_store_name",
            "is_featured",
            "primary_image",
            "created_at",
        ]

    def get_primary_image(self, obj):
        image = obj.images.filter(is_primary=True).first()

        if not image:
            image = obj.images.first()

        if not image:
            return None

        request = self.context.get("request")

        if request:
            return request.build_absolute_uri(image.file.url)

        return image.file.url


class PublicProductDetailSerializer(PublicProductListSerializer):
    images = ProductImageSerializer(many=True, read_only=True)
    variants = serializers.SerializerMethodField()

    class Meta(PublicProductListSerializer.Meta):
        fields = PublicProductListSerializer.Meta.fields + [
            "description",
            "images",
            "variants",
        ]

    def get_variants(self, obj):
        variants = obj.variants.filter(is_active=True)
        return ProductVariantSerializer(variants, many=True).data


class VendorProductReadSerializer(serializers.ModelSerializer):
    vendor_id = serializers.UUIDField(source="vendor.id", read_only=True)
    vendor_store_name = serializers.CharField(source="vendor.store_name", read_only=True)

    category_detail = ProductCategoryCompactSerializer(
        source="category",
        read_only=True,
    )
    brand_detail = ProductBrandCompactSerializer(
        source="brand",
        read_only=True,
    )

    images = ProductImageSerializer(many=True, read_only=True)
    variants = ProductVariantSerializer(many=True, read_only=True)

    class Meta:
        model = Product
        fields = [
            "id",
            "vendor_id",
            "vendor_store_name",
            "category",
            "category_detail",
            "brand",
            "brand_detail",
            "name",
            "slug",
            "sku",
            "short_description",
            "description",
            "base_price",
            "status",
            "is_featured",
            "images",
            "variants",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "vendor_id",
            "vendor_store_name",
            "category_detail",
            "brand_detail",
            "slug",
            "status",
            "is_featured",
            "images",
            "variants",
            "created_at",
            "updated_at",
        ]


class VendorProductWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Product
        fields = [
            "category",
            "brand",
            "name",
            "sku",
            "short_description",
            "description",
            "base_price",
            "status",
        ]

    def validate_sku(self, value):
        value = value.strip()

        vendor = self.context.get("vendor")
        queryset = Product.objects.filter(
            vendor=vendor,
            sku__iexact=value,
        )

        if self.instance:
            queryset = queryset.exclude(pk=self.instance.pk)

        if vendor and queryset.exists():
            raise serializers.ValidationError(
                "This vendor already has a product with this SKU."
            )

        return value

    def validate_base_price(self, value):
        if value < Decimal("0.00"):
            raise serializers.ValidationError(
                "Product base price cannot be negative."
            )

        return value

    def validate_status(self, value):
        allowed_vendor_statuses = [
            Product.Status.DRAFT,
            Product.Status.PENDING_REVIEW,
        ]

        if value not in allowed_vendor_statuses:
            raise serializers.ValidationError(
                "Vendor can only set product status to DRAFT or PENDING_REVIEW."
            )

        return value

    def create(self, validated_data):
        try:
            return super().create(validated_data)
        except DjangoValidationError as exc:
            raise_serializer_validation_error(exc)

    def update(self, instance, validated_data):
        try:
            return super().update(instance, validated_data)
        except DjangoValidationError as exc:
            raise_serializer_validation_error(exc)


class AdminProductReadSerializer(VendorProductReadSerializer):
    pass