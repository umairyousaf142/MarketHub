from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from .models import Address, User


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    model = User

    list_display = [
        "email",
        "role",
        "is_active",
        "is_verified",
        "is_staff",
        "created_at",
    ]

    list_filter = [
        "role",
        "is_active",
        "is_verified",
        "is_staff",
        "created_at",
    ]

    search_fields = [
        "email",
    ]

    ordering = [
        "-created_at",
    ]

    readonly_fields = [
        "id",
        "created_at",
        "updated_at",
        "last_login",
    ]

    fieldsets = [
        (
            "Account",
            {
                "fields": [
                    "id",
                    "email",
                    "password",
                    "role",
                ]
            },
        ),
        (
            "Status",
            {
                "fields": [
                    "is_active",
                    "is_verified",
                    "is_staff",
                    "is_superuser",
                ]
            },
        ),
        (
            "Permissions",
            {
                "fields": [
                    "groups",
                    "user_permissions",
                ]
            },
        ),
        (
            "Important Dates",
            {
                "fields": [
                    "last_login",
                    "created_at",
                    "updated_at",
                ]
            },
        ),
    ]

    add_fieldsets = [
        (
            "Create User",
            {
                "classes": ["wide"],
                "fields": [
                    "email",
                    "role",
                    "password1",
                    "password2",
                    "is_active",
                    "is_verified",
                    "is_staff",
                    "is_superuser",
                ],
            },
        ),
    ]


@admin.register(Address)
class AddressAdmin(admin.ModelAdmin):
    list_display = [
        "user",
        "label",
        "city",
        "country",
        "is_default",
        "created_at",
    ]

    list_filter = [
        "country",
        "city",
        "is_default",
        "created_at",
    ]

    search_fields = [
        "user__email",
        "label",
        "street",
        "city",
        "country",
    ]

    readonly_fields = [
        "id",
        "created_at",
        "updated_at",
    ]

    ordering = [
        "-is_default",
        "-created_at",
    ]