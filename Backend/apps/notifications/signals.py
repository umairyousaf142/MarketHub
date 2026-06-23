from django.db import transaction
from django.dispatch import receiver

from apps.notifications.events import (
    multi_channel_notification_event,
    notification_event,
)
from apps.notifications.tasks import (
    dispatch_multi_channel_notification_task,
    dispatch_notification_task,
)


@receiver(notification_event)
def handle_notification_event(
    sender,
    *,
    user_id,
    notification_type,
    channel,
    title,
    body,
    **kwargs,
):
    payload = {
        "user_id": str(user_id),
        "notification_type": notification_type,
        "channel": channel,
        "title": title,
        "body": body,
    }

    transaction.on_commit(
        lambda payload=payload: dispatch_notification_task.delay(**payload)
    )


@receiver(multi_channel_notification_event)
def handle_multi_channel_notification_event(
    sender,
    *,
    user_id,
    notification_type,
    channels,
    title,
    body,
    **kwargs,
):
    payload = {
        "user_id": str(user_id),
        "notification_type": notification_type,
        "channels": list(channels),
        "title": title,
        "body": body,
    }

    transaction.on_commit(
        lambda payload=payload: dispatch_multi_channel_notification_task.delay(**payload)
    )