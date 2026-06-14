from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from django.contrib.auth.tokens import default_token_generator
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken

from .tokens import decode_user_id, email_verification_token_generator

from .models import Address

User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "role",
            "is_active",
            "is_verified",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "email",
            "role",
            "is_active",
            "is_verified",
            "created_at",
            "updated_at",
        ]

class TokenPairSerializer(serializers.Serializer):
    refresh = serializers.CharField()
    access = serializers.CharField()


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=8)
    password_confirm = serializers.CharField(write_only=True, min_length=8)

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "role",
            "password",
            "password_confirm",
        ]
        read_only_fields = ["id"]
        extra_kwargs = {
            "role": {"required": False},
        }

    def validate_email(self, value):
        email = value.strip().lower()

        if User.objects.filter(email__iexact=email).exists():
            raise serializers.ValidationError("A user with this email already exists.")

        return email

    def validate_role(self, value):
        if value == User.Role.ADMIN:
            raise serializers.ValidationError(
                "Admin users cannot be created from public registration."
            )

        return value

    def validate(self, attrs):
        password = attrs.get("password")
        password_confirm = attrs.pop("password_confirm", None)

        if password != password_confirm:
            raise serializers.ValidationError(
                {"password_confirm": "Passwords do not match."}
            )

        validate_password(password)
        return attrs

    def create(self, validated_data):
        password = validated_data.pop("password")
        return User.objects.create_user(password=password, **validated_data)



class RegisterResponseSerializer(serializers.Serializer):
    detail = serializers.CharField()
    user = UserSerializer()
    tokens = TokenPairSerializer()


class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)

        token["email"] = user.email
        token["role"] = user.role
        token["is_verified"] = user.is_verified

        return token

    def validate(self, attrs):
        data = super().validate(attrs)
        data["user"] = UserSerializer(self.user).data
        return data


class LoginResponseSerializer(serializers.Serializer):
    refresh = serializers.CharField()
    access = serializers.CharField()
    user = UserSerializer()


class AddressSerializer(serializers.ModelSerializer):
    class Meta:
        model = Address
        fields = [
            "id",
            "label",
            "street",
            "city",
            "country",
            "is_default",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "created_at",
            "updated_at",
        ]

    def validate(self, attrs):
        for field in ["label", "street", "city", "country"]:
            if field in attrs and isinstance(attrs[field], str):
                attrs[field] = attrs[field].strip()

        return attrs
    


# After Import 

class DetailResponseSerializer(serializers.Serializer):
    detail = serializers.CharField()


class LogoutSerializer(serializers.Serializer):
    refresh = serializers.CharField(write_only=True)

    def validate(self, attrs):
        try:
            attrs["token"] = RefreshToken(attrs["refresh"])
        except TokenError:
            raise serializers.ValidationError(
                {"refresh": "Invalid or expired refresh token."}
            )

        return attrs

    def save(self, **kwargs):
        self.validated_data["token"].blacklist()


class ChangePasswordSerializer(serializers.Serializer):
    old_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True, min_length=8)
    new_password_confirm = serializers.CharField(write_only=True, min_length=8)

    def validate_old_password(self, value):
        user = self.context["request"].user

        if not user.check_password(value):
            raise serializers.ValidationError("Old password is incorrect.")

        return value

    def validate(self, attrs):
        new_password = attrs.get("new_password")
        confirm_password = attrs.pop("new_password_confirm", None)

        if new_password != confirm_password:
            raise serializers.ValidationError(
                {"new_password_confirm": "Passwords do not match."}
            )

        validate_password(new_password, self.context["request"].user)
        return attrs

    def save(self, **kwargs):
        user = self.context["request"].user
        user.set_password(self.validated_data["new_password"])
        user.save(update_fields=["password", "updated_at"])
        return user


class ForgotPasswordSerializer(serializers.Serializer):
    email = serializers.EmailField()

    def validate_email(self, value):
        return value.strip().lower()


class ResetPasswordSerializer(serializers.Serializer):
    uid = serializers.CharField(write_only=True)
    token = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True, min_length=8)
    new_password_confirm = serializers.CharField(write_only=True, min_length=8)

    def validate(self, attrs):
        user = decode_user_id(attrs.get("uid"))
        token = attrs.get("token")

        if not user or not default_token_generator.check_token(user, token):
            raise serializers.ValidationError(
                {"token": "Invalid or expired password reset token."}
            )

        new_password = attrs.get("new_password")
        confirm_password = attrs.pop("new_password_confirm", None)

        if new_password != confirm_password:
            raise serializers.ValidationError(
                {"new_password_confirm": "Passwords do not match."}
            )

        validate_password(new_password, user)

        attrs["user"] = user
        return attrs

    def save(self, **kwargs):
        user = self.validated_data["user"]
        user.set_password(self.validated_data["new_password"])
        user.save(update_fields=["password", "updated_at"])
        return user


class VerifyEmailSerializer(serializers.Serializer):
    uid = serializers.CharField(write_only=True)
    token = serializers.CharField(write_only=True)

    def validate(self, attrs):
        user = decode_user_id(attrs.get("uid"))
        token = attrs.get("token")

        if not user or not email_verification_token_generator.check_token(user, token):
            raise serializers.ValidationError(
                {"token": "Invalid or expired email verification token."}
            )

        attrs["user"] = user
        return attrs

    def save(self, **kwargs):
        user = self.validated_data["user"]
        user.is_verified = True
        user.save(update_fields=["is_verified", "updated_at"])
        return user