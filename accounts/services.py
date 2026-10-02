"""
Account business logic: sign-up with an email code, login lookup and
throttling, and the business-profile completeness check.

Views stay thin; everything that needs a test lives here.

Throttling and the per-request counters use Django's cache. With no CACHES
setting Django uses LocMemCache, which is per-process: fine for one server
process, but with several gunicorn workers each worker counts on its own
(so the real limit is workers x 5). Point CACHES at Redis/Memcached in
production to share the counters.
"""

import hashlib
import hmac
import re
import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password
from django.core.cache import cache
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify
from django.utils.translation import gettext as _, gettext_lazy

from core.models import Company, UserProfile

from .models import AccountSecurity, EmailOTP, PendingSignup
from .validators import (
    USERNAME_MAX,
    mobile_problem,
    mobile_variants,
    normalize_mobile,
    normalize_username,
    username_problem,
)

User = get_user_model()


def _setting(name, default):
    return getattr(settings, name, default)


SIGNUP_TTL = timedelta(minutes=_setting("ACCOUNTS_SIGNUP_TTL_MINUTES", 30))
OTP_TTL = timedelta(minutes=_setting("ACCOUNTS_OTP_TTL_MINUTES", 10))
OTP_MAX_ATTEMPTS = _setting("ACCOUNTS_OTP_MAX_ATTEMPTS", 5)
OTP_RESEND_SECONDS = _setting("ACCOUNTS_OTP_RESEND_SECONDS", 60)
OTP_MAX_SENDS_PER_HOUR = _setting("ACCOUNTS_OTP_MAX_SENDS_PER_HOUR", 5)

LOGIN_MAX_FAILURES = _setting("ACCOUNTS_LOGIN_MAX_FAILURES", 5)
LOGIN_WINDOW_SECONDS = _setting("ACCOUNTS_LOGIN_WINDOW_SECONDS", 15 * 60)
LOGIN_BLOCK_SECONDS = _setting("ACCOUNTS_LOGIN_BLOCK_SECONDS", 15 * 60)


# ---------------------------------------------------------------------------
# Is it taken?
# ---------------------------------------------------------------------------

def username_taken(username):
    return User.objects.filter(username__iexact=username).exists()


def email_taken(email):
    return User.objects.filter(email__iexact=(email or "").strip()).exists()


def mobile_taken(digits, exclude_company=None):
    variants = mobile_variants(digits)
    profiles = UserProfile.objects.filter(phone__in=variants)
    companies = Company.objects.filter(mobile__in=variants)
    if exclude_company is not None:
        profiles = profiles.exclude(company=exclude_company)
        companies = companies.exclude(pk=exclude_company.pk)
    return profiles.exists() or companies.exists()


def company_name_taken(name, exclude_company=None):
    qs = Company.objects.filter(company_name__iexact=(name or "").strip())
    if exclude_company is not None:
        qs = qs.exclude(pk=exclude_company.pk)
    return qs.exists()


def suggest_usernames(*sources, count=3):
    """
    Up to `count` free usernames built from the business / owner name.

    'Sharma Rice Traders', 'Rajesh Sharma' ->
        ['sharmarice', 'rajesh.sharma', 'sharma.rice.traders', 'sharmarice24', ...]
    """
    candidates = []

    def add(value):
        value = re.sub(r"[^a-z0-9._]", "", value.lower())
        value = re.sub(r"[._]{2,}", ".", value).strip("._")[:USERNAME_MAX].strip("._")
        if value and value not in candidates:
            candidates.append(value)

    for source in sources:
        words = [w for w in slugify(source or "").split("-") if w]
        if not words:
            continue
        add("".join(words[:2]))
        add(".".join(words[:2]))
        add("_".join(words[:2]))
        add(words[0])
        add("".join(words))
        add(".".join(words))
        if len(words) > 1:
            add(words[0][0] + words[-1])

    base = [c for c in candidates]
    for stem in base[:3]:
        for _i in range(4):
            add(f"{stem[:USERNAME_MAX - 3]}{secrets.randbelow(900) + 100}")

    found = []
    for candidate in candidates:
        if len(found) >= count:
            break
        if username_problem(candidate) is None and not username_taken(candidate):
            found.append(candidate)
    return found


def check_availability(field, value):
    """
    Used by the live checker on the sign-up form.

    Returns {"available": bool | None, "message": str, "suggestions": [...]}.
    `available` is None when the value breaks a rule (nothing was looked up).
    """
    value = (value or "").strip()
    result = {"field": field, "available": None, "message": "", "suggestions": []}

    if field == "username":
        username = normalize_username(value)
        problem = username_problem(username)
        if problem:
            result["message"] = str(problem)
        elif username_taken(username):
            result["available"] = False
            result["message"] = _("This username is taken.")
        else:
            result["available"] = True
            result["message"] = _("Username is available.")
    elif field == "email":
        from django.core.validators import validate_email
        from django.core.exceptions import ValidationError

        try:
            validate_email(value)
        except ValidationError:
            result["message"] = _("Enter a valid email address.")
            return result
        if email_taken(value):
            result["available"] = False
            result["message"] = _("This email is already registered. Try logging in instead.")
        else:
            result["available"] = True
            result["message"] = _("Email is available.")
    elif field == "mobile":
        digits = normalize_mobile(value)
        problem = mobile_problem(digits)
        if problem:
            result["message"] = str(problem)
        elif mobile_taken(digits):
            result["available"] = False
            result["message"] = _("This mobile number is already registered.")
        else:
            result["available"] = True
            result["message"] = _("Mobile number is available.")
    else:
        result["message"] = _("Unknown field.")
    return result


# ---------------------------------------------------------------------------
# Sign-up step 1: pending row + emailed code
# ---------------------------------------------------------------------------

class OTPRateLimited(Exception):
    """Too soon or too many codes. `wait` is the number of seconds to wait."""

    def __init__(self, message, wait):
        super().__init__(message)
        self.message = message
        self.wait = wait


def create_pending_signup(data):
    """Store step-1 data. `data` is the sign-up form's cleaned_data."""
    return PendingSignup.objects.create(
        token=secrets.token_urlsafe(32),
        company_name=data["company_name"],
        owner_name=data["owner_name"],
        email=data["email"],
        mobile=data["mobile"],
        username=data["username"],
        password_hash=make_password(data["password1"]),
        expires_at=timezone.now() + SIGNUP_TTL,
    )


def pending_from_token(token):
    if not token:
        return None
    return PendingSignup.objects.filter(token=token).first()


def _hash_code(email, code):
    message = f"{email.lower()}:{code}".encode()
    return hmac.new(settings.SECRET_KEY.encode(), message, hashlib.sha256).hexdigest()


def resend_wait_seconds(email, purpose=EmailOTP.SIGNUP):
    """Seconds until another code may be sent to this email (0 = now)."""
    now = timezone.now()
    codes = EmailOTP.objects.filter(email__iexact=email, purpose=purpose)

    last = codes.order_by("-created_at", "-id").first()
    wait = 0
    if last:
        wait = max(wait, int((last.created_at + timedelta(seconds=OTP_RESEND_SECONDS) - now).total_seconds()) + 1)

    hour_ago = now - timedelta(hours=1)
    recent = list(codes.filter(created_at__gt=hour_ago).order_by("created_at").values_list("created_at", flat=True))
    if len(recent) >= OTP_MAX_SENDS_PER_HOUR:
        oldest_counted = recent[-OTP_MAX_SENDS_PER_HOUR]
        wait = max(wait, int((oldest_counted + timedelta(hours=1) - now).total_seconds()) + 1)

    return max(wait, 0)


def send_signup_code(pending):
    """
    Create a fresh code, close older ones and email it.

    Returns the plain code (the caller may show it only in development).
    Raises OTPRateLimited when the cooldown or hourly cap applies.
    """
    wait = resend_wait_seconds(pending.email)
    if wait:
        hourly = EmailOTP.objects.filter(
            email__iexact=pending.email, purpose=EmailOTP.SIGNUP,
            created_at__gt=timezone.now() - timedelta(hours=1),
        ).count() >= OTP_MAX_SENDS_PER_HOUR
        if hourly:
            message = _("Too many codes sent to this email. Try again in %(minutes)d minutes.") % {
                "minutes": max(1, (wait + 59) // 60)
            }
        else:
            message = _("Please wait %(seconds)d seconds before asking for a new code.") % {"seconds": wait}
        raise OTPRateLimited(message, wait)

    code = f"{secrets.randbelow(1_000_000):06d}"
    now = timezone.now()

    with transaction.atomic():
        EmailOTP.objects.filter(
            pending=pending, closed_at__isnull=True
        ).update(closed_at=now)
        EmailOTP.objects.create(
            email=pending.email,
            purpose=EmailOTP.SIGNUP,
            pending=pending,
            code_hash=_hash_code(pending.email, code),
            created_at=now,
            expires_at=now + OTP_TTL,
        )

    subject = _("%(code)s is your Rice Billing verification code") % {"code": code}
    body = _(
        "Hello %(name)s,\n\n"
        "Your verification code is: %(code)s\n\n"
        "It expires in %(minutes)d minutes. If you did not try to sign up, ignore this email.\n\n"
        "- Rice Billing"
    ) % {"name": pending.owner_name, "code": code, "minutes": int(OTP_TTL.total_seconds() // 60)}

    send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [pending.email], fail_silently=False)
    return code


def email_backend_is_console():
    return _setting("EMAIL_BACKEND", "") == "django.core.mail.backends.console.EmailBackend"


# Outcomes of verify_signup_code()
CODE_OK = "ok"
CODE_WRONG = "wrong"
CODE_DEAD = "dead"        # too many wrong attempts
CODE_EXPIRED = "expired"
CODE_MISSING = "missing"  # no live code: ask for a new one


def verify_signup_code(pending, code):
    """Check a code. Returns (outcome, attempts_left)."""
    code = re.sub(r"\D", "", code or "")

    with transaction.atomic():
        otp = (
            EmailOTP.objects.select_for_update()
            .filter(pending=pending, purpose=EmailOTP.SIGNUP)
            .order_by("-created_at", "-id")
            .first()
        )
        if otp is None or otp.closed_at is not None:
            if otp is not None and otp.attempts >= OTP_MAX_ATTEMPTS:
                return CODE_DEAD, 0
            return CODE_MISSING, 0

        if timezone.now() >= otp.expires_at:
            otp.closed_at = timezone.now()
            otp.save(update_fields=["closed_at"])
            return CODE_EXPIRED, 0

        if len(code) == 6 and hmac.compare_digest(otp.code_hash, _hash_code(pending.email, code)):
            otp.closed_at = timezone.now()
            otp.save(update_fields=["closed_at"])
            return CODE_OK, OTP_MAX_ATTEMPTS - otp.attempts

        otp.attempts += 1
        if otp.attempts >= OTP_MAX_ATTEMPTS:
            otp.closed_at = timezone.now()
            otp.save(update_fields=["attempts", "closed_at"])
            return CODE_DEAD, 0
        otp.save(update_fields=["attempts"])
        return CODE_WRONG, OTP_MAX_ATTEMPTS - otp.attempts


def signup_conflicts(pending):
    """Re-check uniqueness at the last moment (someone may have taken it)."""
    problems = []
    if username_taken(pending.username):
        problems.append(_("The username “%(value)s” was taken meanwhile.") % {"value": pending.username})
    if email_taken(pending.email):
        problems.append(_("The email %(value)s was registered meanwhile.") % {"value": pending.email})
    if mobile_taken(pending.mobile):
        problems.append(_("The mobile number %(value)s was registered meanwhile.") % {"value": pending.mobile})
    if company_name_taken(pending.company_name):
        problems.append(_("The business name “%(value)s” was registered meanwhile.") % {"value": pending.company_name})
    return problems


@transaction.atomic
def complete_signup(pending):
    """Create Company + User + UserProfile + trial, mark the email verified."""
    from core.services.registration_service import register_company

    pending = PendingSignup.objects.select_for_update().get(pk=pending.pk)
    if pending.completed_at is not None:
        raise ValueError("This sign-up was already completed.")

    company = register_company(
        {
            "company_name": pending.company_name,
            "owner_name": pending.owner_name,
            "email": pending.email,
            "mobile": pending.mobile,
            "username": pending.username,
        },
        password_hash=pending.password_hash,
    )
    user = UserProfile.objects.select_related("user").get(company=company, role="owner").user

    now = timezone.now()
    AccountSecurity.objects.update_or_create(
        user=user, defaults={"email_verified": True, "email_verified_at": now}
    )

    pending.completed_at = now
    pending.password_hash = ""  # no reason to keep it around
    pending.save(update_fields=["completed_at", "password_hash"])
    return user


def purge_stale_signups():
    """Delete expired pending sign-ups (and their codes). Safe to call anytime."""
    cutoff = timezone.now() - timedelta(days=1)
    PendingSignup.objects.filter(expires_at__lt=cutoff).delete()
    EmailOTP.objects.filter(pending__isnull=True, created_at__lt=cutoff).delete()


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------

def users_for_identifier(identifier):
    """
    Users that the "username, email or mobile" box could mean.

    Usually one. Older data may hold the same email twice, so the caller tries
    the password against each.
    """
    identifier = (identifier or "").strip()
    if not identifier:
        return []

    if "@" in identifier:
        return list(User.objects.filter(email__iexact=identifier).order_by("id"))

    digits = normalize_mobile(identifier)
    if re.fullmatch(r"[+0-9 ()-]+", identifier) and mobile_problem(digits) is None:
        variants = mobile_variants(digits)
        users = list(
            User.objects.filter(userprofile__phone__in=variants).order_by("id")
        )
        if not users:
            # Older accounts kept the number only on the company.
            users = list(
                User.objects.filter(
                    userprofile__company__mobile__in=variants, userprofile__role="owner"
                ).order_by("id")
            )
        if users:
            return users

    exact = list(User.objects.filter(username=identifier))
    if exact:
        return exact
    return list(User.objects.filter(username__iexact=identifier).order_by("id"))


def _throttle_keys(identifier, ip):
    ident = hashlib.sha256((identifier or "").strip().lower().encode()).hexdigest()[:32]
    return [f"accounts:login:id:{ident}", f"accounts:login:ip:{ip or 'unknown'}"]


def login_block_seconds(identifier, ip):
    """Seconds left on a block for this identifier or IP (0 = not blocked)."""
    now = timezone.now().timestamp()
    left = 0
    for key in _throttle_keys(identifier, ip):
        until = cache.get(key + ":blocked")
        if until:
            left = max(left, int(until - now) + 1)
    return left


def record_login_failure(identifier, ip):
    for key in _throttle_keys(identifier, ip):
        cache.add(key, 0, LOGIN_WINDOW_SECONDS)
        try:
            count = cache.incr(key)
        except ValueError:
            cache.set(key, 1, LOGIN_WINDOW_SECONDS)
            count = 1
        if count >= LOGIN_MAX_FAILURES:
            until = timezone.now().timestamp() + LOGIN_BLOCK_SECONDS
            cache.set(key + ":blocked", until, LOGIN_BLOCK_SECONDS)
            cache.delete(key)


def clear_login_failures(identifier):
    key = _throttle_keys(identifier, None)[0]
    cache.delete(key)
    cache.delete(key + ":blocked")


def client_ip(request):
    # REMOTE_ADDR only: X-Forwarded-For can be forged by the client. Behind a
    # proxy, make the proxy set REMOTE_ADDR (e.g. gunicorn --forwarded-allow-ips).
    return request.META.get("REMOTE_ADDR", "")


# ---------------------------------------------------------------------------
# Business profile completeness
# ---------------------------------------------------------------------------

PROFILE_REQUIRED_FIELDS = [
    ("company_name", gettext_lazy("Business name")),
    ("owner_name", gettext_lazy("Owner name")),
    ("mobile", gettext_lazy("Mobile")),
    ("address", gettext_lazy("Address")),
    ("city", gettext_lazy("City")),
    ("state", gettext_lazy("State")),
    ("pincode", gettext_lazy("PIN code")),
    ("bank_account_no", gettext_lazy("Bank account number")),
    ("bank_ifsc", gettext_lazy("IFSC code")),
    ("bank_name", gettext_lazy("Bank name")),
]


def profile_status(company):
    """
    How complete the invoice identity of `company` is.

        {"complete": bool, "percent": int, "missing": [(field, label), ...]}

    GSTIN, PAN, UPI and logo are optional (GST registration is optional for
    many rice traders), so they don't count.
    """
    if company is None:
        return {"complete": False, "percent": 0, "missing": list(PROFILE_REQUIRED_FIELDS)}

    missing = [
        (field, label)
        for field, label in PROFILE_REQUIRED_FIELDS
        if not str(getattr(company, field, "") or "").strip()
    ]
    total = len(PROFILE_REQUIRED_FIELDS)
    percent = int(round(100 * (total - len(missing)) / total))
    return {"complete": not missing, "percent": percent, "missing": missing}
