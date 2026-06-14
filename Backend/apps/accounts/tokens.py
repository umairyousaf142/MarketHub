from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import PasswordResetTokenGenerator, default_token_generator
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode

User = get_user_model()


class EmailVerificationTokenGenerator(PasswordResetTokenGenerator):
    """
    Email verification token.

    Token invalid ho jata hai jab:
    - user.is_verified change ho
    - user.password change ho
    - token timeout expire ho
    """

    def _make_hash_value(self, user, timestamp):
        return f"{user.pk}{timestamp}{user.email}{user.is_verified}{user.password}"


email_verification_token_generator = EmailVerificationTokenGenerator()


def encode_user_id(user) -> str:
    return urlsafe_base64_encode(force_bytes(user.pk))


def decode_user_id(uid: str):
    try:
        user_id = force_str(urlsafe_base64_decode(uid))
        return User.objects.get(pk=user_id)
    except (TypeError, ValueError, OverflowError, User.DoesNotExist):
        return None


def build_email_verification_link(user) -> str:
    uid = encode_user_id(user)
    token = email_verification_token_generator.make_token(user)

    return (
        f"{settings.FRONTEND_URL}"
        f"{settings.VERIFY_EMAIL_PATH}"
        f"?uid={uid}&token={token}"
    )


def build_password_reset_link(user) -> str:
    uid = encode_user_id(user)
    token = default_token_generator.make_token(user)

    return (
        f"{settings.FRONTEND_URL}"
        f"{settings.RESET_PASSWORD_PATH}"
        f"?uid={uid}&token={token}"
    )