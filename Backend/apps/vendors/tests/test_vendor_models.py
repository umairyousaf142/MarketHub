from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.accounts.tests.factories import AdminUserFactory, CustomerUserFactory, VendorUserFactory
from apps.vendors.models import CommissionPlan, Vendor, VendorDocument
from .factories import CommissionPlanFactory, VendorDocumentFactory, VendorFactory


@pytest.mark.django_db
def test_create_default_commission_plan():
    plan = CommissionPlanFactory(
        name="Default",
        percentage=Decimal("10.00"),
        is_default=True,
    )

    assert plan.name == "Default"
    assert plan.percentage == Decimal("10.00")
    assert plan.is_default is True
    assert str(plan) == "Default (10.00%)"


@pytest.mark.django_db
def test_commission_percentage_cannot_be_negative():
    plan = CommissionPlan(
        name="Invalid Negative",
        percentage=Decimal("-1.00"),
        is_default=True,
    )

    with pytest.raises(ValidationError):
        plan.save()


@pytest.mark.django_db
def test_commission_percentage_cannot_exceed_100():
    plan = CommissionPlan(
        name="Invalid High",
        percentage=Decimal("101.00"),
        is_default=True,
    )

    with pytest.raises(ValidationError):
        plan.save()


@pytest.mark.django_db
def test_only_one_default_commission_plan_allowed():
    first_plan = CommissionPlanFactory(
        name="Default One",
        percentage=Decimal("10.00"),
        is_default=True,
    )

    second_plan = CommissionPlanFactory(
        name="Default Two",
        percentage=Decimal("15.00"),
        is_default=True,
    )

    first_plan.refresh_from_db()
    second_plan.refresh_from_db()

    assert first_plan.is_default is False
    assert second_plan.is_default is True
    assert CommissionPlan.objects.filter(is_default=True).count() == 1


@pytest.mark.django_db
def test_non_default_commission_plan_requires_existing_default_plan():
    with pytest.raises(ValidationError):
        CommissionPlanFactory(
            name="Premium",
            percentage=Decimal("8.00"),
            is_default=False,
        )


@pytest.mark.django_db
def test_non_default_commission_plan_can_exist_when_default_exists():
    default_plan = CommissionPlanFactory(
        name="Default",
        percentage=Decimal("10.00"),
        is_default=True,
    )

    premium_plan = CommissionPlanFactory(
        name="Premium",
        percentage=Decimal("8.00"),
        is_default=False,
    )

    assert default_plan.is_default is True
    assert premium_plan.is_default is False
    assert CommissionPlan.objects.count() == 2


@pytest.mark.django_db
def test_cannot_delete_only_default_commission_plan():
    plan = CommissionPlanFactory(
        name="Default",
        percentage=Decimal("10.00"),
        is_default=True,
    )

    with pytest.raises(ValidationError):
        plan.delete()


@pytest.mark.django_db
def test_switching_default_commission_plan_updates_old_default():
    old_default = CommissionPlanFactory(
        name="Old Default",
        percentage=Decimal("10.00"),
        is_default=True,
    )

    new_plan = CommissionPlanFactory(
        name="New Plan",
        percentage=Decimal("5.00"),
        is_default=False,
    )

    new_plan.is_default = True
    new_plan.save()

    old_default.refresh_from_db()
    new_plan.refresh_from_db()

    assert old_default.is_default is False
    assert new_plan.is_default is True
    assert CommissionPlan.objects.filter(is_default=True).count() == 1


@pytest.mark.django_db
def test_create_vendor_profile_for_vendor_user():
    user = VendorUserFactory()
    vendor = VendorFactory(user=user, store_name="Test Store")

    assert vendor.user == user
    assert vendor.store_name == "Test Store"
    assert vendor.status == Vendor.Status.PENDING


@pytest.mark.django_db
def test_vendor_profile_cannot_be_created_for_customer_user():
    customer = CustomerUserFactory()

    with pytest.raises(ValidationError):
        VendorFactory(user=customer, store_name="Invalid Customer Store")


@pytest.mark.django_db
def test_vendor_store_name_is_case_insensitive_unique():
    VendorFactory(store_name="Alpha Store")

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            VendorFactory(store_name="alpha store")


@pytest.mark.django_db
def test_pending_vendor_can_be_approved_by_admin():
    admin = AdminUserFactory()
    vendor = VendorFactory(status=Vendor.Status.PENDING)

    vendor.approve(admin)

    vendor.refresh_from_db()

    assert vendor.status == Vendor.Status.APPROVED
    assert vendor.approved_by == admin
    assert vendor.approved_at is not None


@pytest.mark.django_db
def test_vendor_cannot_be_approved_by_non_admin_user():
    vendor_user = VendorUserFactory()
    vendor = VendorFactory(status=Vendor.Status.PENDING)

    with pytest.raises(ValidationError):
        vendor.approve(vendor_user)

    vendor.refresh_from_db()

    assert vendor.status == Vendor.Status.PENDING
    assert vendor.approved_by is None
    assert vendor.approved_at is None


@pytest.mark.django_db
def test_only_pending_vendor_can_be_approved():
    admin = AdminUserFactory()
    vendor = VendorFactory(status=Vendor.Status.PENDING)

    vendor.approve(admin)

    with pytest.raises(ValidationError):
        vendor.approve(admin)


@pytest.mark.django_db
def test_pending_vendor_can_be_rejected_by_admin():
    admin = AdminUserFactory()
    vendor = VendorFactory(status=Vendor.Status.PENDING)

    vendor.reject(admin)

    vendor.refresh_from_db()

    assert vendor.status == Vendor.Status.REJECTED
    assert vendor.approved_by is None
    assert vendor.approved_at is None


@pytest.mark.django_db
def test_vendor_cannot_be_rejected_by_non_admin_user():
    vendor_user = VendorUserFactory()
    vendor = VendorFactory(status=Vendor.Status.PENDING)

    with pytest.raises(ValidationError):
        vendor.reject(vendor_user)

    vendor.refresh_from_db()

    assert vendor.status == Vendor.Status.PENDING


@pytest.mark.django_db
def test_approved_vendor_can_be_suspended_by_admin():
    admin = AdminUserFactory()
    vendor = VendorFactory(status=Vendor.Status.PENDING)

    vendor.approve(admin)
    vendor.suspend(admin)

    vendor.refresh_from_db()

    assert vendor.status == Vendor.Status.SUSPENDED
    assert vendor.approved_by == admin
    assert vendor.approved_at is not None


@pytest.mark.django_db
def test_pending_vendor_cannot_be_suspended():
    admin = AdminUserFactory()
    vendor = VendorFactory(status=Vendor.Status.PENDING)

    with pytest.raises(ValidationError):
        vendor.suspend(admin)

    vendor.refresh_from_db()

    assert vendor.status == Vendor.Status.PENDING


@pytest.mark.django_db
def test_direct_approved_vendor_save_requires_approved_fields():
    vendor_user = VendorUserFactory()

    vendor = Vendor(
        user=vendor_user,
        store_name="Direct Approved Store",
        status=Vendor.Status.APPROVED,
    )

    with pytest.raises(ValidationError):
        vendor.save()


@pytest.mark.django_db
def test_direct_approved_vendor_save_requires_admin_approver():
    customer = CustomerUserFactory()
    vendor_user = VendorUserFactory()

    vendor = Vendor(
        user=vendor_user,
        store_name="Bad Approver Store",
        status=Vendor.Status.APPROVED,
        approved_at=timezone.now(),
        approved_by=customer,
    )

    with pytest.raises(ValidationError):
        vendor.save()


@pytest.mark.django_db
def test_vendor_get_commission_plan_returns_assigned_plan():
    CommissionPlanFactory(
        name="Default",
        percentage=Decimal("10.00"),
        is_default=True,
    )

    custom_plan = CommissionPlanFactory(
        name="Custom",
        percentage=Decimal("7.50"),
        is_default=False,
    )

    vendor = VendorFactory(commission_plan=custom_plan)

    assert vendor.get_commission_plan() == custom_plan


@pytest.mark.django_db
def test_vendor_get_commission_plan_falls_back_to_default_plan():
    default_plan = CommissionPlanFactory(
        name="Default",
        percentage=Decimal("10.00"),
        is_default=True,
    )

    vendor = VendorFactory(commission_plan=None)

    assert vendor.get_commission_plan() == default_plan


@pytest.mark.django_db
def test_create_vendor_document():
    vendor = VendorFactory()

    document = VendorDocumentFactory(
        vendor=vendor,
        doc_type=VendorDocument.DocumentType.NIC,
        verified=False,
    )

    assert document.vendor == vendor
    assert document.doc_type == VendorDocument.DocumentType.NIC
    assert document.verified is False
    assert str(document) == f"{vendor.store_name} - {VendorDocument.DocumentType.NIC}"