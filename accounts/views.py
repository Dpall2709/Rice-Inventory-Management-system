"""
Account screens.

    /account/signup/            step 1: details (nothing is created yet)
    /account/signup/verify/     step 2: 6-digit email code -> account created
    /account/signup/resend/     POST: send a new code
    /account/signup/edit/       back to step 1 to change the email
    /account/check/             JSON: is this username / email / mobile free?
    /account/login/             username, email or mobile + password
    /account/business/          the company's invoice identity

The old routes /register/ and /login/ (core/urls.py) render these same views.
"""

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _
from django.views.decorators.http import require_GET, require_POST

from core.models import Company, UserProfile
from core.permissions import role_of

from . import services
from .forms import BusinessProfileForm, LoginForm, OTPForm, SignupForm
from .validators import GST_STATE_CODES

SESSION_PENDING = "accounts_pending_signup"
SESSION_DEV_CODE = "accounts_dev_code"

EDIT_ROLES = ("owner", "manager")


# ==========================================================================
# Sign-up
# ==========================================================================

def _current_pending(request):
    pending = services.pending_from_token(request.session.get(SESSION_PENDING))
    if pending is None or not pending.is_usable:
        return None
    return pending


def signup(request):
    if request.user.is_authenticated:
        return redirect("dashboard")

    initial = {}
    if request.method == "GET" and request.GET.get("edit"):
        pending = _current_pending(request)
        if pending:
            initial = {
                "company_name": pending.company_name,
                "owner_name": pending.owner_name,
                "email": pending.email,
                "mobile": pending.mobile,
                "username": pending.username,
            }

    if request.method == "POST":
        form = SignupForm(request.POST)
        if form.is_valid():
            pending = services.create_pending_signup(form.cleaned_data)
            request.session[SESSION_PENDING] = pending.token
            request.session.pop(SESSION_DEV_CODE, None)
            try:
                code = services.send_signup_code(pending)
            except services.OTPRateLimited as limited:
                messages.warning(request, limited.message)
            except Exception:
                messages.error(
                    request,
                    _("We couldn't send the email right now. Please try again in a minute."),
                )
                return render(request, "accounts/signup.html", {"form": form})
            else:
                if services.email_backend_is_console():
                    request.session[SESSION_DEV_CODE] = code
            return redirect("accounts:verify")
    else:
        form = SignupForm(initial=initial)

    return render(request, "accounts/signup.html", {"form": form})


def signup_verify(request):
    if request.user.is_authenticated:
        return redirect("dashboard")

    pending = _current_pending(request)
    if pending is None:
        messages.warning(request, _("Your sign-up expired. Please fill in your details again."))
        request.session.pop(SESSION_PENDING, None)
        return redirect("accounts:signup")

    form = OTPForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        outcome, left = services.verify_signup_code(pending, form.cleaned_data["code"])

        if outcome == services.CODE_OK:
            conflicts = services.signup_conflicts(pending)
            if conflicts:
                for problem in conflicts:
                    messages.error(request, problem)
                return redirect(reverse("accounts:signup") + "?edit=1")

            user = services.complete_signup(pending)
            request.session.pop(SESSION_PENDING, None)
            request.session.pop(SESSION_DEV_CODE, None)
            login(request, user, backend="django.contrib.auth.backends.ModelBackend")
            messages.success(
                request,
                _("Your %(days)d-day trial has started. Add your business details so they print on your invoices.")
                % {"days": getattr(settings, "TRIAL_DAYS", 14)},
            )
            return redirect("accounts:business_profile")

        if outcome == services.CODE_WRONG:
            form.add_error("code", _("That code is not right. %(left)d attempts left.") % {"left": left})
        elif outcome == services.CODE_DEAD:
            request.session.pop(SESSION_DEV_CODE, None)
            form.add_error("code", _("Too many wrong attempts. This code no longer works - ask for a new one."))
        elif outcome == services.CODE_EXPIRED:
            request.session.pop(SESSION_DEV_CODE, None)
            form.add_error("code", _("This code has expired. Ask for a new one."))
        else:
            form.add_error("code", _("There is no active code. Ask for a new one."))

    return render(request, "accounts/verify.html", {
        "form": form,
        "pending": pending,
        "resend_wait": services.resend_wait_seconds(pending.email),
        "dev_code": request.session.get(SESSION_DEV_CODE) if services.email_backend_is_console() else None,
        "otp_minutes": int(services.OTP_TTL.total_seconds() // 60),
    })


@require_POST
def signup_resend(request):
    pending = _current_pending(request)
    if pending is None:
        messages.warning(request, _("Your sign-up expired. Please fill in your details again."))
        return redirect("accounts:signup")

    try:
        code = services.send_signup_code(pending)
    except services.OTPRateLimited as limited:
        messages.warning(request, limited.message)
    except Exception:
        messages.error(request, _("We couldn't send the email right now. Please try again in a minute."))
    else:
        if services.email_backend_is_console():
            request.session[SESSION_DEV_CODE] = code
        messages.success(request, _("A new code was sent to %(email)s.") % {"email": pending.email})
    return redirect("accounts:verify")


def signup_edit(request):
    return redirect(reverse("accounts:signup") + "?edit=1")


@require_GET
def check_availability(request):
    """GET ?field=username|email|mobile&value=... -> JSON."""
    # Light limit so the endpoint can't be used to scan every email quickly.
    key = f"accounts:check:{services.client_ip(request)}"
    cache.add(key, 0, 60)
    try:
        hits = cache.incr(key)
    except ValueError:
        hits = 1
    if hits > 60:
        return JsonResponse(
            {"available": None, "message": _("Too many checks. Wait a minute."), "suggestions": []},
            status=429,
        )

    field = request.GET.get("field", "")
    value = request.GET.get("value", "")
    result = services.check_availability(field, value)

    if field == "username" and result["available"] is False:
        result["suggestions"] = services.suggest_usernames(
            request.GET.get("company_name", ""), request.GET.get("owner_name", ""), value
        )
    status = 400 if field not in ("username", "email", "mobile") else 200
    return JsonResponse(result, status=status)


# ==========================================================================
# Login
# ==========================================================================

def _safe_next(request):
    target = request.POST.get("next") or request.GET.get("next") or ""
    if target and url_has_allowed_host_and_scheme(
        target, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return target
    return ""


def login_view(request):
    if request.user.is_authenticated:
        return redirect("dashboard")

    form = LoginForm(request.POST or None)
    context = {"form": form, "next": _safe_next(request)}

    if request.method != "POST":
        return render(request, "accounts/login.html", context)

    identifier = (request.POST.get("username") or "").strip()
    ip = services.client_ip(request)

    blocked = services.login_block_seconds(identifier, ip)
    if blocked:
        messages.error(
            request,
            _("Too many failed attempts. Try again in %(minutes)d minutes, or reset your password.")
            % {"minutes": max(1, (blocked + 59) // 60)},
        )
        return render(request, "accounts/login.html", context, status=429)

    if not form.is_valid():
        messages.error(request, _("Enter your username, email or mobile and your password."))
        return render(request, "accounts/login.html", context)

    password = form.cleaned_data["password"]
    user = None
    for candidate in services.users_for_identifier(identifier):
        user = authenticate(request, username=candidate.username, password=password)
        if user is not None:
            break

    if user is None:
        services.record_login_failure(identifier, ip)
        messages.error(request, _("Wrong username/email/mobile or password."))
        return render(request, "accounts/login.html", context)

    try:
        profile = UserProfile.objects.select_related("company").get(user=user)
    except UserProfile.DoesNotExist:
        if not user.is_superuser:
            messages.error(request, _("Your account is not configured correctly."))
            return render(request, "accounts/login.html", context)
        profile = None

    if profile is not None:
        if not profile.is_active:
            messages.error(request, _("Your account has been deactivated."))
            return render(request, "accounts/login.html", context)
        if not profile.company.is_active:
            messages.error(request, _("Your company account is inactive."))
            return render(request, "accounts/login.html", context)

    services.clear_login_failures(identifier)
    login(request, user)

    if form.cleaned_data.get("remember"):
        request.session.set_expiry(
            getattr(settings, "ACCOUNTS_REMEMBER_ME_SECONDS", settings.SESSION_COOKIE_AGE)
        )
    else:
        request.session.set_expiry(0)  # ends when the browser closes

    messages.success(request, _("Welcome %(name)s!") % {"name": user.first_name or user.username})
    return redirect(context["next"] or "dashboard")


# ==========================================================================
# Business profile
# ==========================================================================

@login_required
def business_profile(request):
    # Always the caller's own company - there is no id in the URL to tamper with.
    company = getattr(request, "company", None)
    if company is None:
        messages.error(request, _("Your login is not linked to a business."))
        return redirect("dashboard")

    can_edit = request.user.is_superuser or role_of(request) in EDIT_ROLES
    status = services.profile_status(company)

    # Bind the form to a fresh copy, so invalid input never leaks into
    # request.company (the sidebar shows its name).
    instance = Company.objects.get(pk=company.pk)

    if request.method == "POST":
        if not can_edit:
            messages.error(request, _("Only the owner or a manager can change business details."))
            return redirect("accounts:business_profile")

        form = BusinessProfileForm(request.POST, request.FILES, instance=instance)
        if form.is_valid():
            saved = form.save()
            status = services.profile_status(saved)
            if status["complete"]:
                messages.success(request, _("Business details saved. Your invoices will use them."))
            else:
                messages.success(
                    request,
                    _("Saved. %(count)d details still missing for a complete invoice.")
                    % {"count": len(status["missing"])},
                )
            return redirect("accounts:business_profile")
        messages.error(request, _("Please fix the highlighted fields."))
    else:
        form = BusinessProfileForm(instance=instance, read_only=not can_edit)

    return render(request, "accounts/business_profile.html", {
        "form": form,
        "company": instance,
        "can_edit": can_edit,
        "status": status,
        "gst_states": GST_STATE_CODES,
        "required_fields": [name for name, _label in services.PROFILE_REQUIRED_FIELDS],
        "all_required": services.PROFILE_REQUIRED_FIELDS,
        "missing_names": [name for name, _label in status["missing"]],
    })
