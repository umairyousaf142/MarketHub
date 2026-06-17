from decimal import Decimal

import factory

from apps.accounts.tests.factories import AdminUserFactory, VendorUserFactory
from apps.vendors.models import CommissionPlan, Vendor, VendorDocument


class CommissionPlanFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = CommissionPlan

    name = factory.Sequence(lambda n: f"Commission Plan {n}")
    percentage = Decimal("10.00")
    is_default = True


class VendorFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Vendor

    user = factory.SubFactory(VendorUserFactory)
    store_name = factory.Sequence(lambda n: f"Vendor Store {n}")
    status = Vendor.Status.PENDING
    commission_plan = None


class VendorDocumentFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = VendorDocument

    vendor = factory.SubFactory(VendorFactory)
    doc_type = VendorDocument.DocumentType.NIC
    file = "vendor_documents/test-document.pdf"
    verified = False