import uuid
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import Q
from django.db.models.functions import Lower
from django.utils import timezone


class CommissionPlan(models.Model):
    """
    Commission plan applied to vendors.

    Rules:
    - Only one default commission plan can exist.
    - At least one default commission plan should always exist.
    - Percentage must be between 0 and 100.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    name = models.CharField(max_length=100)
    percentage = models.DecimalField(max_digits=5, decimal_places=2)
    is_default = models.BooleanField(default=False, db_index=True)

    class Meta:
        ordering = ["-is_default", "name"]
        constraints = [
            models.UniqueConstraint(
                Lower("name"),
                name="vendors_commission_plan_name_case_insensitive_unique",
            ),
            models.UniqueConstraint(
                fields=["is_default"],
                condition=Q(is_default=True),
                name="vendors_one_default_commission_plan",
            ),
            models.CheckConstraint(
                condition=Q(percentage__gte=Decimal("0.00"))
                & Q(percentage__lte=Decimal("100.00")),
                name="vendors_commission_percentage_between_0_and_100",
            ),
        ]

    def clean(self):
        if self.name:
            self.name = self.name.strip()

        if self.percentage is not None:
            if self.percentage < Decimal("0.00") or self.percentage > Decimal("100.00"):
                raise ValidationError(
                    {"percentage": "Commission percentage must be between 0 and 100."}
                )

    def save(self, *args, **kwargs):
        self.clean()

        with transaction.atomic():
            if self.is_default:
                CommissionPlan.objects.exclude(pk=self.pk).update(is_default=False)
            else:
                has_another_default = CommissionPlan.objects.exclude(pk=self.pk).filter(
                    is_default=True
                ).exists()

                if not has_another_default:
                    raise ValidationError(
                        "At least one default commission plan is required."
                    )

            super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.is_default:
            has_another_default = CommissionPlan.objects.exclude(pk=self.pk).filter(
                is_default=True
            ).exists()

            if not has_another_default:
                raise ValidationError("Cannot delete the only default commission plan.")

        return super().delete(*args, **kwargs)

    def __str__(self):
        return f"{self.name} ({self.percentage}%)"


class Vendor(models.Model):
    """
    Vendor profile.

    Rules:
    - Vendor profile can only be attached to a user with role=VENDOR.
    - Approval workflow must use approve(), reject(), suspend().
    - Views should not update status directly.
    """

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        APPROVED = "APPROVED", "Approved"
        SUSPENDED = "SUSPENDED", "Suspended"
        REJECTED = "REJECTED", "Rejected"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="vendor_profile",
    )

    store_name = models.CharField(max_length=150, db_index=True)

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )

    commission_plan = models.ForeignKey(
        CommissionPlan,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="vendors",
    )

    approved_at = models.DateTimeField(null=True, blank=True)

    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approved_vendors",
    )

    class Meta:
        ordering = ["store_name"]
        constraints = [
            models.UniqueConstraint(
                Lower("store_name"),
                name="vendors_store_name_case_insensitive_unique",
            )
        ]

    def clean(self):
        if self.store_name:
            self.store_name = self.store_name.strip()

        if not self.store_name:
            raise ValidationError({"store_name": "Store name is required."})

        if self.user_id and getattr(self.user, "role", None) != "VENDOR":
            raise ValidationError(
                {"user": "Vendor profile can only be attached to a VENDOR user."}
            )

        if self.approved_by_id and getattr(self.approved_by, "role", None) != "ADMIN":
            raise ValidationError(
                {"approved_by": "Vendor can only be approved by an ADMIN user."}
            )

        if self.status == self.Status.APPROVED:
            if not self.approved_at:
                raise ValidationError(
                    {"approved_at": "Approved vendors must have approved_at set."}
                )

            if not self.approved_by_id:
                raise ValidationError(
                    {"approved_by": "Approved vendors must have approved_by set."}
                )

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    def approve(self, admin_user):
        if getattr(admin_user, "role", None) != "ADMIN":
            raise ValidationError("Only ADMIN users can approve vendors.")

        if self.status != self.Status.PENDING:
            raise ValidationError("Only PENDING vendors can be approved.")

        self.status = self.Status.APPROVED
        self.approved_at = timezone.now()
        self.approved_by = admin_user

        self.save(update_fields=["status", "approved_at", "approved_by"])

    def reject(self, admin_user):
        if getattr(admin_user, "role", None) != "ADMIN":
            raise ValidationError("Only ADMIN users can reject vendors.")

        if self.status != self.Status.PENDING:
            raise ValidationError("Only PENDING vendors can be rejected.")

        self.status = self.Status.REJECTED
        self.approved_at = None
        self.approved_by = None

        self.save(update_fields=["status", "approved_at", "approved_by"])

    def suspend(self, admin_user):
        if getattr(admin_user, "role", None) != "ADMIN":
            raise ValidationError("Only ADMIN users can suspend vendors.")

        if self.status != self.Status.APPROVED:
            raise ValidationError("Only APPROVED vendors can be suspended.")

        self.status = self.Status.SUSPENDED

        self.save(update_fields=["status"])

    def get_commission_plan(self):
        if self.commission_plan:
            return self.commission_plan

        return CommissionPlan.objects.filter(is_default=True).first()

    def __str__(self):
        return self.store_name


class VendorDocument(models.Model):
    """
    Vendor KYC document.

    FileField is storage-backend ready.
    In production, the storage backend can be switched to S3 or any compatible storage.
    """

    class DocumentType(models.TextChoices):
        NIC = "NIC", "NIC"
        TAX = "TAX", "Tax"
        BANK_STATEMENT = "BANK_STATEMENT", "Bank Statement"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    vendor = models.ForeignKey(
        Vendor,
        on_delete=models.CASCADE,
        related_name="documents",
    )

    doc_type = models.CharField(
        max_length=30,
        choices=DocumentType.choices,
        db_index=True,
    )

    file = models.FileField(upload_to="vendor_documents/%Y/%m/")

    verified = models.BooleanField(default=False, db_index=True)

    class Meta:
        ordering = ["vendor", "doc_type"]

    def __str__(self):
        return f"{self.vendor.store_name} - {self.doc_type}"