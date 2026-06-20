from django.contrib import admin, messages
from django.core.exceptions import ValidationError

from apps.payments.models import (
    Payment,
    PaymentTransaction,
    PaymentWebhookEvent,
    Refund,
)


class PaymentTransactionInline(admin.TabularInline):
    model = PaymentTransaction
    extra = 0
    can_delete = False
    fields = [
        "transaction_type",
        "amount",
        "currency",
        "provider_reference",
        "is_successful",
        "failure_reason",
        "created_at",
    ]
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        return False


class RefundInline(admin.TabularInline):
    model = Refund
    extra = 0
    fields = [
        "amount",
        "currency",
        "status",
        "reason",
        "provider_refund_id",
        "requested_by",
        "processed_at",
        "failed_at",
        "created_at",
    ]
    readonly_fields = [
        "processed_at",
        "failed_at",
        "created_at",
    ]


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "order",
        "provider",
        "status",
        "amount",
        "amount_captured",
        "currency",
        "created_at",
    ]
    list_filter = [
        "provider",
        "status",
        "currency",
        "created_at",
    ]
    search_fields = [
        "id",
        "order__order_number",
        "provider_payment_id",
        "idempotency_key",
        "order__customer__email",
    ]
    readonly_fields = [
        "id",
        "amount_captured",
        "authorized_at",
        "captured_at",
        "failed_at",
        "cancelled_at",
        "created_at",
        "updated_at",
    ]
    autocomplete_fields = [
        "order",
        "created_by",
    ]
    inlines = [
        PaymentTransactionInline,
        RefundInline,
    ]
    actions = [
        "mark_selected_as_captured",
        "mark_selected_as_failed",
        "cancel_selected_payments",
    ]

    fieldsets = (
        (
            "Payment",
            {
                "fields": (
                    "id",
                    "order",
                    "provider",
                    "status",
                    "amount",
                    "amount_captured",
                    "currency",
                )
            },
        ),
        (
            "Provider Data",
            {
                "fields": (
                    "provider_payment_id",
                    "provider_client_secret",
                    "idempotency_key",
                    "metadata",
                )
            },
        ),
        (
            "Failure / Audit",
            {
                "fields": (
                    "failure_reason",
                    "created_by",
                    "authorized_at",
                    "captured_at",
                    "failed_at",
                    "cancelled_at",
                    "created_at",
                    "updated_at",
                )
            },
        ),
    )

    @admin.action(description="Mark selected manual payments as captured")
    def mark_selected_as_captured(self, request, queryset):
        success_count = 0
        failure_count = 0

        for payment in queryset:
            try:
                payment.capture(
                    provider_reference=f"ADMIN-MANUAL-{payment.id}",
                    metadata={
                        "admin_action": "mark_selected_as_captured",
                        "admin_user": request.user.email,
                    },
                    commit_order=True,
                )
                success_count += 1
            except ValidationError as exc:
                failure_count += 1
                self.message_user(
                    request,
                    f"Payment {payment.id} failed: {exc}",
                    level=messages.ERROR,
                )

        self.message_user(
            request,
            f"{success_count} payment(s) captured. {failure_count} failed.",
            level=messages.INFO,
        )

    @admin.action(description="Mark selected payments as failed")
    def mark_selected_as_failed(self, request, queryset):
        success_count = 0
        failure_count = 0

        for payment in queryset:
            try:
                payment.mark_failed(
                    reason="Marked as failed from admin.",
                    metadata={
                        "admin_action": "mark_selected_as_failed",
                        "admin_user": request.user.email,
                    },
                )
                success_count += 1
            except ValidationError as exc:
                failure_count += 1
                self.message_user(
                    request,
                    f"Payment {payment.id} failed: {exc}",
                    level=messages.ERROR,
                )

        self.message_user(
            request,
            f"{success_count} payment(s) marked as failed. {failure_count} failed.",
            level=messages.INFO,
        )

    @admin.action(description="Cancel selected pending payments")
    def cancel_selected_payments(self, request, queryset):
        success_count = 0
        failure_count = 0

        for payment in queryset:
            try:
                payment.cancel(
                    reason="Cancelled from admin.",
                    metadata={
                        "admin_action": "cancel_selected_payments",
                        "admin_user": request.user.email,
                    },
                )
                success_count += 1
            except ValidationError as exc:
                failure_count += 1
                self.message_user(
                    request,
                    f"Payment {payment.id} failed: {exc}",
                    level=messages.ERROR,
                )

        self.message_user(
            request,
            f"{success_count} payment(s) cancelled. {failure_count} failed.",
            level=messages.INFO,
        )


@admin.register(PaymentTransaction)
class PaymentTransactionAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "payment",
        "transaction_type",
        "amount",
        "currency",
        "provider_reference",
        "is_successful",
        "created_at",
    ]
    list_filter = [
        "transaction_type",
        "currency",
        "is_successful",
        "created_at",
    ]
    search_fields = [
        "id",
        "payment__id",
        "payment__order__order_number",
        "provider_reference",
        "failure_reason",
    ]
    readonly_fields = [
        "id",
        "payment",
        "transaction_type",
        "amount",
        "currency",
        "provider_reference",
        "is_successful",
        "failure_reason",
        "raw_response",
        "created_at",
    ]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(Refund)
class RefundAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "payment",
        "amount",
        "currency",
        "status",
        "provider_refund_id",
        "created_at",
    ]
    list_filter = [
        "status",
        "currency",
        "created_at",
    ]
    search_fields = [
        "id",
        "payment__id",
        "payment__order__order_number",
        "provider_refund_id",
        "idempotency_key",
    ]
    readonly_fields = [
        "id",
        "processed_at",
        "failed_at",
        "created_at",
        "updated_at",
    ]
    autocomplete_fields = [
        "payment",
        "requested_by",
    ]
    actions = [
        "mark_selected_refunds_succeeded",
        "mark_selected_refunds_failed",
    ]

    @admin.action(description="Mark selected refunds as succeeded")
    def mark_selected_refunds_succeeded(self, request, queryset):
        success_count = 0
        failure_count = 0

        for refund in queryset:
            try:
                refund.mark_succeeded(
                    provider_reference=f"ADMIN-MANUAL-REFUND-{refund.id}",
                    metadata={
                        "admin_action": "mark_selected_refunds_succeeded",
                        "admin_user": request.user.email,
                    },
                )
                success_count += 1
            except ValidationError as exc:
                failure_count += 1
                self.message_user(
                    request,
                    f"Refund {refund.id} failed: {exc}",
                    level=messages.ERROR,
                )

        self.message_user(
            request,
            f"{success_count} refund(s) succeeded. {failure_count} failed.",
            level=messages.INFO,
        )

    @admin.action(description="Mark selected refunds as failed")
    def mark_selected_refunds_failed(self, request, queryset):
        success_count = 0
        failure_count = 0

        for refund in queryset:
            try:
                refund.mark_failed(
                    reason="Marked as failed from admin.",
                    metadata={
                        "admin_action": "mark_selected_refunds_failed",
                        "admin_user": request.user.email,
                    },
                )
                success_count += 1
            except ValidationError as exc:
                failure_count += 1
                self.message_user(
                    request,
                    f"Refund {refund.id} failed: {exc}",
                    level=messages.ERROR,
                )

        self.message_user(
            request,
            f"{success_count} refund(s) failed. {failure_count} action failures.",
            level=messages.INFO,
        )


@admin.register(PaymentWebhookEvent)
class PaymentWebhookEventAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "provider",
        "event_type",
        "event_id",
        "status",
        "related_payment",
        "related_refund",
        "received_at",
    ]
    list_filter = [
        "provider",
        "event_type",
        "status",
        "received_at",
    ]
    search_fields = [
        "id",
        "event_id",
        "event_type",
        "related_payment__id",
        "related_payment__order__order_number",
        "related_refund__id",
        "error_message",
    ]
    readonly_fields = [
        "id",
        "received_at",
        "processed_at",
    ]
    autocomplete_fields = [
        "related_payment",
        "related_refund",
    ]