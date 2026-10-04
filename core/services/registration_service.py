"""
Company signup.

Creates the three rows a new tenant needs - Company, User, UserProfile - and
starts a free trial. Everything happens in one transaction, so a half-created
account is impossible.

Called by the email-verified sign-up in the `accounts` app (with a dict and an
already-hashed password) and still accepts a bound, valid form as before.
"""

from django.contrib.auth.models import User
from django.db import transaction

from core.models import Company, UserProfile


@transaction.atomic
def register_company(data, password_hash=None):
    """
    Create Company + User + UserProfile + a free trial subscription.

    `data` is a dict (or a valid form, whose cleaned_data is used) with
    company_name, owner_name, email, mobile, username and - unless
    `password_hash` is given - password1.
    """
    if hasattr(data, "cleaned_data"):
        data = data.cleaned_data

    company = Company.objects.create(
        company_name=data["company_name"],
        owner_name=data["owner_name"],
        email=data["email"],
        mobile=data["mobile"],

        # The trial dates below are replaced immediately by start_trial(); they
        # are only here because the columns do not allow null.
        subscription_start="2000-01-01",
        subscription_end="2000-01-01",
    )

    user = User.objects.create_user(
        username=data["username"],
        email=data["email"],
        password=None if password_hash else data["password1"],
        first_name=data["owner_name"][:150],
    )
    if password_hash:
        user.password = password_hash
        user.save(update_fields=["password"])

    UserProfile.objects.create(
        user=user,
        company=company,
        role="owner",
        phone=data["mobile"],
    )

    # Imported here to avoid a circular import at startup (billing imports core).
    from billing.services import start_trial

    start_trial(company)

    return company
