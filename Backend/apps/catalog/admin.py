from django.contrib import admin, messages
from django.core.exceptions import ValidationError

from .models import Brand, Category, Product, ProductImage, ProductVariant


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = [
        "name",
        "slug",
        "parent",
        "is_active",
        "sort_order",
        "created_at",
    ]

    list_filter = [
        "is_active",
        "parent",
    ]

    search_fields = [
        "name",
        "slug",
    ]

    prepopulated_fields = {
        "slug": ["name"],
    }

    readonly_fields = [
        "id",
        "created_at",
        "updated_at",
    ]

    ordering = [
        "sort_order",
        "name",
    ]


@admin.register(Brand)
class BrandAdmin(admin.ModelAdmin):
    list_display = [
        "name",
        "slug",
        "is_active",
        "created_at",
    ]

    list_filter = [
        "is_active",
    ]

    search_fields = [
        "name",
        "slug",
    ]

    prepopulated_fields = {
        "slug": ["name"],
    }

    readonly_fields = [
        "id",
        "created_at",
        "updated_at",
    ]

    ordering = [
        "name",
    ]


class ProductImageInline(admin.TabularInline):
    model = ProductImage
    extra = 0

    fields = [
        "file",
        "alt_text",
        "is_primary",
        "sort_order",
    ]


class ProductVariantInline(admin.TabularInline):
    model = ProductVariant
    extra = 0

    fields = [
        "name",
        "sku",
        "price",
        "attributes",
        "is_default",
        "is_active",
        "sort_order",
    ]


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = [
        "name",
        "sku",
        "vendor",
        "category",
        "brand",
        "base_price",
        "status",
        "is_featured",
        "created_at",
    ]

    list_filter = [
        "status",
        "category",
        "brand",
        "is_featured",
    ]

    search_fields = [
        "name",
        "slug",
        "sku",
        "vendor__store_name",
        "vendor__user__email",
    ]

    prepopulated_fields = {
        "slug": ["name"],
    }

    readonly_fields = [
        "id",
        "created_at",
        "updated_at",
    ]

    ordering = [
        "-created_at",
    ]

    inlines = [
        ProductImageInline,
        ProductVariantInline,
    ]

    actions = [
        "mark_as_draft",
        "mark_as_pending_review",
        "mark_as_archived",
    ]

    @admin.action(description="Mark selected products as draft")
    def mark_as_draft(self, request, queryset):
        updated = queryset.update(status=Product.Status.DRAFT)

        self.message_user(
            request,
            f"{updated} product(s) marked as draft.",
            level=messages.SUCCESS,
        )

    @admin.action(description="Mark selected products as pending review")
    def mark_as_pending_review(self, request, queryset):
        updated = queryset.update(status=Product.Status.PENDING_REVIEW)

        self.message_user(
            request,
            f"{updated} product(s) marked as pending review.",
            level=messages.SUCCESS,
        )

    @admin.action(description="Archive selected products")
    def mark_as_archived(self, request, queryset):
        updated = queryset.update(status=Product.Status.ARCHIVED)

        self.message_user(
            request,
            f"{updated} product(s) archived.",
            level=messages.SUCCESS,
        )


@admin.register(ProductImage)
class ProductImageAdmin(admin.ModelAdmin):
    list_display = [
        "product",
        "is_primary",
        "sort_order",
        "created_at",
    ]

    list_filter = [
        "is_primary",
    ]

    search_fields = [
        "product__name",
        "product__sku",
    ]

    readonly_fields = [
        "id",
        "created_at",
    ]

    ordering = [
        "product",
        "sort_order",
    ]


@admin.register(ProductVariant)
class ProductVariantAdmin(admin.ModelAdmin):
    list_display = [
        "product",
        "name",
        "sku",
        "price",
        "is_default",
        "is_active",
        "sort_order",
    ]

    list_filter = [
        "is_default",
        "is_active",
    ]

    search_fields = [
        "product__name",
        "product__sku",
        "name",
        "sku",
    ]

    readonly_fields = [
        "id",
        "created_at",
        "updated_at",
    ]

    ordering = [
        "product",
        "sort_order",
        "name",
    ]