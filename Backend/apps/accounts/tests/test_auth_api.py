import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from .factories import CustomerUserFactory

User = get_user_model()


@pytest.mark.django_db
def test_register_customer_success(api_client):
    url = reverse("accounts-register")

    payload = {
        "email": "newcustomer@example.com",
        "role": User.Role.CUSTOMER,
        "password": "StrongPass123!",
        "password_confirm": "StrongPass123!",
    }

    response = api_client.post(url, payload, format="json")

    assert response.status_code == 201
    assert response.data["user"]["email"] == "newcustomer@example.com"
    assert response.data["user"]["role"] == User.Role.CUSTOMER
    assert "access" in response.data["tokens"]
    assert "refresh" in response.data["tokens"]


@pytest.mark.django_db
def test_register_vendor_success(api_client):
    url = reverse("accounts-register")

    payload = {
        "email": "vendor@example.com",
        "role": User.Role.VENDOR,
        "password": "StrongPass123!",
        "password_confirm": "StrongPass123!",
    }

    response = api_client.post(url, payload, format="json")

    assert response.status_code == 201
    assert response.data["user"]["role"] == User.Role.VENDOR


@pytest.mark.django_db
def test_public_registration_cannot_create_admin(api_client):
    url = reverse("accounts-register")

    payload = {
        "email": "fakeadmin@example.com",
        "role": User.Role.ADMIN,
        "password": "StrongPass123!",
        "password_confirm": "StrongPass123!",
    }

    response = api_client.post(url, payload, format="json")

    assert response.status_code == 400
    assert not User.objects.filter(email="fakeadmin@example.com").exists()


@pytest.mark.django_db
def test_register_password_mismatch(api_client):
    url = reverse("accounts-register")

    payload = {
        "email": "mismatch@example.com",
        "role": User.Role.CUSTOMER,
        "password": "StrongPass123!",
        "password_confirm": "DifferentPass123!",
    }

    response = api_client.post(url, payload, format="json")

    assert response.status_code == 400
    details = response.data.get("error", {}).get("details", response.data)
    assert "password_confirm" in details


@pytest.mark.django_db
def test_login_returns_tokens_and_user(api_client):
    user = CustomerUserFactory(
        email="login@example.com",
        password="StrongPass123!",
    )

    url = reverse("accounts-login")

    response = api_client.post(
        url,
        {
            "email": user.email,
            "password": "StrongPass123!",
        },
        format="json",
    )

    assert response.status_code == 200
    assert "access" in response.data
    assert "refresh" in response.data
    assert response.data["user"]["email"] == user.email


@pytest.mark.django_db
def test_login_with_invalid_credentials_fails(api_client):
    user = CustomerUserFactory(
        email="wrongpass@example.com",
        password="StrongPass123!",
    )

    url = reverse("accounts-login")

    response = api_client.post(
        url,
        {
            "email": user.email,
            "password": "WrongPassword123!",
        },
        format="json",
    )

    assert response.status_code == 401


@pytest.mark.django_db
def test_me_endpoint_requires_authentication(api_client):
    url = reverse("accounts-me")

    response = api_client.get(url)

    assert response.status_code == 401


@pytest.mark.django_db
def test_me_endpoint_returns_authenticated_user(authenticated_client, customer_user):
    url = reverse("accounts-me")

    response = authenticated_client.get(url)

    assert response.status_code == 200
    assert response.data["id"] == str(customer_user.id)
    assert response.data["email"] == customer_user.email