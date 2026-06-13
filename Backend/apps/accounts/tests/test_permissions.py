import pytest
from rest_framework.test import APIRequestFactory

from core.permissions.base import IsAdmin, IsCustomer, IsVendor
from .factories import AdminUserFactory, CustomerUserFactory, VendorUserFactory
from rest_framework.permissions import BasePermission


class IsAdminRole(BasePermission):
    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.role == "ADMIN"
        )


class IsVendorRole(BasePermission):
    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.role == "VENDOR"
        )


class IsCustomerRole(BasePermission):
    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.role == "CUSTOMER"
        )


@pytest.mark.django_db
def test_is_admin_role_permission_allows_admin():
    request = APIRequestFactory().get("/")
    request.user = AdminUserFactory()

    assert IsAdmin().has_permission(request, view=None) is True


@pytest.mark.django_db
def test_is_admin_role_permission_denies_customer():
    request = APIRequestFactory().get("/")
    request.user = CustomerUserFactory()

    assert IsAdmin().has_permission(request, view=None) is False


@pytest.mark.django_db
def test_is_vendor_role_permission_allows_vendor():
    request = APIRequestFactory().get("/")
    request.user = VendorUserFactory()

    assert IsVendor().has_permission(request, view=None) is True


@pytest.mark.django_db
def test_is_vendor_role_permission_denies_customer():
    request = APIRequestFactory().get("/")
    request.user = CustomerUserFactory()

    assert IsVendor().has_permission(request, view=None) is False


@pytest.mark.django_db
def test_is_customer_role_permission_allows_customer():
    request = APIRequestFactory().get("/")
    request.user = CustomerUserFactory()

    assert IsCustomer().has_permission(request, view=None) is True


@pytest.mark.django_db
def test_is_customer_role_permission_denies_vendor():
    request = APIRequestFactory().get("/")
    request.user = VendorUserFactory()

    assert IsCustomer().has_permission(request, view=None) is False
