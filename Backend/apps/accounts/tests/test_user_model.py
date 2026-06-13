import pytest
from django.contrib.auth import get_user_model

from apps.accounts.models import Address
from .factories import AddressFactory, CustomerUserFactory

User = get_user_model()


@pytest.mark.django_db
def test_create_user_with_email_and_password():
    user = User.objects.create_user(
        email="TestUser@Example.COM",
        password="StrongPass123!",
    )

    assert user.email == "testuser@example.com"
    assert user.check_password("StrongPass123!")
    assert user.role == User.Role.CUSTOMER
    assert user.is_active is True
    assert user.is_staff is False
    assert user.is_superuser is False


@pytest.mark.django_db
def test_create_superuser_has_admin_role():
    user = User.objects.create_superuser(
        email="admin@example.com",
        password="StrongPass123!",
    )

    assert user.role == User.Role.ADMIN
    assert user.is_staff is True
    assert user.is_superuser is True
    assert user.is_verified is True


@pytest.mark.django_db
def test_user_model_does_not_use_username_field():
    user = CustomerUserFactory()

    assert User.USERNAME_FIELD == "email"
    assert not hasattr(user, "username")


@pytest.mark.django_db
def test_only_one_default_address_per_user():
    user = CustomerUserFactory()

    first_address = AddressFactory(user=user, is_default=True)
    second_address = AddressFactory(user=user, is_default=True)

    first_address.refresh_from_db()
    second_address.refresh_from_db()

    assert first_address.is_default is False
    assert second_address.is_default is True

    default_count = Address.objects.filter(user=user, is_default=True).count()
    assert default_count == 1