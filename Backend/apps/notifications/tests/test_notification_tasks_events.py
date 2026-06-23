import pytest
from django.test import override_settings

from apps.accounts.tests.factories import CustomerUserFactory
from apps.notifications import signals as notification_signals
from apps.notifications.events import (
    emit_email_notification,
    emit_in_app_notification,
    emit_multi_channel_notification_event,
    emit_notification_event,
    emit_sms_notification,
    resolve_user_id,
)
from apps.notifications.models import Notification
from apps.notifications.tasks import (
    create_notification_record,
    deliver_email_notification,
    deliver_sms_notification,
    dispatch_multi_channel_notification_task,
    dispatch_notification,
    dispatch_notification_task,
    get_default_from_email,
    get_notification_user,
)


pytestmark = pytest.mark.django_db


def test_resolve_user_id_handles_user_object_and_raw_id():
    user = CustomerUserFactory()

    assert resolve_user_id(user) == user.pk
    assert resolve_user_id(str(user.pk)) == str(user.pk)


def test_get_notification_user_returns_user():
    user = CustomerUserFactory()

    found_user = get_notification_user(str(user.id))

    assert found_user == user


def test_get_default_from_email_uses_settings_value():
    with override_settings(DEFAULT_FROM_EMAIL="support@markethub.test"):
        assert get_default_from_email() == "support@markethub.test"


def test_create_notification_record_creates_in_app_notification():
    user = CustomerUserFactory()

    notification = create_notification_record(
        user=user,
        notification_type=Notification.Type.ORDER_CREATED,
        channel=Notification.Channel.IN_APP,
        title="Order created",
        body="Your order has been created.",
    )

    assert notification.id is not None
    assert notification.user == user
    assert notification.type == Notification.Type.ORDER_CREATED
    assert notification.channel == Notification.Channel.IN_APP
    assert notification.title == "Order created"
    assert notification.body == "Your order has been created."
    assert notification.is_read is False


def test_deliver_email_notification_calls_send_mail(monkeypatch):
    user = CustomerUserFactory(email="customer@example.com")
    sent_messages = []

    def fake_send_mail(
        *,
        subject,
        message,
        from_email,
        recipient_list,
        fail_silently,
    ):
        sent_messages.append(
            {
                "subject": subject,
                "message": message,
                "from_email": from_email,
                "recipient_list": recipient_list,
                "fail_silently": fail_silently,
            }
        )
        return 1

    monkeypatch.setattr(
        "apps.notifications.tasks.send_mail",
        fake_send_mail,
    )

    with override_settings(DEFAULT_FROM_EMAIL="noreply@markethub.test"):
        result = deliver_email_notification(
            user=user,
            title="Welcome",
            body="Welcome to MarketHub.",
        )

    assert result["delivered"] is True
    assert result["recipient"] == "customer@example.com"

    assert sent_messages == [
        {
            "subject": "Welcome",
            "message": "Welcome to MarketHub.",
            "from_email": "noreply@markethub.test",
            "recipient_list": ["customer@example.com"],
            "fail_silently": False,
        }
    ]


def test_deliver_email_notification_skips_missing_email(monkeypatch):
    user = CustomerUserFactory()
    user.email = ""

    def fake_send_mail(*args, **kwargs):
        raise AssertionError("send_mail should not be called without email.")

    monkeypatch.setattr(
        "apps.notifications.tasks.send_mail",
        fake_send_mail,
    )

    result = deliver_email_notification(
        user=user,
        title="Missing email",
        body="This should not be sent.",
    )

    assert result["delivered"] is False
    assert result["reason"] == "missing_email"


def test_deliver_sms_notification_returns_placeholder_result():
    user = CustomerUserFactory()

    result = deliver_sms_notification(
        user=user,
        title="SMS title",
        body="SMS body",
    )

    assert result["delivered"] is False
    assert result["reason"] == "sms_provider_not_configured"
    assert "phone_present" in result


def test_dispatch_in_app_notification_creates_notification_record():
    user = CustomerUserFactory()

    result = dispatch_notification(
        user_id=str(user.id),
        notification_type=Notification.Type.ORDER_CREATED,
        channel=Notification.Channel.IN_APP,
        title="Order created",
        body="Your order has been created.",
    )

    notification = Notification.objects.get(id=result["notification_id"])

    assert result["user_id"] == str(user.id)
    assert result["type"] == Notification.Type.ORDER_CREATED
    assert result["channel"] == Notification.Channel.IN_APP
    assert result["delivery"]["delivered"] is True

    assert notification.user == user
    assert notification.channel == Notification.Channel.IN_APP
    assert notification.is_read is False


def test_dispatch_email_notification_creates_record_and_sends_email(monkeypatch):
    user = CustomerUserFactory(email="buyer@example.com")
    sent_messages = []

    def fake_send_mail(
        *,
        subject,
        message,
        from_email,
        recipient_list,
        fail_silently,
    ):
        sent_messages.append(
            {
                "subject": subject,
                "message": message,
                "from_email": from_email,
                "recipient_list": recipient_list,
                "fail_silently": fail_silently,
            }
        )
        return 1

    monkeypatch.setattr(
        "apps.notifications.tasks.send_mail",
        fake_send_mail,
    )

    with override_settings(DEFAULT_FROM_EMAIL="noreply@markethub.test"):
        result = dispatch_notification(
            user_id=str(user.id),
            notification_type=Notification.Type.WELCOME,
            channel=Notification.Channel.EMAIL,
            title="Welcome",
            body="Welcome to MarketHub.",
        )

    notification = Notification.objects.get(id=result["notification_id"])

    assert result["delivery"]["delivered"] is True
    assert result["delivery"]["recipient"] == "buyer@example.com"

    assert notification.user == user
    assert notification.channel == Notification.Channel.EMAIL
    assert notification.is_read is True

    assert len(sent_messages) == 1
    assert sent_messages[0]["recipient_list"] == ["buyer@example.com"]


def test_dispatch_sms_notification_creates_record_with_placeholder_delivery():
    user = CustomerUserFactory()

    result = dispatch_notification(
        user_id=str(user.id),
        notification_type=Notification.Type.LOW_STOCK_ALERT,
        channel=Notification.Channel.SMS,
        title="Low stock",
        body="Inventory is below threshold.",
    )

    notification = Notification.objects.get(id=result["notification_id"])

    assert result["delivery"]["delivered"] is False
    assert result["delivery"]["reason"] == "sms_provider_not_configured"

    assert notification.user == user
    assert notification.channel == Notification.Channel.SMS
    assert notification.is_read is True


def test_dispatch_notification_task_runs_dispatch():
    user = CustomerUserFactory()

    result = dispatch_notification_task(
        user_id=str(user.id),
        notification_type=Notification.Type.PAYMENT_SUCCESS,
        channel=Notification.Channel.IN_APP,
        title="Payment successful",
        body="Your payment was successful.",
    )

    notification = Notification.objects.get(id=result["notification_id"])

    assert notification.user == user
    assert notification.type == Notification.Type.PAYMENT_SUCCESS
    assert notification.channel == Notification.Channel.IN_APP


def test_dispatch_multi_channel_notification_task_creates_one_record_per_channel(
    monkeypatch,
):
    user = CustomerUserFactory(email="customer@example.com")
    sent_messages = []

    def fake_send_mail(
        *,
        subject,
        message,
        from_email,
        recipient_list,
        fail_silently,
    ):
        sent_messages.append(recipient_list)
        return 1

    monkeypatch.setattr(
        "apps.notifications.tasks.send_mail",
        fake_send_mail,
    )

    results = dispatch_multi_channel_notification_task(
        user_id=str(user.id),
        notification_type=Notification.Type.ORDER_CREATED,
        channels=[
            Notification.Channel.IN_APP,
            Notification.Channel.EMAIL,
            Notification.Channel.SMS,
        ],
        title="Order created",
        body="Your order has been created.",
    )

    assert len(results) == 3

    notifications = Notification.objects.filter(
        user=user,
        type=Notification.Type.ORDER_CREATED,
    )

    assert notifications.count() == 3
    assert notifications.filter(channel=Notification.Channel.IN_APP).exists()
    assert notifications.filter(channel=Notification.Channel.EMAIL).exists()
    assert notifications.filter(channel=Notification.Channel.SMS).exists()

    assert sent_messages == [["customer@example.com"]]


def test_emit_notification_event_queues_single_task_on_commit(monkeypatch):
    user = CustomerUserFactory()
    queued_payloads = []

    class FakeTask:
        def delay(self, **payload):
            queued_payloads.append(payload)

    monkeypatch.setattr(
        notification_signals,
        "dispatch_notification_task",
        FakeTask(),
    )
    monkeypatch.setattr(
        notification_signals.transaction,
        "on_commit",
        lambda callback: callback(),
    )

    emit_notification_event(
        user=user,
        notification_type=Notification.Type.ORDER_CREATED,
        channel=Notification.Channel.IN_APP,
        title="Order created",
        body="Your order has been created.",
    )

    assert queued_payloads == [
        {
            "user_id": str(user.id),
            "notification_type": Notification.Type.ORDER_CREATED,
            "channel": Notification.Channel.IN_APP,
            "title": "Order created",
            "body": "Your order has been created.",
        }
    ]


def test_emit_multi_channel_notification_event_queues_multi_task_on_commit(
    monkeypatch,
):
    user = CustomerUserFactory()
    queued_payloads = []

    class FakeTask:
        def delay(self, **payload):
            queued_payloads.append(payload)

    monkeypatch.setattr(
        notification_signals,
        "dispatch_multi_channel_notification_task",
        FakeTask(),
    )
    monkeypatch.setattr(
        notification_signals.transaction,
        "on_commit",
        lambda callback: callback(),
    )

    emit_multi_channel_notification_event(
        user=user,
        notification_type=Notification.Type.ORDER_CREATED,
        channels=[
            Notification.Channel.IN_APP,
            Notification.Channel.EMAIL,
        ],
        title="Order created",
        body="Your order has been created.",
    )

    assert queued_payloads == [
        {
            "user_id": str(user.id),
            "notification_type": Notification.Type.ORDER_CREATED,
            "channels": [
                Notification.Channel.IN_APP,
                Notification.Channel.EMAIL,
            ],
            "title": "Order created",
            "body": "Your order has been created.",
        }
    ]


def test_channel_helper_events_use_correct_channels(monkeypatch):
    user = CustomerUserFactory()
    queued_payloads = []

    class FakeTask:
        def delay(self, **payload):
            queued_payloads.append(payload)

    monkeypatch.setattr(
        notification_signals,
        "dispatch_notification_task",
        FakeTask(),
    )
    monkeypatch.setattr(
        notification_signals.transaction,
        "on_commit",
        lambda callback: callback(),
    )

    emit_in_app_notification(
        user=user,
        notification_type=Notification.Type.PAYMENT_SUCCESS,
        title="Payment successful",
        body="Your payment was successful.",
    )
    emit_email_notification(
        user=user,
        notification_type=Notification.Type.WELCOME,
        title="Welcome",
        body="Welcome to MarketHub.",
    )
    emit_sms_notification(
        user=user,
        notification_type=Notification.Type.LOW_STOCK_ALERT,
        title="Low stock",
        body="Inventory is below threshold.",
    )

    channels = [payload["channel"] for payload in queued_payloads]

    assert channels == [
        Notification.Channel.IN_APP,
        Notification.Channel.EMAIL,
        Notification.Channel.SMS,
    ]