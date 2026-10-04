"""
Subscription enforcement.

Rule: an expired company is NOT locked out. It becomes read-only - every page
still opens, but saving anything redirects to the billing page. People renew
when they can still see their own ledger; they walk away when they are locked
out of it.
"""

from django.contrib import messages
from django.shortcuts import redirect
from django.urls import reverse

from .services import subscription_for


class SubscriptionMiddleware:
    """Puts request.subscription and request.read_only on every request."""

    # Paths that must keep working even when the subscription has expired.
    ALWAYS_ALLOWED_PREFIXES = (
        "/billing/",
        "/login/",
        "/logout/",
        "/register/",
        "/i18n/",
        "/account/",
        "/admin/",
        "/static/",
        "/media/",
    )

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.subscription = None
        request.read_only = False

        company = getattr(request, "company", None)

        if company is not None:
            subscription = subscription_for(company).mark_expired_if_due()
            request.subscription = subscription
            request.read_only = subscription.is_expired

            if request.read_only and self._is_write(request):
                messages.error(
                    request,
                    "Your subscription has ended, so nothing can be saved. "
                    "Your data is safe - renew to continue.",
                )
                return redirect(reverse("billing:home"))

        return self.get_response(request)

    def _is_write(self, request):
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return False
        return not request.path.startswith(self.ALWAYS_ALLOWED_PREFIXES)
