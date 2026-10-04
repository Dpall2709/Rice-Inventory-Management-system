"""
Validation rules shared by sign-up, login and the business profile page.

Every function here is pure (no request, no form) so it can be reused by the
live availability endpoint, the forms and the tests.
"""

import re

from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

# ---------------------------------------------------------------------------
# Username
# ---------------------------------------------------------------------------

USERNAME_MIN = 4
USERNAME_MAX = 20

# Names that would confuse customers or support staff if a tenant owned them.
RESERVED_USERNAMES = frozenset({
    "admin", "administrator", "root", "support", "help", "helpdesk", "billing",
    "staff", "system", "sys", "api", "www", "web", "mail", "email", "test",
    "testing", "demo", "null", "none", "undefined", "owner", "manager",
    "superuser", "moderator", "security", "info", "contact", "sales", "account",
    "accounts", "login", "logout", "signup", "register", "dashboard", "static",
    "media", "official", "ricebilling", "rice", "guest", "user", "username",
})

USERNAME_SYMBOLS = "._"

USERNAME_RULES = _(
    "4-20 characters: lowercase letters, digits, dot (.) and underscore (_). "
    "Start with a letter, no two symbols in a row, and don't end with a symbol."
)


def normalize_username(value):
    return (value or "").strip().lower()


def username_problem(value):
    """
    Return a translated message describing what is wrong with `value`, or None.

    `value` should already be normalised (lowercase, stripped).
    """
    if not value:
        return _("Choose a username.")
    if len(value) < USERNAME_MIN:
        return _("Username is too short - use at least %(min)d characters.") % {"min": USERNAME_MIN}
    if len(value) > USERNAME_MAX:
        return _("Username is too long - use at most %(max)d characters.") % {"max": USERNAME_MAX}
    if not re.fullmatch(r"[a-z0-9._]+", value):
        return _("Use only lowercase letters, digits, dot (.) and underscore (_).")
    if not value[0].isalpha():
        return _("Username must start with a letter.")
    if re.search(r"[._]{2}", value):
        return _("Don't put two symbols (. or _) next to each other.")
    if value[-1] in USERNAME_SYMBOLS:
        return _("Username can't end with a dot or underscore.")
    # "admin", "ad.min", "admin_1" and "test123" are all just a reserved word.
    core = re.sub(r"[._]", "", value)
    if core in RESERVED_USERNAMES or core.rstrip("0123456789") in RESERVED_USERNAMES:
        return _("That name is reserved. Please choose another.")
    return None


def validate_username_rules(value):
    problem = username_problem(normalize_username(value))
    if problem:
        raise ValidationError(problem, code="username_rules")


# ---------------------------------------------------------------------------
# Mobile
# ---------------------------------------------------------------------------

def normalize_mobile(raw):
    """
    Turn '+91 98765-43210', '098765 43210' or '9876543210' into '9876543210'.

    Returns the digits even when they are not a valid number, so the caller
    can decide what to say; use mobile_problem() to check.
    """
    digits = "".join(ch for ch in (raw or "") if ch.isdigit())
    if len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    elif len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    return digits


def mobile_problem(digits):
    if not digits:
        return _("Enter your mobile number.")
    if len(digits) != 10:
        return _("Enter a 10-digit mobile number.")
    if digits[0] not in "6789":
        return _("An Indian mobile number starts with 6, 7, 8 or 9.")
    return None


def mobile_variants(digits):
    """Ways the same number may already be stored by older code."""
    return [digits, "0" + digits, "91" + digits, "+91" + digits, "+91 " + digits]


# ---------------------------------------------------------------------------
# Indian states / union territories and GST state codes
# ---------------------------------------------------------------------------

# GST state code -> state name (as stored on Company.state)
GST_STATE_CODES = {
    "01": "Jammu and Kashmir",
    "02": "Himachal Pradesh",
    "03": "Punjab",
    "04": "Chandigarh",
    "05": "Uttarakhand",
    "06": "Haryana",
    "07": "Delhi",
    "08": "Rajasthan",
    "09": "Uttar Pradesh",
    "10": "Bihar",
    "11": "Sikkim",
    "12": "Arunachal Pradesh",
    "13": "Nagaland",
    "14": "Manipur",
    "15": "Mizoram",
    "16": "Tripura",
    "17": "Meghalaya",
    "18": "Assam",
    "19": "West Bengal",
    "20": "Jharkhand",
    "21": "Odisha",
    "22": "Chhattisgarh",
    "23": "Madhya Pradesh",
    "24": "Gujarat",
    "25": "Dadra and Nagar Haveli and Daman and Diu",
    "26": "Dadra and Nagar Haveli and Daman and Diu",
    "27": "Maharashtra",
    "28": "Andhra Pradesh",
    "29": "Karnataka",
    "30": "Goa",
    "31": "Lakshadweep",
    "32": "Kerala",
    "33": "Tamil Nadu",
    "34": "Puducherry",
    "35": "Andaman and Nicobar Islands",
    "36": "Telangana",
    "37": "Andhra Pradesh",
    "38": "Ladakh",
}

# Translatable labels for the dropdown. The stored value stays in English so
# invoices and reports print the same thing whatever language the user picks.
INDIAN_STATES = [
    ("Andhra Pradesh", _("Andhra Pradesh")),
    ("Arunachal Pradesh", _("Arunachal Pradesh")),
    ("Assam", _("Assam")),
    ("Bihar", _("Bihar")),
    ("Chhattisgarh", _("Chhattisgarh")),
    ("Goa", _("Goa")),
    ("Gujarat", _("Gujarat")),
    ("Haryana", _("Haryana")),
    ("Himachal Pradesh", _("Himachal Pradesh")),
    ("Jharkhand", _("Jharkhand")),
    ("Karnataka", _("Karnataka")),
    ("Kerala", _("Kerala")),
    ("Madhya Pradesh", _("Madhya Pradesh")),
    ("Maharashtra", _("Maharashtra")),
    ("Manipur", _("Manipur")),
    ("Meghalaya", _("Meghalaya")),
    ("Mizoram", _("Mizoram")),
    ("Nagaland", _("Nagaland")),
    ("Odisha", _("Odisha")),
    ("Punjab", _("Punjab")),
    ("Rajasthan", _("Rajasthan")),
    ("Sikkim", _("Sikkim")),
    ("Tamil Nadu", _("Tamil Nadu")),
    ("Telangana", _("Telangana")),
    ("Tripura", _("Tripura")),
    ("Uttar Pradesh", _("Uttar Pradesh")),
    ("Uttarakhand", _("Uttarakhand")),
    ("West Bengal", _("West Bengal")),
    # Union territories
    ("Andaman and Nicobar Islands", _("Andaman and Nicobar Islands")),
    ("Chandigarh", _("Chandigarh")),
    ("Dadra and Nagar Haveli and Daman and Diu", _("Dadra and Nagar Haveli and Daman and Diu")),
    ("Delhi", _("Delhi")),
    ("Jammu and Kashmir", _("Jammu and Kashmir")),
    ("Ladakh", _("Ladakh")),
    ("Lakshadweep", _("Lakshadweep")),
    ("Puducherry", _("Puducherry")),
]


# ---------------------------------------------------------------------------
# GSTIN / PAN / IFSC / UPI
# ---------------------------------------------------------------------------

GSTIN_RE = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
PAN_RE = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")
IFSC_RE = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")
UPI_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{1,255}@[A-Za-z][A-Za-z0-9]{1,63}$")
PINCODE_RE = re.compile(r"^[1-9][0-9]{5}$")
INVOICE_PREFIX_RE = re.compile(r"^[A-Z0-9]{2,6}$")

_GST_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def gstin_check_digit(first14):
    """The official GSTIN checksum (base-36 Luhn mod 36)."""
    total = 0
    for index, char in enumerate(first14):
        value = _GST_CHARS.index(char) * (2 if index % 2 else 1)
        total += value // 36 + value % 36
    return _GST_CHARS[(36 - total % 36) % 36]


def gstin_problem(gstin):
    if not GSTIN_RE.match(gstin):
        return _("That does not look like a GSTIN. Format: 22AAAAA0000A1Z5 (15 characters).")
    if gstin[:2] not in GST_STATE_CODES:
        return _("The first two digits of a GSTIN are the state code - %(code)s is not a valid state code.") % {"code": gstin[:2]}
    if gstin_check_digit(gstin[:14]) != gstin[14]:
        return _("This GSTIN's last character does not match - please check it for a typo.")
    return None


def state_from_gstin(gstin):
    return GST_STATE_CODES.get((gstin or "")[:2], "")


def pan_from_gstin(gstin):
    return (gstin or "")[2:12]
