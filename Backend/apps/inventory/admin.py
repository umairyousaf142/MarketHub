from django.contrib import admin

from .models import InventoryRecord, StockMovement


@admin.register(InventoryRecord)
class InventoryRecordAdmin(admin.ModelAdmin):
    list_display = [
        "product",
        "variant",
        "vendor",
        "quantity_on_hand",
        "quantity_reserved",
        "available",
        "low_stock_threshold",
        "low_stock",
        "track_inventory",
        "allow_backorder",
        "updated_at",
    ]

    list_filter = [
        "track_inventory",
        "allow_backorder",
        "created_at",
        "updated_at",
    ]

    search_fields = [
        "product__name",
        "product__sku",
        "product__vendor__store_name",
        "variant__name",
        "variant__sku",
    ]

    readonly_fields = [
        "id",
        "available_quantity_display",
        "created_at",
        "updated_at",
    ]

    ordering = [
        "product__name",
        "variant__name",
    ]

    @admin.display(description="Vendor")
    def vendor(self, obj):
        return obj.product.vendor

    @admin.display(description="Available")
    def available(self, obj):
        return obj.available_quantity

    @admin.display(description="Available quantity")
    def available_quantity_display(self, obj):
        return obj.available_quantity

    @admin.display(description="Low stock", boolean=True)
    def low_stock(self, obj):
        return obj.is_low_stock


@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    list_display = [
        "inventory_record",
        "movement_type",
        "quantity",
        "before_on_hand",
        "after_on_hand",
        "before_reserved",
        "after_reserved",
        "reference",
        "created_by",
        "created_at",
    ]

    list_filter = [
        "movement_type",
        "created_at",
    ]

    search_fields = [
        "inventory_record__product__name",
        "inventory_record__product__sku",
        "inventory_record__variant__name",
        "inventory_record__variant__sku",
        "reference",
        "reason",
        "created_by__email",
    ]

    readonly_fields = [
        "id",
        "inventory_record",
        "movement_type",
        "quantity",
        "before_on_hand",
        "after_on_hand",
        "before_reserved",
        "after_reserved",
        "reason",
        "reference",
        "created_by",
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

    def has_view_permission(self, request, obj=None):
        return True