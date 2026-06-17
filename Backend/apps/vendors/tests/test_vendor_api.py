from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse
from rest_framework import status

from apps.accounts.tests.factories import (
    AdminUserFactory,
    CustomerUserFactory,
    VendorUserFactory,
)
from apps.vendors.models import Vendor, VendorDocument
from apps.vendors.tests.factories import (
    CommissionPlanFactory,
    VendorDocumentFactory,
    VendorFactory,
)

def get_results(response):
    if isinstance(response.data, dict) and "results" in response.data:
        return response.data["results"]

    return response.data


def get_error_details(response):
    if isinstance(response.data, dict) and "error" in response.data:
        return response.data["error"].get("details", {})

    return response.data


@pytest.mark.django_db
def test_vendor_onboarding_requires_authentication(api_client):
    url = reverse("vendor-onboarding")

    response = api_client.post(
        url,
        {"store_name": "Unauth Store"},
        format="json",
    )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.django_db
def test_customer_cannot_create_vendor_profile(api_client):
    customer = CustomerUserFactory()
    api_client.force_authenticate(user=customer)

    url = reverse("vendor-onboarding")

    response = api_client.post(
        url,
        {"store_name": "Customer Store"},
        format="json",
    )

    assert response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
def test_vendor_user_can_complete_onboarding(api_client):
    vendor_user = VendorUserFactory()
    api_client.force_authenticate(user=vendor_user)

    url = reverse("vendor-onboarding")

    response = api_client.post(
        url,
        {"store_name": "My Vendor Store"},
        format="json",
    )

    assert response.status_code == status.HTTP_201_CREATED
    assert response.data["store_name"] == "My Vendor Store"
    assert response.data["status"] == Vendor.Status.PENDING

    vendor = Vendor.objects.get(user=vendor_user)

    assert vendor.store_name == "My Vendor Store"
    assert vendor.status == Vendor.Status.PENDING


@pytest.mark.django_db
def test_vendor_user_cannot_onboard_twice(api_client):
    vendor = VendorFactory()
    api_client.force_authenticate(user=vendor.user)

    url = reverse("vendor-onboarding")

    response = api_client.post(
        url,
        {"store_name": "Second Store"},
        format="json",
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert Vendor.objects.filter(user=vendor.user).count() == 1


@pytest.mark.django_db
def test_vendor_onboarding_rejects_duplicate_store_name(api_client):
    VendorFactory(store_name="Existing Store")

    vendor_user = VendorUserFactory()
    api_client.force_authenticate(user=vendor_user)

    url = reverse("vendor-onboarding")

    response = api_client.post(
        url,
        {"store_name": "existing store"},
        format="json",
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    details = get_error_details(response)
    assert "store_name" in details


@pytest.mark.django_db
def test_vendor_me_returns_404_when_profile_missing(api_client):
    vendor_user = VendorUserFactory()
    api_client.force_authenticate(user=vendor_user)

    url = reverse("vendor-me")

    response = api_client.get(url)

    assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.django_db
def test_vendor_can_get_own_profile(api_client):
    vendor = VendorFactory(store_name="Own Store")
    api_client.force_authenticate(user=vendor.user)

    url = reverse("vendor-me")

    response = api_client.get(url)

    assert response.status_code == status.HTTP_200_OK
    assert response.data["id"] == str(vendor.id)
    assert response.data["store_name"] == "Own Store"
    assert response.data["user_email"] == vendor.user.email


@pytest.mark.django_db
def test_vendor_can_update_own_store_name(api_client):
    vendor = VendorFactory(store_name="Old Store")
    api_client.force_authenticate(user=vendor.user)

    url = reverse("vendor-me")

    response = api_client.patch(
        url,
        {"store_name": "Updated Store"},
        format="json",
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.data["store_name"] == "Updated Store"

    vendor.refresh_from_db()

    assert vendor.store_name == "Updated Store"


@pytest.mark.django_db
def test_customer_cannot_access_vendor_me(api_client):
    customer = CustomerUserFactory()
    api_client.force_authenticate(user=customer)

    url = reverse("vendor-me")

    response = api_client.get(url)

    assert response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
def test_vendor_can_upload_document(api_client, tmp_path):
    vendor = VendorFactory()
    api_client.force_authenticate(user=vendor.user)

    file = SimpleUploadedFile(
        "nic.jpg",
        b"fake-image-content",
        content_type="image/jpeg",
    )

    url = reverse("vendor-documents-list")

    with override_settings(MEDIA_ROOT=tmp_path):
        response = api_client.post(
            url,
            {
                "doc_type": VendorDocument.DocumentType.NIC,
                "file": file,
            },
            format="multipart",
        )

    assert response.status_code == status.HTTP_201_CREATED
    assert response.data["doc_type"] == VendorDocument.DocumentType.NIC
    assert response.data["verified"] is False
    assert VendorDocument.objects.filter(vendor=vendor).count() == 1


@pytest.mark.django_db
def test_vendor_cannot_set_document_verified_during_upload(api_client, tmp_path):
    vendor = VendorFactory()
    api_client.force_authenticate(user=vendor.user)

    file = SimpleUploadedFile(
        "nic.jpg",
        b"fake-image-content",
        content_type="image/jpeg",
    )

    url = reverse("vendor-documents-list")

    with override_settings(MEDIA_ROOT=tmp_path):
        response = api_client.post(
            url,
            {
                "doc_type": VendorDocument.DocumentType.NIC,
                "file": file,
                "verified": True,
            },
            format="multipart",
        )

    assert response.status_code == status.HTTP_201_CREATED
    assert response.data["verified"] is False

    document = VendorDocument.objects.get(vendor=vendor)

    assert document.verified is False


@pytest.mark.django_db
def test_vendor_document_list_only_returns_own_documents(api_client):
    own_vendor = VendorFactory()
    other_vendor = VendorFactory()

    own_document = VendorDocumentFactory(vendor=own_vendor)
    VendorDocumentFactory(vendor=other_vendor)

    api_client.force_authenticate(user=own_vendor.user)

    url = reverse("vendor-documents-list")

    response = api_client.get(url)

    assert response.status_code == status.HTTP_200_OK
    assert response.data["count"] == 1
    results = get_results(response)
    assert len(results) == 1
    assert results[0]["id"] == str(own_document.id)


@pytest.mark.django_db
def test_vendor_cannot_retrieve_other_vendor_document(api_client):
    own_vendor = VendorFactory()
    other_vendor = VendorFactory()

    other_document = VendorDocumentFactory(vendor=other_vendor)

    api_client.force_authenticate(user=own_vendor.user)

    url = reverse(
        "vendor-documents-detail",
        kwargs={"pk": other_document.id},
    )

    response = api_client.get(url)

    assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.django_db
def test_vendor_document_upload_rejects_invalid_extension(api_client, tmp_path):
    vendor = VendorFactory()
    api_client.force_authenticate(user=vendor.user)

    file = SimpleUploadedFile(
        "document.exe",
        b"fake-content",
        content_type="application/octet-stream",
    )

    url = reverse("vendor-documents-list")

    with override_settings(MEDIA_ROOT=tmp_path):
        response = api_client.post(
            url,
            {
                "doc_type": VendorDocument.DocumentType.NIC,
                "file": file,
            },
            format="multipart",
        )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    details = get_error_details(response)
    assert "file" in details


@pytest.mark.django_db
def test_vendor_document_upload_rejects_large_file(api_client, tmp_path):
    vendor = VendorFactory()
    api_client.force_authenticate(user=vendor.user)

    file = SimpleUploadedFile(
        "large.pdf",
        b"x" * ((5 * 1024 * 1024) + 1),
        content_type="application/pdf",
    )

    url = reverse("vendor-documents-list")

    with override_settings(MEDIA_ROOT=tmp_path):
        response = api_client.post(
            url,
            {
                "doc_type": VendorDocument.DocumentType.NIC,
                "file": file,
            },
            format="multipart",
        )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    details = get_error_details(response)
    assert "file" in details


@pytest.mark.django_db
def test_admin_can_list_vendors(api_client):
    admin = AdminUserFactory()
    vendor = VendorFactory(store_name="Listed Store")

    api_client.force_authenticate(user=admin)

    url = reverse("admin-vendors-list")

    response = api_client.get(url)

    assert response.status_code == status.HTTP_200_OK
    assert response.data["count"] == 1

    results = get_results(response)

    assert len(results) == 1
    assert results[0]["id"] == str(vendor.id)
    assert results[0]["store_name"] == "Listed Store"


@pytest.mark.django_db
def test_non_admin_cannot_list_admin_vendors(api_client):
    vendor_user = VendorUserFactory()
    api_client.force_authenticate(user=vendor_user)

    url = reverse("admin-vendors-list")

    response = api_client.get(url)

    assert response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
def test_admin_can_approve_vendor(api_client):
    admin = AdminUserFactory()
    vendor = VendorFactory(status=Vendor.Status.PENDING)

    api_client.force_authenticate(user=admin)

    url = reverse(
        "admin-vendors-approve",
        kwargs={"pk": vendor.id},
    )

    response = api_client.post(url)

    assert response.status_code == status.HTTP_200_OK
    assert response.data["status"] == Vendor.Status.APPROVED

    vendor.refresh_from_db()

    assert vendor.status == Vendor.Status.APPROVED
    assert vendor.approved_by == admin
    assert vendor.approved_at is not None


@pytest.mark.django_db
def test_admin_can_reject_vendor(api_client):
    admin = AdminUserFactory()
    vendor = VendorFactory(status=Vendor.Status.PENDING)

    api_client.force_authenticate(user=admin)

    url = reverse(
        "admin-vendors-reject",
        kwargs={"pk": vendor.id},
    )

    response = api_client.post(url)

    assert response.status_code == status.HTTP_200_OK
    assert response.data["status"] == Vendor.Status.REJECTED

    vendor.refresh_from_db()

    assert vendor.status == Vendor.Status.REJECTED
    assert vendor.approved_by is None
    assert vendor.approved_at is None


@pytest.mark.django_db
def test_admin_can_suspend_approved_vendor(api_client):
    admin = AdminUserFactory()
    vendor = VendorFactory(status=Vendor.Status.PENDING)

    vendor.approve(admin)

    api_client.force_authenticate(user=admin)

    url = reverse(
        "admin-vendors-suspend",
        kwargs={"pk": vendor.id},
    )

    response = api_client.post(url)

    assert response.status_code == status.HTTP_200_OK
    assert response.data["status"] == Vendor.Status.SUSPENDED

    vendor.refresh_from_db()

    assert vendor.status == Vendor.Status.SUSPENDED


@pytest.mark.django_db
def test_admin_vendor_approve_invalid_transition_returns_400(api_client):
    admin = AdminUserFactory()
    vendor = VendorFactory(status=Vendor.Status.PENDING)

    vendor.approve(admin)

    api_client.force_authenticate(user=admin)

    url = reverse(
        "admin-vendors-approve",
        kwargs={"pk": vendor.id},
    )

    response = api_client.post(url)

    assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
def test_admin_can_list_commission_plans(api_client):
    admin = AdminUserFactory()
    plan = CommissionPlanFactory(
        name="Default",
        percentage=Decimal("10.00"),
        is_default=True,
    )

    api_client.force_authenticate(user=admin)

    url = reverse("admin-commission-plans-list")

    response = api_client.get(url)

    assert response.status_code == status.HTTP_200_OK
    assert response.data["count"] == 1

    results = get_results(response)

    assert len(results) == 1
    assert results[0]["id"] == str(plan.id)
    assert results[0]["name"] == "Default"


@pytest.mark.django_db
def test_non_admin_cannot_access_commission_plans(api_client):
    vendor_user = VendorUserFactory()
    api_client.force_authenticate(user=vendor_user)

    url = reverse("admin-commission-plans-list")

    response = api_client.get(url)

    assert response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
def test_admin_can_create_commission_plan(api_client):
    admin = AdminUserFactory()

    CommissionPlanFactory(
        name="Default",
        percentage=Decimal("10.00"),
        is_default=True,
    )

    api_client.force_authenticate(user=admin)

    url = reverse("admin-commission-plans-list")

    response = api_client.post(
        url,
        {
            "name": "Premium",
            "percentage": "8.50",
            "is_default": False,
        },
        format="json",
    )

    assert response.status_code == status.HTTP_201_CREATED
    assert response.data["name"] == "Premium"
    assert response.data["percentage"] == "8.50"
    assert response.data["is_default"] is False


@pytest.mark.django_db
def test_admin_can_update_commission_plan(api_client):
    admin = AdminUserFactory()

    plan = CommissionPlanFactory(
        name="Default",
        percentage=Decimal("10.00"),
        is_default=True,
    )

    api_client.force_authenticate(user=admin)

    url = reverse(
        "admin-commission-plans-detail",
        kwargs={"pk": plan.id},
    )

    response = api_client.patch(
        url,
        {
            "percentage": "12.00",
        },
        format="json",
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.data["percentage"] == "12.00"

    plan.refresh_from_db()

    assert plan.percentage == Decimal("12.00")


@pytest.mark.django_db
def test_admin_cannot_delete_only_default_commission_plan(api_client):
    admin = AdminUserFactory()

    plan = CommissionPlanFactory(
        name="Default",
        percentage=Decimal("10.00"),
        is_default=True,
    )

    api_client.force_authenticate(user=admin)

    url = reverse(
        "admin-commission-plans-detail",
        kwargs={"pk": plan.id},
    )

    response = api_client.delete(url)

    assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
def test_admin_can_list_vendor_documents(api_client):
    admin = AdminUserFactory()
    document = VendorDocumentFactory()

    api_client.force_authenticate(user=admin)

    url = reverse("admin-vendor-documents-list")

    response = api_client.get(url)

    assert response.status_code == status.HTTP_200_OK
    assert response.data["count"] == 1

    results = get_results(response)

    assert len(results) == 1
    assert results[0]["id"] == str(document.id)
    assert results[0]["vendor_id"] == str(document.vendor.id)


@pytest.mark.django_db
def test_admin_can_verify_vendor_document(api_client):
    admin = AdminUserFactory()
    document = VendorDocumentFactory(verified=False)

    api_client.force_authenticate(user=admin)

    url = reverse(
        "admin-vendor-documents-verify",
        kwargs={"pk": document.id},
    )

    response = api_client.post(url)

    assert response.status_code == status.HTTP_200_OK
    assert response.data["verified"] is True

    document.refresh_from_db()

    assert document.verified is True


@pytest.mark.django_db
def test_admin_can_unverify_vendor_document(api_client):
    admin = AdminUserFactory()
    document = VendorDocumentFactory(verified=True)

    api_client.force_authenticate(user=admin)

    url = reverse(
        "admin-vendor-documents-unverify",
        kwargs={"pk": document.id},
    )

    response = api_client.post(url)

    assert response.status_code == status.HTTP_200_OK
    assert response.data["verified"] is False

    document.refresh_from_db()

    assert document.verified is False


@pytest.mark.django_db
def test_non_admin_cannot_verify_vendor_document(api_client):
    vendor_user = VendorUserFactory()
    document = VendorDocumentFactory(verified=False)

    api_client.force_authenticate(user=vendor_user)

    url = reverse(
        "admin-vendor-documents-verify",
        kwargs={"pk": document.id},
    )

    response = api_client.post(url)

    assert response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
def test_vendors_schema_contains_vendor_endpoints(api_client):
    url = reverse("schema")

    response = api_client.get(url)

    assert response.status_code == status.HTTP_200_OK

    content = response.content.decode()

    assert "/api/v1/vendors/onboarding/" in content
    assert "/api/v1/vendors/me/" in content
    assert "/api/v1/vendors/documents/" in content
    assert "/api/v1/vendors/admin/vendors/" in content
    assert "/api/v1/vendors/admin/documents/" in content
    assert "/api/v1/vendors/admin/documents/{id}/verify/" in content
    assert "/api/v1/vendors/admin/documents/{id}/unverify/" in content
    assert "/api/v1/vendors/admin/commission-plans/" in content