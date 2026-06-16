from django.contrib import admin
from django.core.exceptions import ValidationError
from django.contrib import messages

from .models import CommissionPlan, Vendor, VendorDocument


@admin.register(CommissionPlan)
class CommissionPlanAdmin(admin.ModelAdmin):
    list_display = [
        "name",
        "percentage",
        "is_default",
    ]

    list_filter = [
        "is_default",
    ]

    search_fields = [
        "name",
    ]

    ordering = [
        "-is_default",
        "name",
    ]

    readonly_fields = [
        "id",
    ]


class VendorDocumentInline(admin.TabularInline):
    model = VendorDocument
    extra = 0
    fields = [
        "doc_type",
        "file",
        "verified",
    ]


@admin.register(Vendor)
class VendorAdmin(admin.ModelAdmin):
    list_display = [
        "store_name",
        "user",
        "status",
        "commission_plan",
        "approved_at",
        "approved_by",
    ]

    list_filter = [
        "status",
        "commission_plan",
    ]

    search_fields = [
        "store_name",
        "user__email",
    ]

    readonly_fields = [
        "id",
        "approved_at",
        "approved_by",
    ]

    ordering = [
        "store_name",
    ]

    inlines = [
        VendorDocumentInline,
    ]

    actions = [
        "approve_selected_vendors",
        "reject_selected_vendors",
        "suspend_selected_vendors",
    ]

    @admin.action(description="Approve selected pending vendors")
    def approve_selected_vendors(self, request, queryset):
        updated_count = 0

        for vendor in queryset.select_related("user"):
            try:
                vendor.approve(request.user)
                updated_count += 1
            except ValidationError as exc:
                self.message_user(
                    request,
                    f"{vendor.store_name}: {exc}",
                    level=messages.ERROR,
                )

        self.message_user(
            request,
            f"{updated_count} vendor(s) approved successfully.",
            level=messages.SUCCESS,
        )

    @admin.action(description="Reject selected pending vendors")
    def reject_selected_vendors(self, request, queryset):
        updated_count = 0

        for vendor in queryset.select_related("user"):
            try:
                vendor.reject(request.user)
                updated_count += 1
            except ValidationError as exc:
                self.message_user(
                    request,
                    f"{vendor.store_name}: {exc}",
                    level=messages.ERROR,
                )

        self.message_user(
            request,
            f"{updated_count} vendor(s) rejected successfully.",
            level=messages.SUCCESS,
        )

    @admin.action(description="Suspend selected approved vendors")
    def suspend_selected_vendors(self, request, queryset):
        updated_count = 0

        for vendor in queryset.select_related("user"):
            try:
                vendor.suspend(request.user)
                updated_count += 1
            except ValidationError as exc:
                self.message_user(
                    request,
                    f"{vendor.store_name}: {exc}",
                    level=messages.ERROR,
                )

        self.message_user(
            request,
            f"{updated_count} vendor(s) suspended successfully.",
            level=messages.SUCCESS,
        )


@admin.register(VendorDocument)
class VendorDocumentAdmin(admin.ModelAdmin):
    list_display = [
        "vendor",
        "doc_type",
        "verified",
    ]

    list_filter = [
        "doc_type",
        "verified",
    ]

    search_fields = [
        "vendor__store_name",
        "vendor__user__email",
    ]

    readonly_fields = [
        "id",
    ]

    ordering = [
        "vendor",
        "doc_type",
    ]