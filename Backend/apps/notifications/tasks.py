import logging

from celery import shared_task
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import send_mail

from apps.notifications.models import Notification


logger = logging.getLogger(__name__)


def get_notification_user(user_id):
    User = get_user_model()

    return User.objects.get(pk=user_id)


def get_default_from_email():
    return getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@markethub.local")


def create_notification_record(
    *,
    user,
    notification_type,
    channel,
    title,
    body,
):
    return Notification.create_for_user(
        user=user,
        type=notification_type,
        channel=channel,
        title=title,
        body=body,
    )


def deliver_email_notification(*, user, title, body):
    email = getattr(user, "email", "")

    if not email:
        logger.warning(
            "Email notification skipped because user has no email.",
            extra={"user_id": str(user.pk)},
        )

        return {
            "delivered": False,
            "reason": "missing_email",
        }

    send_mail(
        subject=title,
        message=body,
        from_email=get_default_from_email(),
        recipient_list=[email],
        fail_silently=False,
    )

    return {
        "delivered": True,
        "recipient": email,
    }


def deliver_sms_notification(*, user, title, body):
    phone = (
        getattr(user, "phone_number", None)
        or getattr(user, "phone", None)
        or getattr(user, "mobile", None)
    )

    logger.info(
        "SMS notification delivery placeholder executed.",
        extra={
            "user_id": str(user.pk),
            "phone_present": bool(phone),
            "title": title,
        },
    )

    return {
        "delivered": False,
        "reason": "sms_provider_not_configured",
        "phone_present": bool(phone),
    }


def dispatch_notification(
    *,
    user_id,
    notification_type,
    channel,
    title,
    body,
):
    user = get_notification_user(user_id)

    notification = create_notification_record(
        user=user,
        notification_type=notification_type,
        channel=channel,
        title=title,
        body=body,
    )

    delivery_result = {
        "delivered": True,
        "reason": None,
    }

    if channel == Notification.Channel.EMAIL:
        delivery_result = deliver_email_notification(
            user=user,
            title=title,
            body=body,
        )

    if channel == Notification.Channel.SMS:
        delivery_result = deliver_sms_notification(
            user=user,
            title=title,
            body=body,
        )

    return {
        "notification_id": str(notification.id),
        "user_id": str(user.pk),
        "type": notification_type,
        "channel": channel,
        "delivery": delivery_result,
    }


@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
)
def dispatch_notification_task(
    self,
    *,
    user_id,
    notification_type,
    channel,
    title,
    body,
):
    return dispatch_notification(
        user_id=user_id,
        notification_type=notification_type,
        channel=channel,
        title=title,
        body=body,
    )


@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
)
def dispatch_multi_channel_notification_task(
    self,
    *,
    user_id,
    notification_type,
    channels,
    title,
    body,
):
    results = []

    for channel in channels:
        results.append(
            dispatch_notification(
                user_id=user_id,
                notification_type=notification_type,
                channel=channel,
                title=title,
                body=body,
            )
        )

    return results