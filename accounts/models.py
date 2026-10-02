"""
Account tables.

    PendingSignup    step 1 of sign-up. Nothing real (Company/User) exists yet.
    EmailOTP         one emailed 6-digit code. Only a hash of the code is stored.
    AccountSecurity  per-user flags, starting with "email verified".

Users created before this app existed have no AccountSecurity row; that is
fine - login never requires one.
"""

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class PendingSignup(models.Model):
    """Sign-up details waiting for the email code. Expires after 30 minutes."""

    # Random, unguessable id kept in the browser session.
    token = models.CharField(max_length=64, unique=True)

    company_name = models.CharField(_("business name"), max_length=200)
    owner_name = models.CharField(_("owner name"), max_length=200)
    email = models.EmailField(_("email"))
    mobile = models.CharField(_("mobile"), max_length=20)
    username = models.CharField(_("username"), max_length=150)

    # Hashed with make_password(); the raw password is never stored.
    password_hash = models.CharField(max_length=256)

    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["email"])]
        verbose_name = _("pending sign-up")
        verbose_name_plural = _("pending sign-ups")

    def __str__(self):
        return f"{self.username} <{self.email}>"

    @property
    def is_expired(self):
        return timezone.now() >= self.expires_at

    @property
    def is_usable(self):
        return self.completed_at is None and not self.is_expired


class EmailOTP(models.Model):
    """A one-time code sent by email."""

    SIGNUP = "signup"
    PURPOSE_CHOICES = ((SIGNUP, _("Sign-up")),)

    email = models.EmailField(db_index=True)
    purpose = models.CharField(max_length=20, choices=PURPOSE_CHOICES, default=SIGNUP)
    pending = models.ForeignKey(
        PendingSignup, null=True, blank=True, on_delete=models.CASCADE, related_name="codes"
    )

    code_hash = models.CharField(max_length=128)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    expires_at = models.DateTimeField()
    attempts = models.PositiveSmallIntegerField(default=0)

    # Set when the code was used, replaced by a newer code, or killed by too
    # many wrong guesses. A code with this set can never succeed again.
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = _("email code")
        verbose_name_plural = _("email codes")

    def __str__(self):
        return f"{self.purpose} code for {self.email}"

    @property
    def is_open(self):
        return self.closed_at is None and timezone.now() < self.expires_at


class AccountSecurity(models.Model):
    """Security facts about a login, kept outside core's tables."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="account_security"
    )
    email_verified = models.BooleanField(default=False)
    email_verified_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("account security")
        verbose_name_plural = _("account security")

    def __str__(self):
        return f"{self.user} ({'verified' if self.email_verified else 'unverified'})"
