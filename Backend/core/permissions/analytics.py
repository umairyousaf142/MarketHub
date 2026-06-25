from rest_framework.permissions import BasePermission


class IsAdminRole(BasePermission):
    message = "Admin access is required."

    def has_permission(self, request, view):
        user = request.user

        if not user or not user.is_authenticated:
            return False

        return (
            getattr(user, "role", None) == "ADMIN"
            or getattr(user, "is_staff", False)
            or getattr(user, "is_superuser", False)
        )


class IsVendorRole(BasePermission):
    message = "Vendor access is required."

    def has_permission(self, request, view):
        user = request.user

        if not user or not user.is_authenticated:
            return False

        if getattr(user, "role", None) != "VENDOR":
            return False

        try:
            return user.vendor_profile is not None
        except Exception:
            return False