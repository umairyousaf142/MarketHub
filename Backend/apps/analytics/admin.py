from django.contrib import admin

from apps.analytics.models import AnalyticsSnapshot


@admin.register(AnalyticsSnapshot)
class AnalyticsSnapshotAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "date",
        "total_revenue",
        "total_orders",
        "new_customers",
        "top_vendor",
        "top_product",
    ]
    list_filter = [
        "date",
        "top_vendor",
        "top_product",
    ]
    search_fields = [
        "id",
        "top_vendor__store_name",
        "top_product__name",
        "top_product__sku",
    ]
    raw_id_fields = [
        "top_vendor",
        "top_product",
    ]
    readonly_fields = [
        "id",
    ]
    date_hierarchy = "date"
    ordering = [
        "-date",
    ]

    fieldsets = (
        (
            "Snapshot",
            {
                "fields": (
                    "id",
                    "date",
                    "total_revenue",
                    "total_orders",
                    "new_customers",
                )
            },
        ),
        (
            "Top Performers",
            {
                "fields": (
                    "top_vendor",
                    "top_product",
                )
            },
        ),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            "top_vendor",
            "top_product",
        )