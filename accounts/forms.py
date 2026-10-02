import re
from decimal import Decimal

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.utils.translation import gettext_lazy as _

from core.models import Company

from . import services
from .validators import (
    GSTIN_RE,
    IFSC_RE,
    INDIAN_STATES,
    INVOICE_PREFIX_RE,
    PAN_RE,
    PINCODE_RE,
    UPI_RE,
    USERNAME_MAX,
    USERNAME_RULES,
    gstin_problem,
    mobile_problem,
    normalize_mobile,
    normalize_username,
    pan_from_gstin,
    state_from_gstin,
    username_problem,
)

User = get_user_model()

LOGO_MAX_BYTES = 2 * 1024 * 1024
LOGO_FORMATS = {"PNG", "JPEG", "WEBP"}


# ==========================================================================
# Sign-up step 1
# ==========================================================================

class SignupForm(forms.Form):
    company_name = forms.CharField(
        label=_("Business name"),
        max_length=200,
        widget=forms.TextInput(attrs={
            "placeholder": _("e.g. Sharma Rice Traders"),
            "autocomplete": "organization",
        }),
    )
    owner_name = forms.CharField(
        label=_("Owner name"),
        max_length=150,
        widget=forms.TextInput(attrs={
            "placeholder": _("Your full name"),
            "autocomplete": "name",
        }),
    )
    email = forms.EmailField(
        label=_("Email"),
        max_length=254,
        help_text=_("We'll send a 6-digit code here to confirm it's yours."),
        widget=forms.EmailInput(attrs={
            "placeholder": _("you@example.com"),
            "autocomplete": "email",
            "autocapitalize": "none",
            "data-check": "email",
        }),
    )
    mobile = forms.CharField(
        label=_("Mobile"),
        max_length=20,
        help_text=_("10-digit Indian mobile number."),
        widget=forms.TextInput(attrs={
            "placeholder": _("98765 43210"),
            "autocomplete": "tel-national",
            "inputmode": "tel",
            "data-check": "mobile",
        }),
    )
    username = forms.CharField(
        label=_("Username"),
        max_length=40,
        help_text=USERNAME_RULES,
        widget=forms.TextInput(attrs={
            "placeholder": _("e.g. sharma.rice"),
            "autocomplete": "username",
            "autocapitalize": "none",
            "autocorrect": "off",
            "spellcheck": "false",
            "maxlength": USERNAME_MAX,
            "data-check": "username",
        }),
    )
    password1 = forms.CharField(
        label=_("Password"),
        strip=False,
        widget=forms.PasswordInput(attrs={
            "autocomplete": "new-password",
            "placeholder": _("At least 8 characters"),
            "data-strength": "1",
        }),
    )
    password2 = forms.CharField(
        label=_("Confirm password"),
        strip=False,
        widget=forms.PasswordInput(attrs={
            "autocomplete": "new-password",
            "placeholder": _("Type it again"),
        }),
    )

    def clean_company_name(self):
        name = re.sub(r"\s+", " ", self.cleaned_data["company_name"]).strip()
        if len(name) < 3:
            raise forms.ValidationError(_("Business name is too short."))
        if not re.search(r"[A-Za-zऀ-ॿ]", name):
            raise forms.ValidationError(_("Business name must contain letters."))
        if services.company_name_taken(name):
            raise forms.ValidationError(_("A business with this name is already registered."))
        return name

    def clean_owner_name(self):
        name = re.sub(r"\s+", " ", self.cleaned_data["owner_name"]).strip()
        if len(name) < 2 or not re.search(r"[A-Za-zऀ-ॿ]", name):
            raise forms.ValidationError(_("Enter the owner's name."))
        return name

    def clean_email(self):
        email = self.cleaned_data["email"].strip()
        # Lowercase the domain; keep the local part as typed.
        local, _sep, domain = email.rpartition("@")
        email = f"{local}@{domain.lower()}"
        if services.email_taken(email):
            raise forms.ValidationError(
                _("This email is already registered. Log in or reset your password instead.")
            )
        return email

    def clean_mobile(self):
        digits = normalize_mobile(self.cleaned_data["mobile"])
        problem = mobile_problem(digits)
        if problem:
            raise forms.ValidationError(problem)
        if services.mobile_taken(digits):
            raise forms.ValidationError(_("This mobile number is already registered."))
        return digits

    def clean_username(self):
        username = normalize_username(self.cleaned_data["username"])
        problem = username_problem(username)
        if problem:
            raise forms.ValidationError(problem)
        if services.username_taken(username):
            raise forms.ValidationError(_("This username is taken."))
        return username

    def clean(self):
        cleaned = super().clean()
        password1 = cleaned.get("password1")
        password2 = cleaned.get("password2")

        if password1 and password2 and password1 != password2:
            self.add_error("password2", _("Passwords do not match."))

        if password1:
            probe = User(
                username=cleaned.get("username") or "",
                email=cleaned.get("email") or "",
                first_name=cleaned.get("owner_name") or "",
            )
            try:
                validate_password(password1, probe)
            except forms.ValidationError as error:
                self.add_error("password1", error)

        return cleaned


class OTPForm(forms.Form):
    code = forms.CharField(
        label=_("6-digit code"),
        max_length=12,
        widget=forms.TextInput(attrs={
            "inputmode": "numeric",
            "autocomplete": "one-time-code",
            "pattern": "[0-9 ]*",
            "maxlength": "7",
            "placeholder": "••••••",
            "autofocus": True,
        }),
    )

    def clean_code(self):
        code = re.sub(r"\D", "", self.cleaned_data["code"])
        if len(code) != 6:
            raise forms.ValidationError(_("Enter the 6-digit code from the email."))
        return code


# ==========================================================================
# Login
# ==========================================================================

class LoginForm(forms.Form):
    # Named "username" so older links / tests posting `username` keep working.
    username = forms.CharField(label=_("Username, email or mobile"), max_length=254)
    password = forms.CharField(label=_("Password"), strip=False, widget=forms.PasswordInput)
    remember = forms.BooleanField(label=_("Keep me signed in"), required=False)


# ==========================================================================
# Business profile
# ==========================================================================

class BusinessProfileForm(forms.ModelForm):
    state = forms.ChoiceField(label=_("State"), required=False)

    bank_account_no_confirm = forms.CharField(
        label=_("Confirm account number"),
        required=False,
        max_length=30,
        widget=forms.TextInput(attrs={"inputmode": "numeric", "autocomplete": "off"}),
    )

    class Meta:
        model = Company
        fields = [
            "company_name", "owner_name", "email", "mobile",
            "address", "city", "state", "pincode",
            "gst_number", "pan_number",
            "logo",
            "bank_account_name", "bank_account_no", "bank_ifsc", "bank_name",
            "bank_branch", "upi_id",
            "invoice_prefix", "invoice_terms", "default_margin_percent", "default_loading_rate_per_kg",
        ]
        labels = {
            "company_name": _("Business name"),
            "owner_name": _("Owner name"),
            "email": _("Business email"),
            "mobile": _("Mobile"),
            "address": _("Address"),
            "city": _("City / town"),
            "pincode": _("PIN code"),
            "gst_number": _("GSTIN"),
            "pan_number": _("PAN"),
            "logo": _("Logo"),
            "bank_account_name": _("Account holder name"),
            "bank_account_no": _("Account number"),
            "bank_ifsc": _("IFSC code"),
            "bank_name": _("Bank name"),
            "bank_branch": _("Branch"),
            "upi_id": _("UPI ID"),
            "invoice_prefix": _("Invoice number prefix"),
            "invoice_terms": _("Terms printed on invoice"),
            "default_margin_percent": _("Default margin %"),
            "default_loading_rate_per_kg": _("Loading charge per kg (₹)"),
        }
        help_texts = {
            "gst_number": _("Optional. Filling it sets your state and PAN automatically."),
            "pan_number": _("Optional. Format: ABCDE1234F"),
            "logo": _("PNG, JPG or WEBP, up to 2 MB."),
            "upi_id": _("Optional, e.g. sharmarice@okicici. Printed with a QR on invoices."),
            "invoice_prefix": _("2-6 capital letters or digits, e.g. SRT gives SRT-20260927-0001."),
            "invoice_terms": _("For example: Goods once sold will not be taken back."),
            "default_margin_percent": _("Used to suggest a selling price from your cost."),
            "default_loading_rate_per_kg": _("e.g. 0.10 - each truck's loading charge is filled as weight × this rate."),
            "bank_ifsc": _("11 characters, e.g. SBIN0001234. Printed on the invoice."),
        }
        widgets = {
            "company_name": forms.TextInput(attrs={"autocomplete": "organization"}),
            "owner_name": forms.TextInput(attrs={"autocomplete": "name"}),
            "email": forms.EmailInput(attrs={"autocomplete": "email"}),
            "mobile": forms.TextInput(attrs={"inputmode": "tel", "autocomplete": "tel-national"}),
            "address": forms.Textarea(attrs={"rows": 2, "autocomplete": "street-address"}),
            "city": forms.TextInput(attrs={"autocomplete": "address-level2"}),
            "pincode": forms.TextInput(attrs={"inputmode": "numeric", "maxlength": "6", "autocomplete": "postal-code"}),
            "gst_number": forms.TextInput(attrs={"maxlength": "15", "style": "text-transform:uppercase", "placeholder": "22AAAAA0000A1Z5"}),
            "pan_number": forms.TextInput(attrs={"maxlength": "10", "style": "text-transform:uppercase", "placeholder": "ABCDE1234F"}),
            "logo": forms.ClearableFileInput(attrs={"accept": "image/png,image/jpeg,image/webp"}),
            "bank_account_no": forms.TextInput(attrs={"inputmode": "numeric", "autocomplete": "off"}),
            "bank_ifsc": forms.TextInput(attrs={"maxlength": "11", "style": "text-transform:uppercase", "placeholder": "SBIN0001234"}),
            "upi_id": forms.TextInput(attrs={"autocapitalize": "none", "placeholder": "name@bank"}),
            "invoice_prefix": forms.TextInput(attrs={"maxlength": "6", "style": "text-transform:uppercase"}),
            "invoice_terms": forms.Textarea(attrs={"rows": 3}),
            "default_margin_percent": forms.NumberInput(attrs={"step": "0.5", "min": "0", "max": "100", "inputmode": "decimal"}),
            "default_loading_rate_per_kg": forms.NumberInput(attrs={"step": "0.01", "min": "0", "inputmode": "decimal"}),
        }

    def __init__(self, *args, read_only=False, **kwargs):
        super().__init__(*args, **kwargs)
        choices = [("", _("Select state"))] + list(INDIAN_STATES)
        current = (self.instance.state or "").strip()
        if current and current not in {value for value, _label in INDIAN_STATES}:
            # Keep older free-text values selectable instead of losing them.
            choices.append((current, current))
        self.fields["state"].choices = choices
        self.fields["state"].initial = current

        if self.instance.pk and self.instance.bank_account_no:
            self.fields["bank_account_no_confirm"].help_text = _(
                "Only needed when you change the account number."
            )

        self.fields["default_loading_rate_per_kg"].required = False

        if read_only:
            for field in self.fields.values():
                field.disabled = True

    # ----- simple fields -------------------------------------------------

    def clean_company_name(self):
        name = re.sub(r"\s+", " ", self.cleaned_data["company_name"]).strip()
        if len(name) < 3:
            raise forms.ValidationError(_("Business name is too short."))
        if services.company_name_taken(name, exclude_company=self.instance):
            raise forms.ValidationError(_("Another business already uses this name."))
        return name

    def clean_owner_name(self):
        return re.sub(r"\s+", " ", self.cleaned_data["owner_name"]).strip()

    def clean_mobile(self):
        digits = normalize_mobile(self.cleaned_data.get("mobile"))
        problem = mobile_problem(digits)
        if problem:
            raise forms.ValidationError(problem)
        if services.mobile_taken(digits, exclude_company=self.instance):
            raise forms.ValidationError(_("This mobile number is registered to another business."))
        return digits

    def clean_city(self):
        return re.sub(r"\s+", " ", self.cleaned_data.get("city") or "").strip()

    def clean_pincode(self):
        pin = re.sub(r"\s", "", self.cleaned_data.get("pincode") or "")
        if pin and not PINCODE_RE.match(pin):
            raise forms.ValidationError(_("A PIN code has 6 digits and doesn't start with 0."))
        return pin

    def clean_gst_number(self):
        gstin = re.sub(r"\s", "", self.cleaned_data.get("gst_number") or "").upper()
        if not gstin:
            return ""
        problem = gstin_problem(gstin)
        if problem:
            raise forms.ValidationError(problem)
        return gstin

    def clean_pan_number(self):
        pan = re.sub(r"\s", "", self.cleaned_data.get("pan_number") or "").upper()
        if pan and not PAN_RE.match(pan):
            raise forms.ValidationError(_("PAN format is ABCDE1234F (5 letters, 4 digits, 1 letter)."))
        return pan

    def clean_logo(self):
        logo = self.cleaned_data.get("logo")
        # Untouched existing file, or cleared: nothing to check.
        if not logo or not hasattr(logo, "content_type"):
            return logo
        if logo.size > LOGO_MAX_BYTES:
            raise forms.ValidationError(_("The logo is too large - keep it under 2 MB."))
        image = getattr(logo, "image", None)
        fmt = (getattr(image, "format", "") or "").upper()
        if fmt not in LOGO_FORMATS:
            raise forms.ValidationError(_("Upload a PNG, JPG or WEBP image."))
        return logo

    def clean_bank_account_no(self):
        number = re.sub(r"[\s-]", "", self.cleaned_data.get("bank_account_no") or "")
        if number and not re.fullmatch(r"[0-9]{9,18}", number):
            raise forms.ValidationError(_("A bank account number has 9 to 18 digits."))
        return number

    def clean_bank_ifsc(self):
        ifsc = re.sub(r"\s", "", self.cleaned_data.get("bank_ifsc") or "").upper()
        if ifsc and not IFSC_RE.match(ifsc):
            raise forms.ValidationError(
                _("IFSC is 11 characters: 4 letters, a zero, then 6 letters/digits (e.g. SBIN0001234).")
            )
        return ifsc

    def clean_upi_id(self):
        upi = (self.cleaned_data.get("upi_id") or "").strip()
        if upi and not UPI_RE.match(upi):
            raise forms.ValidationError(_("A UPI ID looks like name@bank."))
        return upi

    def clean_invoice_prefix(self):
        prefix = (self.cleaned_data.get("invoice_prefix") or "").strip().upper()
        if not INVOICE_PREFIX_RE.match(prefix):
            raise forms.ValidationError(_("Use 2 to 6 capital letters or digits."))
        return prefix

    def clean_default_loading_rate_per_kg(self):
        rate = self.cleaned_data.get("default_loading_rate_per_kg")
        if rate is None:
            return Decimal("0")
        if rate < 0 or rate > 100:
            raise forms.ValidationError(_("Enter a rate per kg between 0 and 100."))
        return rate

    def clean_default_margin_percent(self):
        margin = self.cleaned_data.get("default_margin_percent")
        if margin is None:
            return Decimal("0")
        if margin < 0 or margin > 100:
            raise forms.ValidationError(_("Margin must be between 0 and 100."))
        return margin

    # ----- cross-field rules ---------------------------------------------

    def clean(self):
        cleaned = super().clean()

        # GSTIN carries the state code (chars 1-2) and the PAN (chars 3-12).
        gstin = cleaned.get("gst_number")
        if gstin:
            cleaned["state"] = state_from_gstin(gstin)
            cleaned["pan_number"] = pan_from_gstin(gstin)
            self.errors.pop("pan_number", None)
            self.errors.pop("state", None)

        number = cleaned.get("bank_account_no")
        confirm = re.sub(r"[\s-]", "", cleaned.get("bank_account_no_confirm") or "")
        changed = number and number != (self.instance.bank_account_no or "")
        if changed and confirm != number:
            self.add_error(
                "bank_account_no_confirm",
                _("Account numbers don't match. Type the same number in both boxes."),
            )
        elif number and confirm and confirm != number:
            self.add_error(
                "bank_account_no_confirm",
                _("Account numbers don't match. Type the same number in both boxes."),
            )

        return cleaned

    def _post_clean(self):
        # The model field is a plain CharField; push the auto-filled values in.
        super()._post_clean()
        if "state" in self.cleaned_data:
            self.instance.state = self.cleaned_data["state"] or ""
        if "pan_number" in self.cleaned_data:
            self.instance.pan_number = self.cleaned_data["pan_number"] or ""
