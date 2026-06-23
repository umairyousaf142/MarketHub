from django.contrib import admin, messages

from apps.notifications.models import Notification


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "user",
        "type",
        "channel",
        "title",
        "is_read",
        "created_at",
    ]
    list_filter = [
        "type",
        "channel",
        "is_read",
        "created_at",
    ]
    search_fields = [
        "id",
        "user__email",
        "title",
        "body",
    ]
    raw_id_fields = [
        "user",
    ]
    readonly_fields = [
        "id",
        "created_at",
    ]
    actions = [
        "mark_notifications_read",
        "mark_notifications_unread",
    ]

    fieldsets = (
        (
            "Notification",
            {
                "fields": (
                    "id",
                    "user",
                    "type",
                    "channel",
                    "title",
                    "body",
                    "is_read",
                    "created_at",
                )
            },
        ),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("user")

    @admin.action(description="Mark selected in-app notifications as read")
    def mark_notifications_read(self, request, queryset):
        updated_count = queryset.filter(
            channel=Notification.Channel.IN_APP,
        ).update(is_read=True)

        self.message_user(
            request,
            f"{updated_count} in-app notification(s) marked as read.",
            level=messages.INFO,
        )

    @admin.action(description="Mark selected in-app notifications as unread")
    def mark_notifications_unread(self, request, queryset):
        updated_count = queryset.filter(
            channel=Notification.Channel.IN_APP,
        ).update(is_read=False)

        self.message_user(
            request,
            f"{updated_count} in-app notification(s) marked as unread.",
            level=messages.INFO,
        )