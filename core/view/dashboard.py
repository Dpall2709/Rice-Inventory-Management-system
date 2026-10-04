from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from core.services.dashboard import build_dashboard
from core.tenancy import company_of


@login_required
def dashboard(request):
    """The owner's home screen: period numbers, balances and today's to-do list."""
    # A user without a company gets the empty onboarding screen: every query
    # below is scoped with for_company(), which returns nothing for None.
    data = build_dashboard(company_of(request), request.GET.get("period"))
    return render(request, "core/dashboard.html", data)
