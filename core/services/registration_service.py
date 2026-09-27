"""
Company signup.

Creates the three rows a new tenant needs - Company, User, UserProfile - and
starts a free trial. Everything happens in one transaction, so a half-created
account is impossible.
"""

from django.contrib.auth.models import User
from django.db import transaction

from core.models import Company, UserProfile


@transaction.atomic
def register_company(form):
    """Create Company + User + UserProfile + a free trial subscription."""

    company = Company.objects.create(
        company_name=form.cleaned_data["company_name"],
        owner_name=form.cleaned_data["owner_name"],
        email=form.cleaned_data["email"],
        mobile=form.cleaned_data["mobile"],

        # The trial dates below are replaced immediately by start_trial(); they
        # are only here because the columns do not allow null.
        subscription_start="2000-01-01",
        subscription_end="2000-01-01",
    )

    user = User.objects.create_user(
        username=form.cleaned_data["username"],
        email=form.cleaned_data["email"],
        password=form.cleaned_data["password1"],
        first_name=form.cleaned_data["owner_name"],
    )

    UserProfile.objects.create(
        user=user,
        company=company,
        role="owner",
        phone=form.cleaned_data["mobile"],
    )

    # Imported here to avoid a circular import at startup (billing imports core).
    from billing.services import start_trial

    start_trial(company)

    return company
