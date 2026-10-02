"""
`business_profile` in every template: how complete the company's invoice
details are. Used by base.html for the menu badge and the "incomplete" banner.

No database query: request.company is already loaded by CompanyMiddleware.
"""

from .services import profile_status


def business_profile(request):
    company = getattr(request, "company", None)
    if company is None:
        return {}
    return {"business_profile": profile_status(company)}
