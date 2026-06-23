from rest_framework.permissions import BasePermission


def is_admin_user(user):
    return bool(
        user
        and user.is_authenticated
        and (
            getattr(user, "is_staff", False)
            or getattr(user, "is_superuser", False)
            or getattr(user, "role", None) == "ADMIN"
        )
    )


def is_customer_user(user):
    return bool(
        user
        and user.is_authenticated
        and getattr(user, "role", None) == "CUSTOMER"
    )


class IsAdminRole(BasePermission):
    def has_permission(self, request, view):
        return is_admin_user(request.user)


class IsCustomerRole(BasePermission):
    def has_permission(self, request, view):
        return is_customer_user(request.user)