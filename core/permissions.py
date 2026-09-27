"""
Role rules.

UserProfile.role is one of: owner, manager, staff.

    owner    - everything, including billing and deleting records
    manager  - day-to-day entry and edits, no deleting, no billing
    staff    - entry only (add), no edits, no deletes, no reports export

Usage:

    from core.permissions import role_required

    @login_required
    @role_required("owner", "manager")
    def edit_mill(request, mill_id):
        ...
"""

from functools import wraps

from django.contrib import messages
from django.shortcuts import redirect

OWNER = "owner"
MANAGER = "manager"
STAFF = "staff"


def role_of(request):
    profile = getattr(request, "user_profile", None)
    if profile is None and request.user.is_authenticated:
        profile = getattr(request.user, "userprofile", None)
    return profile.role if profile else None


def role_required(*allowed_roles):
    """Allow the view only for the listed roles. Superusers always pass."""

    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            if request.user.is_superuser:
                return view(request, *args, **kwargs)

            if role_of(request) in allowed_roles:
                return view(request, *args, **kwargs)

            messages.error(
                request,
                "You do not have permission for this action. Ask the account owner.",
            )
            return redirect("dashboard")

        return wrapper

    return decorator


owner_required = role_required(OWNER)
manager_required = role_required(OWNER, MANAGER)
