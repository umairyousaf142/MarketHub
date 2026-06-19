from django.contrib import admin

from .models import Order, OrderItem, VendorOrder


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    readonly_fields = [
        "id",
        "vendor",
        "product",
        "variant",
        "inventory_record",
        "product_name",
        "product_sku",
        "variant_name",
        "variant_sku",
        "vendor_store_name",
        "quantity",
        "unit_price",
        "line_total",
        "created_at",
    ]

    fields = [
        "id",
        "vendor",
        "product_name",
        "product_sku",
        "variant_name",
        "variant_sku",
        "quantity",
        "unit_price",
        "line_total",
        "created_at",
    ]

    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


class VendorOrderInline(admin.TabularInline):
    model = VendorOrder
    extra = 0
    readonly_fields = [
        "id",
        "vendor",
        "status",
        "subtotal_amount",
        "item_count",
        "total_quantity",
        "created_at",
        "updated_at",
    ]

    fields = [
        "id",
        "vendor",
        "status",
        "subtotal_amount",
        "item_count",
        "total_quantity",
        "created_at",
        "updated_at",
    ]

    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = [
        "order_number",
        "customer",
        "status",
        "payment_status",
        "inventory_status",
        "total_amount",
        "item_count_display",
        "total_quantity_display",
        "placed_at",
        "created_at",
    ]

    list_filter = [
        "status",
        "payment_status",
        "inventory_status",
        "placed_at",
        "created_at",
    ]

    search_fields = [
        "order_number",
        "customer__email",
        "customer__first_name",
        "customer__last_name",
    ]

    readonly_fields = [
        "id",
        "order_number",
        "source_cart",
        "subtotal_amount",
        "shipping_amount",
        "tax_amount",
        "discount_amount",
        "total_amount",
        "item_count_display",
        "total_quantity_display",
        "placed_at",
        "paid_at",
        "cancelled_at",
        "created_at",
        "updated_at",
    ]

    inlines = [
        OrderItemInline,
        VendorOrderInline,
    ]

    ordering = [
        "-created_at",
    ]

    actions = [
        "mark_orders_confirmed",
        "mark_orders_processing",
        "mark_orders_cancelled",
    ]

    @admin.display(description="Items")
    def item_count_display(self, obj):
        return obj.item_count

    @admin.display(description="Total quantity")
    def total_quantity_display(self, obj):
        return obj.total_quantity

    @admin.action(description="Mark selected orders as confirmed")
    def mark_orders_confirmed(self, request, queryset):
        queryset.update(status=Order.Status.CONFIRMED)

    @admin.action(description="Mark selected orders as processing")
    def mark_orders_processing(self, request, queryset):
        queryset.update(status=Order.Status.PROCESSING)

    @admin.action(description="Mark selected orders as cancelled")
    def mark_orders_cancelled(self, request, queryset):
        queryset.update(status=Order.Status.CANCELLED)


@admin.register(OrderItem)
class OrderItemAdmin(admin.ModelAdmin):
    list_display = [
        "order",
        "vendor",
        "product_name",
        "variant_name",
        "quantity",
        "unit_price",
        "line_total",
        "created_at",
    ]

    list_filter = [
        "vendor",
        "created_at",
    ]

    search_fields = [
        "order__order_number",
        "vendor__store_name",
        "product_name",
        "product_sku",
        "variant_name",
        "variant_sku",
    ]

    readonly_fields = [
        "id",
        "order",
        "vendor",
        "product",
        "variant",
        "inventory_record",
        "product_name",
        "product_sku",
        "variant_name",
        "variant_sku",
        "vendor_store_name",
        "quantity",
        "unit_price",
        "line_total",
        "created_at",
    ]

    ordering = [
        "-created_at",
    ]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(VendorOrder)
class VendorOrderAdmin(admin.ModelAdmin):
    list_display = [
        "order",
        "vendor",
        "status",
        "subtotal_amount",
        "item_count",
        "total_quantity",
        "created_at",
    ]

    list_filter = [
        "status",
        "created_at",
        "updated_at",
    ]

    search_fields = [
        "order__order_number",
        "vendor__store_name",
    ]

    readonly_fields = [
        "id",
        "order",
        "vendor",
        "subtotal_amount",
        "item_count",
        "total_quantity",
        "created_at",
        "updated_at",
    ]

    ordering = [
        "-created_at",
    ]