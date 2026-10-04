"""
Subscription billing for the SaaS product.

Three tables:

    Plan                - what you sell (name, price, how many days, limits)
    Subscription        - one row per company: which plan, until when, what state
    SubscriptionPayment - one row per payment attempt, with the Razorpay ids

Company.subscription_start / subscription_end are kept in step with the
Subscription row so that older code reading those fields keeps working.
"""

from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone

from core.models import Company


class Plan(models.Model):
    """A sellable subscription plan."""

    BILLING_PERIODS = [
        ("monthly", "Monthly"),
        ("quarterly", "Quarterly"),
        ("yearly", "Yearly"),
    ]

    name = models.CharField(max_length=60)
    code = models.SlugField(max_length=40, unique=True)

    price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Price in rupees for one billing period.",
    )

    billing_period = models.CharField(
        max_length=20,
        choices=BILLING_PERIODS,
        default="monthly",
    )

    duration_days = models.PositiveIntegerField(
        default=30,
        help_text="How many days this plan adds to the subscription.",
    )

    # Limits. 0 means unlimited.
    max_users = models.PositiveIntegerField(default=0)
    max_sales_per_month = models.PositiveIntegerField(default=0)

    features = models.TextField(
        blank=True,
        help_text="One feature per line. Shown on the plans page.",
    )

    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["sort_order", "price"]

    def __str__(self):
        return f"{self.name} (Rs {self.price}/{self.billing_period})"

    def feature_list(self):
        return [line.strip() for line in self.features.splitlines() if line.strip()]


class Subscription(models.Model):
    """The subscription state of one company."""

    TRIAL = "trial"
    ACTIVE = "active"
    EXPIRED = "expired"
    CANCELLED = "cancelled"

    STATUS_CHOICES = [
        (TRIAL, "Free trial"),
        (ACTIVE, "Active"),
        (EXPIRED, "Expired"),
        (CANCELLED, "Cancelled"),
    ]

    company = models.OneToOneField(
        Company,
        on_delete=models.CASCADE,
        related_name="subscription",
    )

    plan = models.ForeignKey(
        Plan,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="subscriptions",
    )

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=TRIAL)

    start_date = models.DateField(default=timezone.localdate)
    end_date = models.DateField()

    cancelled_at = models.DateTimeField(null=True, blank=True)

    # Set by staff when a subscription is extended by hand (offline payment).
    note = models.CharField(max_length=200, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.company.company_name} - {self.status} till {self.end_date}"

    # ---------------- state questions the rest of the app asks ----------------

    @property
    def days_left(self):
        return (self.end_date - timezone.localdate()).days

    @property
    def is_expired(self):
        return self.status == self.CANCELLED or self.days_left < 0

    @property
    def is_running(self):
        """True while the company may still write data."""
        return not self.is_expired

    @property
    def in_trial(self):
        return self.status == self.TRIAL and not self.is_expired

    @property
    def needs_warning(self):
        """Show a renew banner in the last few days."""
        warn_days = getattr(settings, "SUBSCRIPTION_WARN_DAYS", 7)
        return self.is_running and self.days_left <= warn_days

    # ---------------- changes of state ----------------

    def extend(self, days, plan=None, note=""):
        """
        Add days to the subscription.

        Renewing early never loses time: the days are added to the current end
        date. Renewing after expiry starts from today.
        """
        today = timezone.localdate()
        base = self.end_date if self.end_date and self.end_date > today else today

        self.end_date = base + timedelta(days=days)
        self.status = self.ACTIVE
        if plan is not None:
            self.plan = plan
        if note:
            self.note = note
        self.cancelled_at = None
        self.save()

        self.sync_company()
        return self

    def mark_expired_if_due(self):
        if self.status in (self.TRIAL, self.ACTIVE) and self.days_left < 0:
            self.status = self.EXPIRED
            self.save(update_fields=["status", "updated_at"])
        return self

    def sync_company(self):
        """Keep the legacy Company.subscription_* fields in step."""
        company = self.company
        company.subscription_start = self.start_date
        company.subscription_end = self.end_date
        company.save(update_fields=["subscription_start", "subscription_end", "updated_at"])


class SubscriptionPayment(models.Model):
    """One payment attempt for a subscription (Razorpay or manual)."""

    CREATED = "created"
    PAID = "paid"
    FAILED = "failed"

    STATUS_CHOICES = [
        (CREATED, "Created"),
        (PAID, "Paid"),
        (FAILED, "Failed"),
    ]

    MANUAL = "manual"
    RAZORPAY = "razorpay"

    GATEWAY_CHOICES = [
        (RAZORPAY, "Razorpay"),
        (MANUAL, "Manual / offline"),
    ]

    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name="subscription_payments",
    )

    plan = models.ForeignKey(Plan, on_delete=models.SET_NULL, null=True, blank=True)

    amount = models.DecimalField(max_digits=10, decimal_places=2)

    gateway = models.CharField(max_length=20, choices=GATEWAY_CHOICES, default=RAZORPAY)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=CREATED)

    razorpay_order_id = models.CharField(max_length=100, blank=True, db_index=True)
    razorpay_payment_id = models.CharField(max_length=100, blank=True)
    razorpay_signature = models.CharField(max_length=200, blank=True)

    failure_reason = models.CharField(max_length=200, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    paid_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.company.company_name} Rs {self.amount} {self.status}"
