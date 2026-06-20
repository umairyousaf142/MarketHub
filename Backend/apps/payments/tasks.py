from decimal import Decimal

from celery import shared_task
from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.mail import send_mail

from apps.payments.models import Payment, PaymentWebhookEvent, Refund


def money(amount, currency):
    value = Decimal(str(amount or "0.00")).quantize(Decimal("0.01"))

    return f"{currency} {value}"


def get_default_from_email():
    return getattr(settings, "DEFAULT_FROM_EMAIL", "no-reply@markethub.local")


def get_user_display_name(user):
    email = getattr(user, "email", "")

    return email or "Customer"


def get_customer_email_from_payment(payment):
    customer = payment.order.customer

    return getattr(customer, "email", "")


def build_payment_metadata(event):
    return {
        "webhook_event_id": str(event.id),
        "webhook_event_type": event.event_type,
        "webhook_provider": event.provider,
        "webhook_provider_event_id": event.event_id,
    }


def payload_value(payload, *keys):
    for key in keys:
        value = payload.get(key)

        if value:
            return value

    return ""


def find_payment_from_payload(payload, provider):
    payment_id = payload_value(
        payload,
        "payment_id",
        "payment",
        "payment_uuid",
        "markethub_payment_id",
    )

    if payment_id:
        try:
            payment = Payment.objects.select_related(
                "order",
                "order__customer",
            ).filter(id=payment_id).first()

            if payment:
                return payment
        except (ValueError, DjangoValidationError):
            pass

    provider_payment_id = payload_value(
        payload,
        "provider_payment_id",
        "provider_reference",
        "transaction_id",
        "gateway_payment_id",
    )

    if provider_payment_id:
        return Payment.objects.select_related(
            "order",
            "order__customer",
        ).filter(
            provider=provider,
            provider_payment_id=provider_payment_id,
        ).first()

    return None


def find_refund_from_payload(payload):
    refund_id = payload_value(
        payload,
        "refund_id",
        "refund",
        "refund_uuid",
        "markethub_refund_id",
    )

    if refund_id:
        try:
            refund = Refund.objects.select_related(
                "payment",
                "payment__order",
                "payment__order__customer",
            ).filter(id=refund_id).first()

            if refund:
                return refund
        except (ValueError, DjangoValidationError):
            pass

    provider_refund_id = payload_value(
        payload,
        "provider_refund_id",
        "provider_reference",
        "gateway_refund_id",
    )

    if provider_refund_id:
        return Refund.objects.select_related(
            "payment",
            "payment__order",
            "payment__order__customer",
        ).filter(provider_refund_id=provider_refund_id).first()

    return None


@shared_task(name="payments.send_payment_captured_email")
def send_payment_captured_email_task(payment_id):
    try:
        payment = Payment.objects.select_related(
            "order",
            "order__customer",
        ).get(id=payment_id)
    except (Payment.DoesNotExist, ValueError, DjangoValidationError):
        return {
            "sent": False,
            "reason": "payment_not_found",
            "payment_id": str(payment_id),
        }

    customer_email = get_customer_email_from_payment(payment)

    if not customer_email:
        return {
            "sent": False,
            "reason": "customer_email_missing",
            "payment_id": str(payment.id),
        }

    order = payment.order
    customer_name = get_user_display_name(order.customer)

    subject = f"Payment received for order {order.order_number}"
    message = (
        f"Hi {customer_name},\n\n"
        f"We have received your payment for order {order.order_number}.\n\n"
        f"Payment amount: {money(payment.amount_captured, payment.currency)}\n"
        f"Payment status: {payment.status}\n\n"
        "Thank you for shopping with MarketHub."
    )

    sent_count = send_mail(
        subject=subject,
        message=message,
        from_email=get_default_from_email(),
        recipient_list=[customer_email],
        fail_silently=False,
    )

    return {
        "sent": bool(sent_count),
        "payment_id": str(payment.id),
        "order_id": str(order.id),
        "order_number": order.order_number,
        "recipient": customer_email,
    }


@shared_task(name="payments.send_payment_failed_email")
def send_payment_failed_email_task(payment_id):
    try:
        payment = Payment.objects.select_related(
            "order",
            "order__customer",
        ).get(id=payment_id)
    except (Payment.DoesNotExist, ValueError, DjangoValidationError):
        return {
            "sent": False,
            "reason": "payment_not_found",
            "payment_id": str(payment_id),
        }

    customer_email = get_customer_email_from_payment(payment)

    if not customer_email:
        return {
            "sent": False,
            "reason": "customer_email_missing",
            "payment_id": str(payment.id),
        }

    order = payment.order
    customer_name = get_user_display_name(order.customer)

    subject = f"Payment failed for order {order.order_number}"
    message = (
        f"Hi {customer_name},\n\n"
        f"Your payment for order {order.order_number} could not be completed.\n\n"
        f"Payment amount: {money(payment.amount, payment.currency)}\n"
        f"Reason: {payment.failure_reason or 'Payment failed.'}\n\n"
        "Please try again or contact support if you need help."
    )

    sent_count = send_mail(
        subject=subject,
        message=message,
        from_email=get_default_from_email(),
        recipient_list=[customer_email],
        fail_silently=False,
    )

    return {
        "sent": bool(sent_count),
        "payment_id": str(payment.id),
        "order_id": str(order.id),
        "order_number": order.order_number,
        "recipient": customer_email,
    }


@shared_task(name="payments.send_refund_processed_email")
def send_refund_processed_email_task(refund_id):
    try:
        refund = Refund.objects.select_related(
            "payment",
            "payment__order",
            "payment__order__customer",
        ).get(id=refund_id)
    except (Refund.DoesNotExist, ValueError, DjangoValidationError):
        return {
            "sent": False,
            "reason": "refund_not_found",
            "refund_id": str(refund_id),
        }

    payment = refund.payment
    order = payment.order
    customer_email = get_customer_email_from_payment(payment)

    if not customer_email:
        return {
            "sent": False,
            "reason": "customer_email_missing",
            "refund_id": str(refund.id),
        }

    customer_name = get_user_display_name(order.customer)

    subject = f"Refund processed for order {order.order_number}"
    message = (
        f"Hi {customer_name},\n\n"
        f"Your refund for order {order.order_number} has been processed.\n\n"
        f"Refund amount: {money(refund.amount, refund.currency)}\n"
        f"Refund status: {refund.status}\n\n"
        "The refund may take some time to appear depending on the payment provider."
    )

    sent_count = send_mail(
        subject=subject,
        message=message,
        from_email=get_default_from_email(),
        recipient_list=[customer_email],
        fail_silently=False,
    )

    return {
        "sent": bool(sent_count),
        "refund_id": str(refund.id),
        "payment_id": str(payment.id),
        "order_id": str(order.id),
        "order_number": order.order_number,
        "recipient": customer_email,
    }


@shared_task(name="payments.process_payment_webhook_event")
def process_payment_webhook_event_task(webhook_event_id):
    try:
        event = PaymentWebhookEvent.objects.select_related(
            "related_payment",
            "related_refund",
        ).get(id=webhook_event_id)
    except (PaymentWebhookEvent.DoesNotExist, ValueError, DjangoValidationError):
        return {
            "processed": False,
            "reason": "webhook_event_not_found",
            "webhook_event_id": str(webhook_event_id),
        }

    if event.status in [
        PaymentWebhookEvent.Status.PROCESSED,
        PaymentWebhookEvent.Status.IGNORED,
    ]:
        return {
            "processed": False,
            "reason": "webhook_event_already_finalized",
            "webhook_event_id": str(event.id),
            "status": event.status,
        }

    if event.provider != Payment.Provider.MANUAL:
        event.mark_ignored("Webhook processing is not implemented for this provider yet.")

        return {
            "processed": False,
            "reason": "provider_processing_not_implemented",
            "webhook_event_id": str(event.id),
            "provider": event.provider,
            "status": event.status,
        }

    payload = event.payload or {}
    event_type = event.event_type or ""
    provider_reference = payload_value(
        payload,
        "provider_reference",
        "provider_payment_id",
        "provider_refund_id",
        "transaction_id",
    ) or event.event_id or f"WEBHOOK-{event.id}"

    metadata = build_payment_metadata(event)

    payment_created_events = {
        "manual.payment.created",
        "manual.payment.initiated",
        "payment.created",
        "payment.initiated",
    }

    payment_captured_events = {
        "manual.payment.captured",
        "manual.payment.succeeded",
        "payment.captured",
        "payment.succeeded",
    }

    payment_failed_events = {
        "manual.payment.failed",
        "payment.failed",
    }

    payment_cancelled_events = {
        "manual.payment.cancelled",
        "payment.cancelled",
    }

    refund_succeeded_events = {
        "manual.refund.succeeded",
        "refund.succeeded",
    }

    refund_failed_events = {
        "manual.refund.failed",
        "refund.failed",
    }

    try:
        if event_type in payment_created_events:
            event.mark_processed()

            return {
                "processed": True,
                "action": "payment_event_recorded",
                "webhook_event_id": str(event.id),
                "status": event.status,
            }

        if event_type in payment_captured_events:
            payment = find_payment_from_payload(payload, event.provider)

            if not payment:
                event.mark_failed("Payment not found for webhook payload.")

                return {
                    "processed": False,
                    "reason": "payment_not_found",
                    "webhook_event_id": str(event.id),
                    "status": event.status,
                }

            old_status = payment.status

            payment = payment.capture(
                provider_reference=provider_reference,
                metadata=metadata,
                commit_order=True,
            )

            event.related_payment = payment
            event.save(update_fields=["related_payment"])
            event.mark_processed()

            if old_status != Payment.Status.CAPTURED:
                send_payment_captured_email_task.delay(str(payment.id))

            return {
                "processed": True,
                "action": "payment_captured",
                "payment_id": str(payment.id),
                "webhook_event_id": str(event.id),
                "status": event.status,
            }

        if event_type in payment_failed_events:
            payment = find_payment_from_payload(payload, event.provider)

            if not payment:
                event.mark_failed("Payment not found for webhook payload.")

                return {
                    "processed": False,
                    "reason": "payment_not_found",
                    "webhook_event_id": str(event.id),
                    "status": event.status,
                }

            old_status = payment.status

            payment = payment.mark_failed(
                reason=payload_value(payload, "reason", "failure_reason")
                or "Payment failed via webhook.",
                provider_reference=provider_reference,
                metadata=metadata,
            )

            event.related_payment = payment
            event.save(update_fields=["related_payment"])
            event.mark_processed()

            if old_status != Payment.Status.FAILED:
                send_payment_failed_email_task.delay(str(payment.id))

            return {
                "processed": True,
                "action": "payment_failed",
                "payment_id": str(payment.id),
                "webhook_event_id": str(event.id),
                "status": event.status,
            }

        if event_type in payment_cancelled_events:
            payment = find_payment_from_payload(payload, event.provider)

            if not payment:
                event.mark_failed("Payment not found for webhook payload.")

                return {
                    "processed": False,
                    "reason": "payment_not_found",
                    "webhook_event_id": str(event.id),
                    "status": event.status,
                }

            payment = payment.cancel(
                reason=payload_value(payload, "reason", "failure_reason")
                or "Payment cancelled via webhook.",
                metadata=metadata,
            )

            event.related_payment = payment
            event.save(update_fields=["related_payment"])
            event.mark_processed()

            return {
                "processed": True,
                "action": "payment_cancelled",
                "payment_id": str(payment.id),
                "webhook_event_id": str(event.id),
                "status": event.status,
            }

        if event_type in refund_succeeded_events:
            refund = find_refund_from_payload(payload)

            if not refund:
                event.mark_failed("Refund not found for webhook payload.")

                return {
                    "processed": False,
                    "reason": "refund_not_found",
                    "webhook_event_id": str(event.id),
                    "status": event.status,
                }

            old_status = refund.status

            refund = refund.mark_succeeded(
                provider_reference=provider_reference,
                metadata=metadata,
            )

            event.related_refund = refund
            event.related_payment = refund.payment
            event.save(update_fields=["related_refund", "related_payment"])
            event.mark_processed()

            if old_status != Refund.Status.SUCCEEDED:
                send_refund_processed_email_task.delay(str(refund.id))

            return {
                "processed": True,
                "action": "refund_succeeded",
                "refund_id": str(refund.id),
                "payment_id": str(refund.payment.id),
                "webhook_event_id": str(event.id),
                "status": event.status,
            }

        if event_type in refund_failed_events:
            refund = find_refund_from_payload(payload)

            if not refund:
                event.mark_failed("Refund not found for webhook payload.")

                return {
                    "processed": False,
                    "reason": "refund_not_found",
                    "webhook_event_id": str(event.id),
                    "status": event.status,
                }

            refund = refund.mark_failed(
                reason=payload_value(payload, "reason", "failure_reason")
                or "Refund failed via webhook.",
                metadata=metadata,
            )

            event.related_refund = refund
            event.related_payment = refund.payment
            event.save(update_fields=["related_refund", "related_payment"])
            event.mark_processed()

            return {
                "processed": True,
                "action": "refund_failed",
                "refund_id": str(refund.id),
                "payment_id": str(refund.payment.id),
                "webhook_event_id": str(event.id),
                "status": event.status,
            }

        event.mark_ignored("Unsupported manual webhook event type.")

        return {
            "processed": False,
            "reason": "unsupported_manual_webhook_event_type",
            "webhook_event_id": str(event.id),
            "event_type": event_type,
            "status": event.status,
        }

    except DjangoValidationError as exc:
        event.mark_failed(str(exc))

        return {
            "processed": False,
            "reason": "validation_error",
            "webhook_event_id": str(event.id),
            "error": str(exc),
            "status": event.status,
        }
    except Exception as exc:
        event.mark_failed(str(exc))

        return {
            "processed": False,
            "reason": "unexpected_error",
            "webhook_event_id": str(event.id),
            "error": str(exc),
            "status": event.status,
        }