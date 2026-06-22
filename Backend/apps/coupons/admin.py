from django.contrib import admin

from apps.coupons.models import Coupon, CouponUsage


class CouponUsageInline(admin.TabularInline):
    model = CouponUsage
    extra = 0
    autocomplete_fields = ["user", "order"]
    fields = [
        "user",
        "order",
        "used_at",
    ]
    readonly_fields = ["used_at"]


@admin.register(Coupon)
class CouponAdmin(admin.ModelAdmin):
    list_display = [
        "code",
        "type",
        "value",
        "max_discount",
        "scope",
        "vendor",
        "category",
        "min_order_value",
        "usage_limit",
        "per_user_limit",
        "valid_from",
        "valid_until",
        "is_active",
        "usage_count",
    ]
    list_filter = [
        "type",
        "scope",
        "is_active",
        "valid_from",
        "valid_until",
    ]
    search_fields = [
        "id",
        "code",
        "vendor__store_name",
        "category__name",
    ]
    autocomplete_fields = [
        "vendor",
        "category",
    ]
    readonly_fields = [
        "id",
        "usage_count",
    ]
    inlines = [
        CouponUsageInline,
    ]

    fieldsets = (
        (
            "Coupon",
            {
                "fields": (
                    "id",
                    "code",
                    "type",
                    "value",
                    "max_discount",
                    "is_active",
                )
            },
        ),
        (
            "Scope",
            {
                "fields": (
                    "scope",
                    "vendor",
                    "category",
                )
            },
        ),
        (
            "Validation Rules",
            {
                "fields": (
                    "min_order_value",
                    "usage_limit",
                    "per_user_limit",
                    "valid_from",
                    "valid_until",
                )
            },
        ),
        (
            "Usage Tracking",
            {
                "fields": (
                    "usage_count",
                )
            },
        ),
    )


@admin.register(CouponUsage)
class CouponUsageAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "coupon",
        "user",
        "order",
        "used_at",
    ]
    list_filter = [
        "used_at",
        "coupon__type",
        "coupon__scope",
    ]
    search_fields = [
        "id",
        "coupon__code",
        "user__email",
        "order__order_number",
    ]
    autocomplete_fields = [
        "coupon",
        "user",
        "order",
    ]
    readonly_fields = [
        "id",
        "used_at",
    ]