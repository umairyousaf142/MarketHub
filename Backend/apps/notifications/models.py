import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import Q


class NotificationQuerySet(models.QuerySet):
    def for_user(self, user):
        return self.filter(user=user)

    def in_app(self):
        return self.filter(channel=Notification.Channel.IN_APP)

    def unread(self):
        return self.filter(
            channel=Notification.Channel.IN_APP,
            is_read=False,
        )

    def read(self):
        return self.filter(
            channel=Notification.Channel.IN_APP,
            is_read=True,
        )

    def by_type(self, notification_type):
        return self.filter(type=notification_type)

    def by_channel(self, channel):
        return self.filter(channel=channel)


class Notification(models.Model):
    class Type(models.TextChoices):
        WELCOME = "WELCOME", "Welcome"
        ORDER_CREATED = "ORDER_CREATED", "Order Created"
        PAYMENT_SUCCESS = "PAYMENT_SUCCESS", "Payment Success"
        VENDOR_APPROVED = "VENDOR_APPROVED", "Vendor Approved"
        VENDOR_NEW_ORDER = "VENDOR_NEW_ORDER", "Vendor New Order"
        LOW_STOCK_ALERT = "LOW_STOCK_ALERT", "Low Stock Alert"
        REVIEW_REMINDER = "REVIEW_REMINDER", "Review Reminder"

    class Channel(models.TextChoices):
        EMAIL = "EMAIL", "Email"
        SMS = "SMS", "SMS"
        IN_APP = "IN_APP", "In App"

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="notifications",
        db_index=True,
    )

    type = models.CharField(
        max_length=50,
        choices=Type.choices,
        db_index=True,
    )

    channel = models.CharField(
        max_length=20,
        choices=Channel.choices,
        db_index=True,
    )

    title = models.CharField(
        max_length=255,
    )

    body = models.TextField()

    is_read = models.BooleanField(
        default=False,
        db_index=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
    )

    objects = NotificationQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "created_at"]),
            models.Index(fields=["user", "is_read"]),
            models.Index(fields=["user", "channel"]),
            models.Index(fields=["type", "created_at"]),
            models.Index(fields=["channel", "created_at"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(channel__in=["EMAIL", "SMS", "IN_APP"]),
                name="notifications_valid_channel",
            ),
            models.CheckConstraint(
                condition=Q(
                    type__in=[
                        "WELCOME",
                        "ORDER_CREATED",
                        "PAYMENT_SUCCESS",
                        "VENDOR_APPROVED",
                        "VENDOR_NEW_ORDER",
                        "LOW_STOCK_ALERT",
                        "REVIEW_REMINDER",
                    ]
                ),
                name="notifications_valid_type",
            ),
        ]

    def __str__(self):
        return f"{self.user_id} - {self.type} - {self.channel}"

    def clean(self):
        if not self.title or not str(self.title).strip():
            raise ValidationError(
                {"title": "Notification title is required."}
            )

        if not self.body or not str(self.body).strip():
            raise ValidationError(
                {"body": "Notification body is required."}
            )

        if self.channel != self.Channel.IN_APP and self.is_read is False:
            raise ValidationError(
                {"is_read": "is_read is only meaningful for IN_APP notifications."}
            )

    def save(self, *args, **kwargs):
        if self.channel != self.Channel.IN_APP:
            self.is_read = True

        self.full_clean()

        return super().save(*args, **kwargs)

    @classmethod
    def create_for_user(
        cls,
        *,
        user,
        type,
        channel,
        title,
        body,
        is_read=False,
    ):
        with transaction.atomic():
            notification = cls(
                user=user,
                type=type,
                channel=channel,
                title=title,
                body=body,
                is_read=is_read,
            )
            notification.save()

            return notification

    def mark_as_read(self):
        if self.channel != self.Channel.IN_APP:
            return self

        self.is_read = True
        self.save(update_fields=["is_read"])

        return self

    def mark_as_unread(self):
        if self.channel != self.Channel.IN_APP:
            raise ValidationError(
                {"channel": "Only IN_APP notifications can be marked unread."}
            )

        self.is_read = False
        self.save(update_fields=["is_read"])

        return self