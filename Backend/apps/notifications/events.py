from django.dispatch import Signal

from apps.notifications.models import Notification


notification_event = Signal()
multi_channel_notification_event = Signal()


def resolve_user_id(user):
    return getattr(user, "pk", user)


def emit_notification_event(
    *,
    user,
    notification_type,
    channel,
    title,
    body,
):
    notification_event.send(
        sender=emit_notification_event,
        user_id=str(resolve_user_id(user)),
        notification_type=notification_type,
        channel=channel,
        title=title,
        body=body,
    )


def emit_multi_channel_notification_event(
    *,
    user,
    notification_type,
    channels,
    title,
    body,
):
    multi_channel_notification_event.send(
        sender=emit_multi_channel_notification_event,
        user_id=str(resolve_user_id(user)),
        notification_type=notification_type,
        channels=list(channels),
        title=title,
        body=body,
    )


def emit_in_app_notification(
    *,
    user,
    notification_type,
    title,
    body,
):
    emit_notification_event(
        user=user,
        notification_type=notification_type,
        channel=Notification.Channel.IN_APP,
        title=title,
        body=body,
    )


def emit_email_notification(
    *,
    user,
    notification_type,
    title,
    body,
):
    emit_notification_event(
        user=user,
        notification_type=notification_type,
        channel=Notification.Channel.EMAIL,
        title=title,
        body=body,
    )


def emit_sms_notification(
    *,
    user,
    notification_type,
    title,
    body,
):
    emit_notification_event(
        user=user,
        notification_type=notification_type,
        channel=Notification.Channel.SMS,
        title=title,
        body=body,
    )