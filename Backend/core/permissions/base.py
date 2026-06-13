from rest_framework.permissions import BasePermission


class IsAdmin(BasePermission):
    """Only Admin role users."""
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated
                    and request.user.role == 'ADMIN')


class IsVendor(BasePermission):
    """Only Vendor role users."""
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated
                    and request.user.role == 'VENDOR')


class IsCustomer(BasePermission):
    """Only Customer role users."""
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated
                    and request.user.role == 'CUSTOMER')


class IsAdminOrVendor(BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated
                    and request.user.role in ('ADMIN', 'VENDOR'))


class IsOwnerOrAdmin(BasePermission):
    """Object-level: user owns the object or is Admin."""
    def has_object_permission(self, request, view, obj):
        if request.user.role == 'ADMIN':
            return True
        return obj.user == request.user
