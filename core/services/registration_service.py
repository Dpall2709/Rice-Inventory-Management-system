from django.contrib.auth.models import User

from core.models import Company, UserProfile


def register_company(form):
    """
    Create Company + User + UserProfile
    """

    company = Company.objects.create(
        company_name=form.cleaned_data["company_name"],
        owner_name=form.cleaned_data["owner_name"],
        email=form.cleaned_data["email"],
        mobile=form.cleaned_data["mobile"],

        subscription_start="2026-01-01",
        subscription_end="2036-01-01",
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

    return company