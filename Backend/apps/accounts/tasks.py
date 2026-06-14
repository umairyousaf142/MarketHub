import logging

from celery import shared_task
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import send_mail

from .tokens import build_email_verification_link, build_password_reset_link

logger = logging.getLogger(__name__)
User = get_user_model()


@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
    retry_kwargs={"max_retries": 3},
)
def send_email_verification_task(self, user_id: str):
    user = User.objects.filter(id=user_id, is_active=True).first()

    if not user:
        return "skipped:user_not_found"

    if user.is_verified:
        return "skipped:already_verified"

    verification_link = build_email_verification_link(user)

    send_mail(
        subject="Verify your MarketHub email",
        message=(
            f"Hello,\n\n"
            f"Please verify your MarketHub email using this link:\n\n"
            f"{verification_link}\n\n"
            f"If you did not create this account, you can ignore this email."
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[user.email],
        fail_silently=False,
    )

    logger.info("Email verification sent to user_id=%s", user_id)
    return "sent"


@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
    retry_kwargs={"max_retries": 3},
)
def send_password_reset_email_task(self, user_id: str):
    user = User.objects.filter(id=user_id, is_active=True).first()

    if not user:
        return "skipped:user_not_found"

    reset_link = build_password_reset_link(user)

    send_mail(
        subject="Reset your MarketHub password",
        message=(
            f"Hello,\n\n"
            f"Use this link to reset your MarketHub password:\n\n"
            f"{reset_link}\n\n"
            f"If you did not request this, you can ignore this email."
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[user.email],
        fail_silently=False,
    )

    logger.info("Password reset email sent to user_id=%s", user_id)
    return "sent"


@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
    retry_kwargs={"max_retries": 3},
)
def send_welcome_email_task(self, user_id: str):
    user = User.objects.filter(id=user_id, is_active=True).first()

    if not user:
        return "skipped:user_not_found"

    send_mail(
        subject="Welcome to MarketHub",
        message=(
            f"Hello,\n\n"
            f"Welcome to MarketHub. Your email has been verified successfully."
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[user.email],
        fail_silently=False,
    )

    logger.info("Welcome email sent to user_id=%s", user_id)
    return "sent"


@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
    retry_kwargs={"max_retries": 3},
)
def send_password_changed_email_task(self, user_id: str):
    user = User.objects.filter(id=user_id, is_active=True).first()

    if not user:
        return "skipped:user_not_found"

    send_mail(
        subject="Your MarketHub password was changed",
        message=(
            f"Hello,\n\n"
            f"Your MarketHub password was changed successfully.\n\n"
            f"If this was not you, please contact support immediately."
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[user.email],
        fail_silently=False,
    )

    logger.info("Password changed email sent to user_id=%s", user_id)
    return "sent"