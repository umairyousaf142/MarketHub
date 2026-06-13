import pytest
from rest_framework.test import APIClient

from .factories import CustomerUserFactory


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def customer_user(db):
    return CustomerUserFactory(password="StrongPass123!")


@pytest.fixture
def authenticated_client(api_client, customer_user):
    api_client.force_authenticate(user=customer_user)
    return api_client