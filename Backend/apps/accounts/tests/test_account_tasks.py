import pytest
from django.core import mail
from django.test import override_settings

from apps.accounts.tasks import (
    send_email_verification_task,
    send_password_changed_email_task,
    send_password_reset_email_task,
    send_welcome_email_task,
)
from .factories import CustomerUserFactory


@pytest.mark.django_db
@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEFAULT_FROM_EMAIL="MarketHub <noreply@testserver.local>",
    FRONTEND_URL="http://localhost:3000",
    VERIFY_EMAIL_PATH="/verify-email",
    RESET_PASSWORD_PATH="/reset-password",
)
def test_send_email_verification_task_sends_email():
    user = CustomerUserFactory(
        email="verification-task@example.com",
        is_verified=False,
    )

    result = send_email_verification_task.apply(args=[str(user.id)])

    assert result.get() == "sent"
    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == [user.email]
    assert mail.outbox[0].subject == "Verify your MarketHub email"
    assert "/verify-email" in mail.outbox[0].body


@pytest.mark.django_db
@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEFAULT_FROM_EMAIL="MarketHub <noreply@testserver.local>",
    FRONTEND_URL="http://localhost:3000",
    RESET_PASSWORD_PATH="/reset-password",
)
def test_send_password_reset_email_task_sends_email():
    user = CustomerUserFactory(
        email="password-reset-task@example.com",
    )

    result = send_password_reset_email_task.apply(args=[str(user.id)])

    assert result.get() == "sent"
    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == [user.email]
    assert mail.outbox[0].subject == "Reset your MarketHub password"
    assert "/reset-password" in mail.outbox[0].body


@pytest.mark.django_db
@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEFAULT_FROM_EMAIL="MarketHub <noreply@testserver.local>",
)
def test_send_welcome_email_task_sends_email():
    user = CustomerUserFactory(
        email="welcome-task@example.com",
    )

    result = send_welcome_email_task.apply(args=[str(user.id)])

    assert result.get() == "sent"
    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == [user.email]
    assert mail.outbox[0].subject == "Welcome to MarketHub"


@pytest.mark.django_db
@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEFAULT_FROM_EMAIL="MarketHub <noreply@testserver.local>",
)
def test_send_password_changed_email_task_sends_email():
    user = CustomerUserFactory(
        email="password-changed-task@example.com",
    )

    result = send_password_changed_email_task.apply(args=[str(user.id)])

    assert result.get() == "sent"
    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == [user.email]
    assert mail.outbox[0].subject == "Your MarketHub password was changed"


@pytest.mark.django_db
def test_email_verification_task_skips_missing_user():
    result = send_email_verification_task.apply(
        args=["00000000-0000-0000-0000-000000000000"]
    )

    assert result.get() == "skipped:user_not_found"


@pytest.mark.django_db
def test_email_verification_task_skips_already_verified_user():
    user = CustomerUserFactory(
        email="already-verified@example.com",
        is_verified=True,
    )

    result = send_email_verification_task.apply(args=[str(user.id)])

    assert result.get() == "skipped:already_verified"