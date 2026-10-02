import re
from datetime import timedelta
from io import BytesIO

from django.contrib.auth.models import User
from django.core import mail
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from billing.models import Plan
from billing.services import start_trial
from core.models import Company, UserProfile

from . import services
from .forms import BusinessProfileForm, SignupForm
from .models import AccountSecurity, EmailOTP, PendingSignup
from .validators import gstin_check_digit, normalize_username, username_problem

PASSWORD = "TestPass#2026"

LOCMEM_EMAIL = "django.core.mail.backends.locmem.EmailBackend"


def make_company(name, username, role="owner", mobile="9000000001", email=None, **extra):
    company = Company.objects.create(
        company_name=name,
        owner_name=f"{name} Owner",
        email=email or f"{username}@example.com",
        mobile=mobile,
        subscription_start=timezone.localdate(),
        subscription_end=timezone.localdate(),
        **extra,
    )
    user = User.objects.create_user(
        username=username, password=PASSWORD, email=email or f"{username}@example.com"
    )
    UserProfile.objects.create(user=user, company=company, role=role, phone=mobile)
    start_trial(company)
    return company, user


def valid_gstin(state="10", pan="AABCS1234K"):
    first14 = f"{state}{pan}1Z"
    return first14 + gstin_check_digit(first14)


COMPLETE_PROFILE = {
    "address": "Naya Bazar",
    "city": "Lakhisarai",
    "state": "Bihar",
    "pincode": "811311",
    "bank_account_no": "123456789012",
    "bank_ifsc": "SBIN0001234",
    "bank_name": "State Bank of India",
}


SIGNUP_POST = {
    "company_name": "Sharma Rice Traders",
    "owner_name": "Rajesh Sharma",
    "email": "Rajesh@Example.com",
    "mobile": "+91 98765 43210",
    "username": "Sharma.Rice",
    "password1": "Basmati#Grain42",
    "password2": "Basmati#Grain42",
}


class CacheClearingTestCase(TestCase):
    def setUp(self):
        cache.clear()
        super().setUp()


# ==========================================================================
# Username rules
# ==========================================================================

class UsernameRuleTests(TestCase):

    def test_good_usernames(self):
        for name in ["sharma.rice", "raj_k2", "abcd", "a1b2c3", "rice.mill_24", "mahavir.traders"]:
            with self.subTest(name=name):
                self.assertIsNone(username_problem(name))

    def test_bad_usernames(self):
        bad = [
            "", "abc", "a" * 21,           # length
            "1rice", "_rice", ".rice",     # must start with a letter
            "rice..mill", "rice._mill",    # two symbols in a row
            "rice.", "rice_",              # ends with a symbol
            "rice-mill", "rice mill", "राइस",  # bad characters
            "admin", "root", "support", "billing", "staff", "system", "api", "www", "test",
            "ad.min", "admin1", "test123",   # still just a reserved word
        ]
        for name in bad:
            with self.subTest(name=name):
                self.assertIsNotNone(username_problem(name))

    def test_uppercase_is_normalised(self):
        self.assertEqual(normalize_username("  Sharma.Rice "), "sharma.rice")
        self.assertIsNone(username_problem(normalize_username("Sharma.Rice")))


# ==========================================================================
# Sign-up form uniqueness
# ==========================================================================

class SignupFormTests(CacheClearingTestCase):

    def setUp(self):
        super().setUp()
        make_company("Existing Rice", "existing.user", mobile="9123456780", email="Taken@Example.com")

    def form(self, **overrides):
        data = dict(SIGNUP_POST)
        data.update(overrides)
        return SignupForm(data)

    def test_valid_form_normalises(self):
        form = self.form()
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["username"], "sharma.rice")
        self.assertEqual(form.cleaned_data["mobile"], "9876543210")
        self.assertEqual(form.cleaned_data["email"], "Rajesh@example.com")

    def test_duplicate_username_any_case(self):
        form = self.form(username="EXISTING.User")
        self.assertFalse(form.is_valid())
        self.assertIn("username", form.errors)

    def test_duplicate_email_any_case(self):
        form = self.form(email="taken@EXAMPLE.com")
        self.assertFalse(form.is_valid())
        self.assertIn("email", form.errors)

    def test_duplicate_mobile_any_format(self):
        for mobile in ["9123456780", "+91 91234 56780", "09123456780"]:
            with self.subTest(mobile=mobile):
                form = self.form(mobile=mobile)
                self.assertFalse(form.is_valid())
                self.assertIn("mobile", form.errors)

    def test_duplicate_business_name_any_case(self):
        form = self.form(company_name="existing RICE")
        self.assertFalse(form.is_valid())
        self.assertIn("company_name", form.errors)

    def test_bad_mobile_and_weak_password(self):
        form = self.form(mobile="12345", password1="12345678", password2="12345678")
        self.assertFalse(form.is_valid())
        self.assertIn("mobile", form.errors)
        self.assertIn("password1", form.errors)

    def test_password_mismatch(self):
        form = self.form(password2="Different#Pass99")
        self.assertFalse(form.is_valid())
        self.assertIn("password2", form.errors)


# ==========================================================================
# Live availability endpoint
# ==========================================================================

class AvailabilityTests(CacheClearingTestCase):

    def setUp(self):
        super().setUp()
        make_company("Sharma Rice Traders", "sharmarice", mobile="9123456780", email="owner@sharma.in")
        self.url = reverse("accounts:check")

    def check(self, field, value, **extra):
        return self.client.get(self.url, {"field": field, "value": value, **extra}).json()

    def test_username_available(self):
        data = self.check("username", "new.trader")
        self.assertTrue(data["available"])

    def test_username_taken_case_insensitive_with_suggestions(self):
        data = self.check("username", "SharmaRice", company_name="Sharma Rice Traders", owner_name="Rajesh Sharma")
        self.assertFalse(data["available"])
        self.assertEqual(len(data["suggestions"]), 3)
        for suggestion in data["suggestions"]:
            self.assertIsNone(username_problem(suggestion))
            self.assertFalse(User.objects.filter(username__iexact=suggestion).exists())

    def test_username_rule_hint(self):
        data = self.check("username", "1x")
        self.assertIsNone(data["available"])
        self.assertTrue(data["message"])

    def test_email(self):
        self.assertFalse(self.check("email", "OWNER@sharma.in")["available"])
        self.assertTrue(self.check("email", "new@sharma.in")["available"])
        self.assertIsNone(self.check("email", "not-an-email")["available"])

    def test_mobile(self):
        self.assertFalse(self.check("mobile", "+91-91234-56780")["available"])
        self.assertTrue(self.check("mobile", "9988776655")["available"])
        self.assertIsNone(self.check("mobile", "12345")["available"])

    def test_unknown_field(self):
        response = self.client.get(self.url, {"field": "password", "value": "x"})
        self.assertEqual(response.status_code, 400)


# ==========================================================================
# Full sign-up with the emailed code
# ==========================================================================

@override_settings(EMAIL_BACKEND=LOCMEM_EMAIL)
class SignupFlowTests(CacheClearingTestCase):

    def start(self, **overrides):
        data = dict(SIGNUP_POST)
        data.update(overrides)
        return self.client.post(reverse("accounts:signup"), data)

    def code_from_mail(self, index=-1):
        return re.search(r"\b(\d{6})\b", mail.outbox[index].body).group(1)

    def test_full_signup(self):
        response = self.start()
        self.assertRedirects(response, reverse("accounts:verify"))

        # Nothing real exists yet.
        self.assertFalse(User.objects.filter(username="sharma.rice").exists())
        self.assertFalse(Company.objects.filter(company_name="Sharma Rice Traders").exists())
        pending = PendingSignup.objects.get()
        self.assertTrue(pending.password_hash.startswith("pbkdf2_") or "$" in pending.password_hash)
        self.assertNotIn("Basmati", pending.password_hash)

        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["Rajesh@example.com"])
        code = self.code_from_mail()
        self.assertNotEqual(EmailOTP.objects.get().code_hash, code)

        # The locmem backend is not the console one: no development box.
        page = self.client.get(reverse("accounts:verify"))
        self.assertNotContains(page, "Development mode")
        self.assertContains(page, 'autocomplete="one-time-code"')

        response = self.client.post(reverse("accounts:verify"), {"code": code})
        self.assertRedirects(response, reverse("accounts:business_profile"), fetch_redirect_response=False)

        user = User.objects.get(username="sharma.rice")
        self.assertTrue(user.check_password("Basmati#Grain42"))
        self.assertEqual(user.email, "Rajesh@example.com")
        profile = user.userprofile
        self.assertEqual(profile.role, "owner")
        self.assertEqual(profile.phone, "9876543210")
        self.assertEqual(profile.company.company_name, "Sharma Rice Traders")
        self.assertEqual(profile.company.mobile, "9876543210")
        self.assertTrue(profile.company.subscription.in_trial)
        self.assertTrue(AccountSecurity.objects.get(user=user).email_verified)

        # Logged in, with the welcome message.
        page = self.client.get(reverse("accounts:business_profile"))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "trial has started")

    def test_wrong_code_limit(self):
        self.start()
        code = self.code_from_mail()
        wrong = "000000" if code != "000000" else "111111"
        for attempt in range(5):
            response = self.client.post(reverse("accounts:verify"), {"code": wrong})
            self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Too many wrong attempts")

        # The right code is dead now.
        response = self.client.post(reverse("accounts:verify"), {"code": code})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(username="sharma.rice").exists())

    def test_expired_code(self):
        self.start()
        code = self.code_from_mail()
        EmailOTP.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
        response = self.client.post(reverse("accounts:verify"), {"code": code})
        self.assertContains(response, "expired")
        self.assertFalse(User.objects.filter(username="sharma.rice").exists())

    def test_expired_pending_signup(self):
        self.start()
        code = self.code_from_mail()
        PendingSignup.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
        response = self.client.post(reverse("accounts:verify"), {"code": code})
        self.assertRedirects(response, reverse("accounts:signup"))
        self.assertFalse(User.objects.filter(username="sharma.rice").exists())

    def test_resend_cooldown_and_hourly_cap(self):
        self.start()
        self.assertEqual(len(mail.outbox), 1)

        # Too soon.
        self.client.post(reverse("accounts:resend"))
        self.assertEqual(len(mail.outbox), 1)

        # After the cooldown a new code goes out and the old one stops working.
        old_code = self.code_from_mail()
        EmailOTP.objects.update(created_at=timezone.now() - timedelta(seconds=61))
        self.client.post(reverse("accounts:resend"))
        self.assertEqual(len(mail.outbox), 2)
        new_code = self.code_from_mail()
        if old_code != new_code:
            response = self.client.post(reverse("accounts:verify"), {"code": old_code})
            self.assertEqual(response.status_code, 200)
            self.assertFalse(User.objects.filter(username="sharma.rice").exists())

        # Hourly cap: 5 codes per email per hour.
        for _ in range(5):
            EmailOTP.objects.update(created_at=timezone.now() - timedelta(seconds=61))
            self.client.post(reverse("accounts:resend"))
        self.assertEqual(len(mail.outbox), 5)
        self.assertGreater(services.resend_wait_seconds("Rajesh@example.com"), 0)

        response = self.client.post(reverse("accounts:verify"), {"code": self.code_from_mail()})
        self.assertRedirects(response, reverse("accounts:business_profile"))

    def test_someone_took_the_username_meanwhile(self):
        self.start()
        code = self.code_from_mail()
        make_company("Other Co", "sharma.rice", mobile="9000000009")
        response = self.client.post(reverse("accounts:verify"), {"code": code})
        self.assertRedirects(response, reverse("accounts:signup") + "?edit=1", fetch_redirect_response=False)
        self.assertEqual(Company.objects.filter(company_name="Sharma Rice Traders").count(), 0)

    def test_change_email_prefills_the_form(self):
        self.start()
        page = self.client.get(reverse("accounts:signup_edit"), follow=True)
        self.assertContains(page, 'value="sharma.rice"')
        self.assertContains(page, 'value="Rajesh@example.com"')

    def test_old_register_url_shows_new_signup(self):
        page = self.client.get(reverse("register"))
        self.assertContains(page, 'data-check-url="%s"' % reverse("accounts:check"))

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.console.EmailBackend")
    def test_console_backend_shows_dev_code(self):
        import io
        from contextlib import redirect_stdout

        with redirect_stdout(io.StringIO()) as out:
            self.start()
        code = re.search(r"verification code is: (\d{6})", out.getvalue()).group(1)
        page = self.client.get(reverse("accounts:verify"))
        self.assertContains(page, "Development mode")
        self.assertContains(page, code)

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend")
    def test_smtp_backend_never_shows_code(self):
        from unittest import mock

        with mock.patch("accounts.services.send_mail", return_value=1):
            self.start()
        page = self.client.get(reverse("accounts:verify"))
        self.assertNotContains(page, "Development mode")


# ==========================================================================
# Login
# ==========================================================================

class LoginTests(CacheClearingTestCase):

    def setUp(self):
        super().setUp()
        self.company, self.user = make_company(
            "Login Rice", "login.user", mobile="9811122233", email="Login@Example.com"
        )
        self.url = reverse("accounts:login")

    def login(self, identifier, password=PASSWORD, **extra):
        return self.client.post(self.url, {"username": identifier, "password": password, **extra})

    def test_login_by_username_any_case(self):
        self.assertRedirects(self.login("LOGIN.user"), reverse("dashboard"), fetch_redirect_response=False)

    def test_login_by_email(self):
        self.assertRedirects(self.login("login@example.COM"), reverse("dashboard"), fetch_redirect_response=False)

    def test_login_by_mobile(self):
        for mobile in ["9811122233", "+91 98111 22233", "09811122233"]:
            with self.subTest(mobile=mobile):
                self.client.logout()
                self.assertRedirects(self.login(mobile), reverse("dashboard"), fetch_redirect_response=False)

    def test_old_user_without_verification_row_can_log_in(self):
        self.assertFalse(AccountSecurity.objects.filter(user=self.user).exists())
        self.assertEqual(self.login("login.user").status_code, 302)

    def test_remember_me(self):
        self.login("login.user")
        self.assertTrue(self.client.session.get_expire_at_browser_close())
        self.client.logout()
        self.login("login.user", remember="on")
        self.assertFalse(self.client.session.get_expire_at_browser_close())

    def test_wrong_password(self):
        response = self.login("login.user", "nope")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'value="login.user"')
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_throttle_by_identifier(self):
        for _ in range(5):
            self.login("login.user", "wrong")
        response = self.login("login.user")  # right password, but blocked
        self.assertEqual(response.status_code, 429)
        self.assertContains(response, "Too many failed attempts", status_code=429)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_throttle_by_ip(self):
        for index in range(5):
            self.login(f"nobody{index}", "wrong")
        response = self.login("login.user")
        self.assertEqual(response.status_code, 429)

    def test_block_expires(self):
        for _ in range(5):
            self.login("login.user", "wrong")
        cache.clear()  # what the 15-minute timeout does
        self.assertEqual(self.login("login.user").status_code, 302)

    def test_inactive_profile_and_company(self):
        UserProfile.objects.filter(user=self.user).update(is_active=False)
        self.assertContains(self.login("login.user"), "deactivated")
        UserProfile.objects.filter(user=self.user).update(is_active=True)
        Company.objects.filter(pk=self.company.pk).update(is_active=False)
        self.assertContains(self.login("login.user"), "inactive")

    def test_old_login_url_form_posts_to_accounts(self):
        page = self.client.get(reverse("login"))
        self.assertContains(page, 'action="%s"' % self.url)
        self.assertContains(page, "Keep me signed in")


# ==========================================================================
# Business profile
# ==========================================================================

class BusinessProfileTests(CacheClearingTestCase):

    def setUp(self):
        super().setUp()
        self.company, self.owner = make_company("Profile Rice", "profile.owner", mobile="9822233344")
        self.other, _other_user = make_company("Other Rice", "other.owner", mobile="9833344455")
        self.url = reverse("accounts:business_profile")
        self.client.login(username="profile.owner", password=PASSWORD)

    def post_data(self, **overrides):
        data = {
            "company_name": "Profile Rice",
            "owner_name": "Mr Profile",
            "email": "shop@profile.in",
            "mobile": "9822233344",
            "invoice_prefix": "PRF",
            "default_margin_percent": "8",
            **COMPLETE_PROFILE,
            "bank_account_no_confirm": COMPLETE_PROFILE["bank_account_no"],
        }
        data.update(overrides)
        return data

    def form(self, **overrides):
        return BusinessProfileForm(self.post_data(**overrides), instance=self.company)

    def test_gstin_fills_state_and_pan(self):
        gstin = valid_gstin("27", "AAPFU0939F")
        form = self.form(gst_number=gstin.lower(), state="Bihar", pan_number="")
        self.assertTrue(form.is_valid(), form.errors)
        company = form.save()
        self.assertEqual(company.gst_number, gstin)
        self.assertEqual(company.state, "Maharashtra")
        self.assertEqual(company.pan_number, "AAPFU0939F")

    def test_bad_gstin(self):
        for gstin in ["22AAAAA0000A1Z", "99AAPFU0939F1ZV", "27AAPFU0939F1ZX"]:
            with self.subTest(gstin=gstin):
                self.assertIn("gst_number", self.form(gst_number=gstin).errors)

    def test_pan_ifsc_upi_pincode_prefix(self):
        errors = self.form(
            pan_number="ABC123", bank_ifsc="SBIN1001234", upi_id="no-handle",
            pincode="011311", invoice_prefix="TOOLONG1",
        ).errors
        for field in ["pan_number", "bank_ifsc", "upi_id", "pincode", "invoice_prefix"]:
            self.assertIn(field, errors)
        form = self.form(pan_number="abcde1234f", bank_ifsc="sbin0001234", upi_id="profile@okicici", invoice_prefix="prf2")
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["bank_ifsc"], "SBIN0001234")
        self.assertEqual(form.cleaned_data["invoice_prefix"], "PRF2")

    def test_account_confirm_mismatch(self):
        form = self.form(bank_account_no_confirm="123456789099")
        self.assertIn("bank_account_no_confirm", form.errors)

        form = self.form(bank_account_no="12345", bank_account_no_confirm="12345")
        self.assertIn("bank_account_no", form.errors)

    def test_unchanged_account_needs_no_confirm(self):
        Company.objects.filter(pk=self.company.pk).update(bank_account_no="123456789012")
        self.company.refresh_from_db()
        form = self.form(bank_account_no_confirm="")
        self.assertTrue(form.is_valid(), form.errors)

    def test_logo_rules(self):
        from PIL import Image

        buffer = BytesIO()
        Image.new("RGB", (20, 20), "red").save(buffer, "PNG")
        good = SimpleUploadedFile("logo.png", buffer.getvalue(), content_type="image/png")
        form = BusinessProfileForm(self.post_data(), {"logo": good}, instance=self.company)
        self.assertTrue(form.is_valid(), form.errors)

        gif = BytesIO()
        Image.new("RGB", (20, 20), "red").save(gif, "GIF")
        bad = SimpleUploadedFile("logo.gif", gif.getvalue(), content_type="image/gif")
        form = BusinessProfileForm(self.post_data(), {"logo": bad}, instance=self.company)
        self.assertIn("logo", form.errors)

    def test_mobile_and_name_of_another_company_rejected(self):
        errors = self.form(mobile="9833344455", company_name="other rice").errors
        self.assertIn("mobile", errors)
        self.assertIn("company_name", errors)

    def test_owner_saves_own_company_only(self):
        response = self.client.post(self.url, self.post_data(company_name="Profile Rice Pvt"))
        self.assertRedirects(response, self.url)
        self.company.refresh_from_db()
        self.other.refresh_from_db()
        self.assertEqual(self.company.company_name, "Profile Rice Pvt")
        self.assertEqual(self.company.bank_ifsc, "SBIN0001234")
        self.assertEqual(self.other.company_name, "Other Rice")
        self.assertEqual(self.other.bank_ifsc, "")

    def test_tenant_isolation_ignores_injected_ids(self):
        self.client.post(
            self.url + f"?company={self.other.pk}",
            self.post_data(id=self.other.pk, pk=self.other.pk, company=self.other.pk, city="Patna"),
        )
        self.other.refresh_from_db()
        self.company.refresh_from_db()
        self.assertEqual(self.other.city, "")
        self.assertEqual(self.company.city, "Patna")

        # The other company's owner sees their own data, not ours.
        self.client.logout()
        self.client.login(username="other.owner", password=PASSWORD)
        page = self.client.get(self.url)
        self.assertContains(page, 'value="Other Rice"')
        self.assertNotContains(page, "Patna")

    def test_staff_is_read_only(self):
        staff = User.objects.create_user(username="profile.staff", password=PASSWORD)
        UserProfile.objects.create(user=staff, company=self.company, role="staff")
        self.client.logout()
        self.client.login(username="profile.staff", password=PASSWORD)

        page = self.client.get(self.url)
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "disabled")
        self.assertNotContains(page, "Save business details")

        self.client.post(self.url, self.post_data(city="Gaya"))
        self.company.refresh_from_db()
        self.assertEqual(self.company.city, "")

    def test_manager_can_edit(self):
        manager = User.objects.create_user(username="profile.mgr", password=PASSWORD)
        UserProfile.objects.create(user=manager, company=self.company, role="manager")
        self.client.logout()
        self.client.login(username="profile.mgr", password=PASSWORD)
        self.client.post(self.url, self.post_data(city="Gaya"))
        self.company.refresh_from_db()
        self.assertEqual(self.company.city, "Gaya")

    def test_login_required(self):
        self.client.logout()
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response["Location"])


# ==========================================================================
# profile_status + checkout gate
# ==========================================================================

class ProfileStatusTests(CacheClearingTestCase):

    def setUp(self):
        super().setUp()
        self.company, self.owner = make_company("Status Rice", "status.owner", mobile="9844455566")

    def test_incomplete(self):
        status = services.profile_status(self.company)
        self.assertFalse(status["complete"])
        missing = [field for field, _label in status["missing"]]
        self.assertIn("address", missing)
        self.assertIn("bank_ifsc", missing)
        self.assertNotIn("gst_number", missing)
        self.assertNotIn("company_name", missing)
        self.assertEqual(status["percent"], 30)  # 3 of 10

    def test_complete_without_gst(self):
        for field, value in COMPLETE_PROFILE.items():
            setattr(self.company, field, value)
        status = services.profile_status(self.company)
        self.assertTrue(status["complete"])
        self.assertEqual(status["percent"], 100)
        self.assertEqual(status["missing"], [])

    def test_none_company(self):
        self.assertFalse(services.profile_status(None)["complete"])

    def test_context_processor(self):
        self.client.login(username="status.owner", password=PASSWORD)
        response = self.client.get(reverse("accounts:business_profile"))
        self.assertIn("business_profile", response.context)
        self.assertFalse(response.context["business_profile"]["complete"])


class CheckoutGateTests(CacheClearingTestCase):

    def setUp(self):
        super().setUp()
        self.company, self.owner = make_company("Gate Rice", "gate.owner", mobile="9855566677")
        Plan.objects.get_or_create(
            code="monthly",
            defaults={"name": "Monthly", "price": 499, "duration_days": 30, "is_active": True},
        )
        self.client.login(username="gate.owner", password=PASSWORD)
        self.url = reverse("billing:checkout", args=["monthly"])

    def test_incomplete_profile_redirects_to_business_profile(self):
        response = self.client.get(self.url, follow=True)
        self.assertRedirects(response, reverse("accounts:business_profile"))
        self.assertContains(response, "Complete your business details before upgrading")

    def test_complete_profile_reaches_checkout(self):
        Company.objects.filter(pk=self.company.pk).update(**COMPLETE_PROFILE)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
