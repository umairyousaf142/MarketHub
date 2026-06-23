import pytest
from django.core.exceptions import ValidationError

from apps.accounts.tests.factories import CustomerUserFactory
from apps.notifications.models import Notification
from apps.notifications.tests.factories import NotificationFactory


pytestmark = pytest.mark.django_db


def test_notification_factory_creates_valid_in_app_notification():
    notification = NotificationFactory()

    assert notification.id is not None
    assert notification.user_id is not None
    assert notification.type == Notification.Type.ORDER_CREATED
    assert notification.channel == Notification.Channel.IN_APP
    assert notification.title == "Order created"
    assert notification.body == "Your order has been created."
    assert notification.is_read is False
    assert notification.created_at is not None


def test_create_for_user_creates_in_app_notification():
    user = CustomerUserFactory()

    notification = Notification.create_for_user(
        user=user,
        type=Notification.Type.PAYMENT_SUCCESS,
        channel=Notification.Channel.IN_APP,
        title="Payment received",
        body="Your payment was successful.",
    )

    assert notification.user == user
    assert notification.type == Notification.Type.PAYMENT_SUCCESS
    assert notification.channel == Notification.Channel.IN_APP
    assert notification.title == "Payment received"
    assert notification.body == "Your payment was successful."
    assert notification.is_read is False


def test_create_for_user_creates_email_notification_as_read():
    user = CustomerUserFactory()

    notification = Notification.create_for_user(
        user=user,
        type=Notification.Type.WELCOME,
        channel=Notification.Channel.EMAIL,
        title="Welcome",
        body="Welcome to MarketHub.",
        is_read=False,
    )

    assert notification.channel == Notification.Channel.EMAIL
    assert notification.is_read is True


def test_create_for_user_creates_sms_notification_as_read():
    user = CustomerUserFactory()

    notification = Notification.create_for_user(
        user=user,
        type=Notification.Type.LOW_STOCK_ALERT,
        channel=Notification.Channel.SMS,
        title="Low stock",
        body="Inventory is below threshold.",
        is_read=False,
    )

    assert notification.channel == Notification.Channel.SMS
    assert notification.is_read is True


def test_email_notification_forces_is_read_true_on_save():
    notification = NotificationFactory(
        channel=Notification.Channel.EMAIL,
        is_read=False,
    )

    assert notification.is_read is True


def test_sms_notification_forces_is_read_true_on_save():
    notification = NotificationFactory(
        channel=Notification.Channel.SMS,
        is_read=False,
    )

    assert notification.is_read is True


def test_in_app_notification_can_be_created_as_unread():
    notification = NotificationFactory(
        channel=Notification.Channel.IN_APP,
        is_read=False,
    )

    assert notification.is_read is False


def test_in_app_notification_can_be_created_as_read():
    notification = NotificationFactory(
        channel=Notification.Channel.IN_APP,
        is_read=True,
    )

    assert notification.is_read is True


def test_mark_as_read_marks_in_app_notification_read():
    notification = NotificationFactory(
        channel=Notification.Channel.IN_APP,
        is_read=False,
    )

    result = notification.mark_as_read()

    notification.refresh_from_db()

    assert result == notification
    assert notification.is_read is True


def test_mark_as_unread_marks_in_app_notification_unread():
    notification = NotificationFactory(
        channel=Notification.Channel.IN_APP,
        is_read=True,
    )

    result = notification.mark_as_unread()

    notification.refresh_from_db()

    assert result == notification
    assert notification.is_read is False


def test_mark_as_read_on_email_notification_keeps_it_read():
    notification = NotificationFactory(
        channel=Notification.Channel.EMAIL,
        is_read=True,
    )

    result = notification.mark_as_read()

    notification.refresh_from_db()

    assert result == notification
    assert notification.is_read is True


def test_mark_as_unread_rejects_email_notification():
    notification = NotificationFactory(
        channel=Notification.Channel.EMAIL,
        is_read=True,
    )

    with pytest.raises(ValidationError):
        notification.mark_as_unread()


def test_mark_as_unread_rejects_sms_notification():
    notification = NotificationFactory(
        channel=Notification.Channel.SMS,
        is_read=True,
    )

    with pytest.raises(ValidationError):
        notification.mark_as_unread()


def test_blank_title_is_rejected():
    user = CustomerUserFactory()

    notification = Notification(
        user=user,
        type=Notification.Type.ORDER_CREATED,
        channel=Notification.Channel.IN_APP,
        title="",
        body="Body is present.",
    )

    with pytest.raises(ValidationError):
        notification.full_clean()


def test_whitespace_title_is_rejected():
    user = CustomerUserFactory()

    notification = Notification(
        user=user,
        type=Notification.Type.ORDER_CREATED,
        channel=Notification.Channel.IN_APP,
        title="   ",
        body="Body is present.",
    )

    with pytest.raises(ValidationError):
        notification.full_clean()


def test_blank_body_is_rejected():
    user = CustomerUserFactory()

    notification = Notification(
        user=user,
        type=Notification.Type.ORDER_CREATED,
        channel=Notification.Channel.IN_APP,
        title="Title is present.",
        body="",
    )

    with pytest.raises(ValidationError):
        notification.full_clean()


def test_whitespace_body_is_rejected():
    user = CustomerUserFactory()

    notification = Notification(
        user=user,
        type=Notification.Type.ORDER_CREATED,
        channel=Notification.Channel.IN_APP,
        title="Title is present.",
        body="   ",
    )

    with pytest.raises(ValidationError):
        notification.full_clean()


def test_invalid_channel_is_rejected():
    user = CustomerUserFactory()

    notification = Notification(
        user=user,
        type=Notification.Type.ORDER_CREATED,
        channel="PUSH",
        title="Invalid channel",
        body="This channel is not allowed.",
    )

    with pytest.raises(ValidationError):
        notification.full_clean()


def test_invalid_type_is_rejected():
    user = CustomerUserFactory()

    notification = Notification(
        user=user,
        type="UNKNOWN_TYPE",
        channel=Notification.Channel.IN_APP,
        title="Invalid type",
        body="This type is not allowed.",
    )

    with pytest.raises(ValidationError):
        notification.full_clean()


def test_queryset_for_user_returns_only_user_notifications():
    user = CustomerUserFactory()
    other_user = CustomerUserFactory()

    own_notification = NotificationFactory(user=user)
    other_notification = NotificationFactory(user=other_user)

    queryset = Notification.objects.for_user(user)

    assert own_notification in queryset
    assert other_notification not in queryset


def test_queryset_in_app_returns_only_in_app_notifications():
    in_app_notification = NotificationFactory(
        channel=Notification.Channel.IN_APP,
    )
    email_notification = NotificationFactory(
        channel=Notification.Channel.EMAIL,
    )
    sms_notification = NotificationFactory(
        channel=Notification.Channel.SMS,
    )

    queryset = Notification.objects.in_app()

    assert in_app_notification in queryset
    assert email_notification not in queryset
    assert sms_notification not in queryset


def test_queryset_unread_returns_only_unread_in_app_notifications():
    unread_in_app = NotificationFactory(
        channel=Notification.Channel.IN_APP,
        is_read=False,
    )
    read_in_app = NotificationFactory(
        channel=Notification.Channel.IN_APP,
        is_read=True,
    )
    email_notification = NotificationFactory(
        channel=Notification.Channel.EMAIL,
        is_read=False,
    )

    queryset = Notification.objects.unread()

    assert unread_in_app in queryset
    assert read_in_app not in queryset
    assert email_notification not in queryset


def test_queryset_read_returns_only_read_in_app_notifications():
    read_in_app = NotificationFactory(
        channel=Notification.Channel.IN_APP,
        is_read=True,
    )
    unread_in_app = NotificationFactory(
        channel=Notification.Channel.IN_APP,
        is_read=False,
    )
    email_notification = NotificationFactory(
        channel=Notification.Channel.EMAIL,
        is_read=True,
    )

    queryset = Notification.objects.read()

    assert read_in_app in queryset
    assert unread_in_app not in queryset
    assert email_notification not in queryset


def test_queryset_by_type_filters_notifications():
    matching_notification = NotificationFactory(
        type=Notification.Type.PAYMENT_SUCCESS,
    )
    other_notification = NotificationFactory(
        type=Notification.Type.ORDER_CREATED,
    )

    queryset = Notification.objects.by_type(Notification.Type.PAYMENT_SUCCESS)

    assert matching_notification in queryset
    assert other_notification not in queryset


def test_queryset_by_channel_filters_notifications():
    matching_notification = NotificationFactory(
        channel=Notification.Channel.SMS,
    )
    other_notification = NotificationFactory(
        channel=Notification.Channel.IN_APP,
    )

    queryset = Notification.objects.by_channel(Notification.Channel.SMS)

    assert matching_notification in queryset
    assert other_notification not in queryset


def test_notification_str_contains_user_type_and_channel():
    notification = NotificationFactory(
        type=Notification.Type.VENDOR_APPROVED,
        channel=Notification.Channel.IN_APP,
    )

    text = str(notification)

    assert str(notification.user_id) in text
    assert Notification.Type.VENDOR_APPROVED in text
    assert Notification.Channel.IN_APP in text


def test_notifications_are_ordered_newest_first():
    older_notification = NotificationFactory(
        title="Older notification",
    )
    newer_notification = NotificationFactory(
        title="Newer notification",
    )

    notifications = list(Notification.objects.all()[:2])

    assert notifications[0] == newer_notification
    assert notifications[1] == older_notification