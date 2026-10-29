"""
Who may call the API, and on whose data.

Every request is for the company of the logged-in user (from their
UserProfile), exactly like the web app. Roles follow the web app too:
staff can read and create, managers and owners can also edit and delete.
An expired subscription makes the API read-only, as it does the website.
"""

from rest_framework import permissions

from core.models import UserProfile

WRITE_ROLES = ("owner", "manager")


def profile_of(user):
    if not user or not user.is_authenticated:
        return None
    return UserProfile.objects.select_related("company").filter(user=user, is_active=True).first()


class HasCompany(permissions.BasePermission):
    """Logged in, active, and attached to a company. Puts request.company in place."""

    message = "This user is not attached to a company."

    def has_permission(self, request, view):
        profile = profile_of(request.user)
        if profile is None or not profile.company.is_active:
            return False
        request.company = profile.company
        request.user_profile = profile
        return True


class SubscriptionAllowsWrites(permissions.BasePermission):
    message = "Your subscription has ended, so nothing can be saved. Renew to continue."

    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS:
            return True
        from billing.services import subscription_for

        subscription = subscription_for(request.company).mark_expired_if_due()
        return not subscription.is_expired


class RoleAllowsChange(permissions.BasePermission):
    """Editing and deleting need a manager or the owner; creating does not."""

    message = "You do not have permission for this action. Ask the account owner."

    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS or request.method == "POST":
            return True
        if request.user.is_superuser:
            return True
        return getattr(request.user_profile, "role", None) in WRITE_ROLES


DEFAULT = [permissions.IsAuthenticated, HasCompany, SubscriptionAllowsWrites, RoleAllowsChange]
