from django.contrib import admin, messages

from apps.reviews.models import Review


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "order_item",
        "reviewer",
        "variant",
        "rating",
        "is_visible",
        "created_at",
    ]
    list_filter = [
        "is_visible",
        "rating",
        "created_at",
    ]
    search_fields = [
        "id",
        "reviewer__email",
        "variant__sku",
        "order_item__product_name",
        "body",
    ]
    raw_id_fields = [
        "order_item",
        "reviewer",
        "variant",
    ]
    readonly_fields = [
        "id",
        "created_at",
    ]
    actions = [
        "mark_reviews_visible",
        "hide_reviews",
    ]

    fieldsets = (
        (
            "Review",
            {
                "fields": (
                    "id",
                    "order_item",
                    "reviewer",
                    "variant",
                    "rating",
                    "body",
                    "is_visible",
                    "created_at",
                )
            },
        ),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            "order_item",
            "reviewer",
            "variant",
        )

    @admin.action(description="Mark selected reviews as visible")
    def mark_reviews_visible(self, request, queryset):
        updated_count = queryset.update(is_visible=True)

        self.message_user(
            request,
            f"{updated_count} review(s) marked as visible.",
            level=messages.INFO,
        )

    @admin.action(description="Hide selected reviews")
    def hide_reviews(self, request, queryset):
        updated_count = queryset.update(is_visible=False)

        self.message_user(
            request,
            f"{updated_count} review(s) hidden.",
            level=messages.INFO,
        )