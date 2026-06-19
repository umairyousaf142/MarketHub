from django.contrib import admin

from .models import Cart, CartItem


class CartItemInline(admin.TabularInline):
    model = CartItem
    extra = 0
    readonly_fields = [
        "id",
        "unit_price",
        "line_total_display",
        "created_at",
        "updated_at",
    ]

    fields = [
        "id",
        "product",
        "variant",
        "quantity",
        "unit_price",
        "line_total_display",
        "created_at",
        "updated_at",
    ]

    @admin.display(description="Line total")
    def line_total_display(self, obj):
        if not obj.pk:
            return "-"

        return obj.line_total


@admin.register(Cart)
class CartAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "customer",
        "status",
        "item_count_display",
        "total_quantity_display",
        "subtotal_display",
        "created_at",
        "updated_at",
    ]

    list_filter = [
        "status",
        "created_at",
        "updated_at",
    ]

    search_fields = [
        "id",
        "customer__email",
        "customer__first_name",
        "customer__last_name",
    ]

    readonly_fields = [
        "id",
        "item_count_display",
        "total_quantity_display",
        "subtotal_display",
        "created_at",
        "updated_at",
        "converted_at",
        "abandoned_at",
    ]

    inlines = [
        CartItemInline,
    ]

    ordering = [
        "-created_at",
    ]

    @admin.display(description="Items")
    def item_count_display(self, obj):
        return obj.item_count

    @admin.display(description="Total quantity")
    def total_quantity_display(self, obj):
        return obj.total_quantity

    @admin.display(description="Subtotal")
    def subtotal_display(self, obj):
        return obj.subtotal_amount


@admin.register(CartItem)
class CartItemAdmin(admin.ModelAdmin):
    list_display = [
        "cart",
        "customer",
        "product",
        "variant",
        "quantity",
        "unit_price",
        "line_total_display",
        "created_at",
    ]

    list_filter = [
        "created_at",
        "updated_at",
    ]

    search_fields = [
        "cart__id",
        "cart__customer__email",
        "product__name",
        "product__sku",
        "variant__name",
        "variant__sku",
    ]

    readonly_fields = [
        "id",
        "unit_price",
        "line_total_display",
        "created_at",
        "updated_at",
    ]

    ordering = [
        "-created_at",
    ]

    @admin.display(description="Customer")
    def customer(self, obj):
        return obj.cart.customer

    @admin.display(description="Line total")
    def line_total_display(self, obj):
        return obj.line_total