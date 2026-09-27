"""
Tenant (company) scoping helpers.

Every business table in this project carries a `company` foreign key. Data of one
company must never be visible to another. Instead of remembering to write
`company=company` in every query by hand, use the helpers in this file:

    from core.tenancy import company_of, tenant_object_or_404

    company = company_of(request)
    mills   = Mill.objects.for_company(company)
    mill    = tenant_object_or_404(Mill, request, mill_id)

`for_company()` also understands models that reach Company through a parent
(PurchaseItem -> purchase -> company, SaleItem -> sale -> company) via the
`company_path` attribute on the manager.
"""

from django.db import models
from django.shortcuts import get_object_or_404


class TenantQuerySet(models.QuerySet):
    """QuerySet that can narrow itself to a single company."""

    def for_company(self, company):
        if company is None:
            return self.none()
        path = getattr(self.model, "company_path", "company")
        return self.filter(**{path: company})


class TenantManager(models.Manager.from_queryset(TenantQuerySet)):
    """Default manager for every company-owned model."""

    use_in_migrations = False


def company_of(request):
    """
    The company of the logged-in user.

    CompanyMiddleware already put it on the request, so this costs no extra
    database query. Returns None for anonymous users or users without a profile.
    """
    company = getattr(request, "company", None)
    if company is not None:
        return company

    # Fallback for code paths that run without the middleware (management
    # commands, tests, DRF views mounted outside the middleware stack).
    profile = getattr(request.user, "userprofile", None) if request.user.is_authenticated else None
    return profile.company if profile else None


def tenant_object_or_404(model, request, pk, **extra):
    """
    Fetch one row by id, but only if it belongs to the caller's company.

    This is what stops company A from opening company B's record by changing the
    id in the URL. Raises 404 - never "permission denied" - so a probing user
    cannot even learn whether the id exists.
    """
    company = company_of(request)
    if company is None:
        from django.http import Http404

        raise Http404("No company for this user.")

    path = getattr(model, "company_path", "company")
    return get_object_or_404(model, pk=pk, **{path: company}, **extra)
