import pytest
from django.urls import reverse

from .factories import AddressFactory, CustomerUserFactory


@pytest.mark.django_db
def test_authenticated_user_can_create_address(authenticated_client, customer_user):
    url = reverse("addresses-list")

    payload = {
        "label": "Home",
        "street": "Main Street 123",
        "city": "Lahore",
        "country": "Pakistan",
        "is_default": True,
    }

    response = authenticated_client.post(url, payload, format="json")

    assert response.status_code == 201
    assert response.data["label"] == "Home"
    assert response.data["is_default"] is True

    customer_user.refresh_from_db()
    assert customer_user.addresses.count() == 1


@pytest.mark.django_db
def test_user_can_only_list_own_addresses(authenticated_client, customer_user):
    other_user = CustomerUserFactory()

    own_address = AddressFactory(user=customer_user)
    AddressFactory(user=other_user)

    url = reverse("addresses-list")

    response = authenticated_client.get(url)
    # Paginated response handle karo
    results = response.data.get("results", response.data)

    assert response.status_code == 200  
    assert len(results) == 1
    assert results[0]["id"] == str(own_address.id)


@pytest.mark.django_db
def test_user_cannot_retrieve_other_user_address(authenticated_client):
    other_user = CustomerUserFactory()
    other_address = AddressFactory(user=other_user)

    url = reverse("addresses-detail", kwargs={"pk": other_address.id})

    response = authenticated_client.get(url)

    assert response.status_code == 404


@pytest.mark.django_db
def test_user_can_update_own_address(authenticated_client, customer_user):
    address = AddressFactory(user=customer_user, city="Lahore")

    url = reverse("addresses-detail", kwargs={"pk": address.id})

    response = authenticated_client.patch(
        url,
        {"city": "Karachi"},
        format="json",
    )

    assert response.status_code == 200

    address.refresh_from_db()
    assert address.city == "Karachi"


@pytest.mark.django_db
def test_user_can_delete_own_address(authenticated_client, customer_user):
    address = AddressFactory(user=customer_user)

    url = reverse("addresses-detail", kwargs={"pk": address.id})

    response = authenticated_client.delete(url)

    assert response.status_code == 204
    assert customer_user.addresses.count() == 0


@pytest.mark.django_db
def test_only_one_default_address_through_api(authenticated_client, customer_user):
    first_address = AddressFactory(user=customer_user, is_default=True)

    url = reverse("addresses-list")

    payload = {
        "label": "Office",
        "street": "Office Street",
        "city": "Islamabad",
        "country": "Pakistan",
        "is_default": True,
    }

    response = authenticated_client.post(url, payload, format="json")

    assert response.status_code == 201

    first_address.refresh_from_db()

    assert first_address.is_default is False
    assert customer_user.addresses.filter(is_default=True).count() == 1