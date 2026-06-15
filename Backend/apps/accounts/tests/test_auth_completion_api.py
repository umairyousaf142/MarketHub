import pytest
from django.contrib.auth.tokens import default_token_generator
from django.urls import reverse
from rest_framework_simplejwt.tokens import RefreshToken
from unittest.mock import patch

from apps.accounts.tokens import encode_user_id, email_verification_token_generator
from .factories import CustomerUserFactory


@pytest.mark.django_db
def test_register_queues_email_verification_task(api_client, django_capture_on_commit_callbacks):
    url = reverse("accounts-register")

    payload = {
        "email": "queue-register@example.com",
        "role": "CUSTOMER",
        "password": "StrongPass123!",
        "password_confirm": "StrongPass123!",
    }

    with patch("apps.accounts.views.send_email_verification_task.delay") as mock_delay:
        with django_capture_on_commit_callbacks(execute=True):
            response = api_client.post(url, payload, format="json")

    assert response.status_code == 201
    assert response.data["detail"] == "Account created successfully. Please verify your email."
    assert response.data["user"]["email"] == "queue-register@example.com"
    assert "access" in response.data["tokens"]
    assert "refresh" in response.data["tokens"]

    mock_delay.assert_called_once()


@pytest.mark.django_db
def test_logout_blacklists_refresh_token(authenticated_client, customer_user):
    refresh = RefreshToken.for_user(customer_user)

    logout_url = reverse("accounts-logout")

    response = authenticated_client.post(
        logout_url,
        {"refresh": str(refresh)},
        format="json",
    )

    assert response.status_code == 200
    assert response.data["detail"] == "Logged out successfully."

    refresh_url = reverse("token-refresh")

    refresh_response = authenticated_client.post(
        refresh_url,
        {"refresh": str(refresh)},
        format="json",
    )

    assert refresh_response.status_code == 401


@pytest.mark.django_db
def test_logout_requires_authentication(api_client, customer_user):
    refresh = RefreshToken.for_user(customer_user)

    url = reverse("accounts-logout")

    response = api_client.post(
        url,
        {"refresh": str(refresh)},
        format="json",
    )

    assert response.status_code == 401


@pytest.mark.django_db
def test_change_password_success(
    authenticated_client,
    customer_user,
    django_capture_on_commit_callbacks,
):
    url = reverse("accounts-change-password")

    payload = {
        "old_password": "StrongPass123!",
        "new_password": "NewStrongPass123!",
        "new_password_confirm": "NewStrongPass123!",
    }

    with patch("apps.accounts.views.send_password_changed_email_task.delay") as mock_delay:
        with django_capture_on_commit_callbacks(execute=True):
            response = authenticated_client.post(url, payload, format="json")

    assert response.status_code == 200
    assert response.data["detail"] == "Password changed successfully."

    customer_user.refresh_from_db()

    assert customer_user.check_password("NewStrongPass123!") is True
    assert customer_user.check_password("StrongPass123!") is False

    mock_delay.assert_called_once_with(str(customer_user.id))


@pytest.mark.django_db
def test_change_password_fails_with_wrong_old_password(authenticated_client, customer_user):
    url = reverse("accounts-change-password")

    payload = {
        "old_password": "WrongOldPass123!",
        "new_password": "NewStrongPass123!",
        "new_password_confirm": "NewStrongPass123!",
    }

    response = authenticated_client.post(url, payload, format="json")

    assert response.status_code == 400

    customer_user.refresh_from_db()

    assert customer_user.check_password("StrongPass123!") is True


@pytest.mark.django_db
def test_forgot_password_returns_generic_response_for_existing_user(
    api_client,
    customer_user,
    django_capture_on_commit_callbacks,
):
    url = reverse("accounts-forgot-password")

    with patch("apps.accounts.views.send_password_reset_email_task.delay") as mock_delay:
        with django_capture_on_commit_callbacks(execute=True):
            response = api_client.post(
                url,
                {"email": customer_user.email},
                format="json",
            )

    assert response.status_code == 200
    assert response.data["detail"] == (
        "If an account exists with this email, a password reset link has been sent."
    )

    mock_delay.assert_called_once_with(str(customer_user.id))


@pytest.mark.django_db
def test_forgot_password_returns_same_response_for_unknown_email(
    api_client,
    django_capture_on_commit_callbacks,
):
    url = reverse("accounts-forgot-password")

    with patch("apps.accounts.views.send_password_reset_email_task.delay") as mock_delay:
        with django_capture_on_commit_callbacks(execute=True):
            response = api_client.post(
                url,
                {"email": "unknown@example.com"},
                format="json",
            )

    assert response.status_code == 200
    assert response.data["detail"] == (
        "If an account exists with this email, a password reset link has been sent."
    )

    mock_delay.assert_not_called()


@pytest.mark.django_db
def test_reset_password_success(api_client, customer_user, django_capture_on_commit_callbacks):
    uid = encode_user_id(customer_user)
    token = default_token_generator.make_token(customer_user)

    url = reverse("accounts-reset-password")

    payload = {
        "uid": uid,
        "token": token,
        "new_password": "ResetStrongPass123!",
        "new_password_confirm": "ResetStrongPass123!",
    }

    with patch("apps.accounts.views.send_password_changed_email_task.delay") as mock_delay:
        with django_capture_on_commit_callbacks(execute=True):
            response = api_client.post(url, payload, format="json")

    assert response.status_code == 200
    assert response.data["detail"] == "Password reset successfully."

    customer_user.refresh_from_db()

    assert customer_user.check_password("ResetStrongPass123!") is True

    mock_delay.assert_called_once_with(str(customer_user.id))


@pytest.mark.django_db
def test_reset_password_fails_with_invalid_token(api_client, customer_user):
    uid = encode_user_id(customer_user)

    url = reverse("accounts-reset-password")

    payload = {
        "uid": uid,
        "token": "invalid-token",
        "new_password": "ResetStrongPass123!",
        "new_password_confirm": "ResetStrongPass123!",
    }

    response = api_client.post(url, payload, format="json")

    assert response.status_code == 400

    customer_user.refresh_from_db()

    assert customer_user.check_password("StrongPass123!") is True


@pytest.mark.django_db
def test_verify_email_success(api_client, django_capture_on_commit_callbacks):
    user = CustomerUserFactory(
        email="verify@example.com",
        password="StrongPass123!",
        is_verified=False,
    )

    uid = encode_user_id(user)
    token = email_verification_token_generator.make_token(user)

    url = reverse("accounts-verify-email")

    payload = {
        "uid": uid,
        "token": token,
    }

    with patch("apps.accounts.views.send_welcome_email_task.delay") as mock_delay:
        with django_capture_on_commit_callbacks(execute=True):
            response = api_client.post(url, payload, format="json")

    assert response.status_code == 200
    assert response.data["detail"] == "Email verified successfully."

    user.refresh_from_db()

    assert user.is_verified is True

    mock_delay.assert_called_once_with(str(user.id))


@pytest.mark.django_db
def test_verify_email_fails_with_invalid_token(api_client):
    user = CustomerUserFactory(
        email="invalid-verify@example.com",
        password="StrongPass123!",
        is_verified=False,
    )

    uid = encode_user_id(user)

    url = reverse("accounts-verify-email")

    response = api_client.post(
        url,
        {
            "uid": uid,
            "token": "invalid-token",
        },
        format="json",
    )

    assert response.status_code == 400

    user.refresh_from_db()

    assert user.is_verified is False



@pytest.mark.django_db
def test_resend_verification_email_queues_task_for_unverified_user(
    api_client,
    django_capture_on_commit_callbacks,
):
    user = CustomerUserFactory(
        email="resend-unverified@example.com",
        password="StrongPass123!",
        is_verified=False,
    )

    url = reverse("accounts-resend-verification-email")

    with patch("apps.accounts.views.send_email_verification_task.delay") as mock_delay:
        with django_capture_on_commit_callbacks(execute=True):
            response = api_client.post(
                url,
                {"email": user.email},
                format="json",
            )

    assert response.status_code == 200
    assert response.data["detail"] == (
        "If an unverified account exists with this email, "
        "a verification link has been sent."
    )

    mock_delay.assert_called_once_with(str(user.id))


@pytest.mark.django_db
def test_resend_verification_email_does_not_queue_for_verified_user(
    api_client,
    django_capture_on_commit_callbacks,
):
    user = CustomerUserFactory(
        email="resend-verified@example.com",
        password="StrongPass123!",
        is_verified=True,
    )

    url = reverse("accounts-resend-verification-email")

    with patch("apps.accounts.views.send_email_verification_task.delay") as mock_delay:
        with django_capture_on_commit_callbacks(execute=True):
            response = api_client.post(
                url,
                {"email": user.email},
                format="json",
            )

    assert response.status_code == 200
    assert response.data["detail"] == (
        "If an unverified account exists with this email, "
        "a verification link has been sent."
    )

    mock_delay.assert_not_called()


@pytest.mark.django_db
def test_resend_verification_email_returns_same_response_for_unknown_email(
    api_client,
    django_capture_on_commit_callbacks,
):
    url = reverse("accounts-resend-verification-email")

    with patch("apps.accounts.views.send_email_verification_task.delay") as mock_delay:
        with django_capture_on_commit_callbacks(execute=True):
            response = api_client.post(
                url,
                {"email": "unknown-resend@example.com"},
                format="json",
            )

    assert response.status_code == 200
    assert response.data["detail"] == (
        "If an unverified account exists with this email, "
        "a verification link has been sent."
    )

    mock_delay.assert_not_called()