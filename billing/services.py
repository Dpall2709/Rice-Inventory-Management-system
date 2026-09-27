"""
Subscription business logic. Views stay thin; the rules live here.
"""

import logging
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import Plan, Subscription, SubscriptionPayment

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Trial and activation
# ---------------------------------------------------------------------------

def start_trial(company, days=None):
    """
    Give a brand new company a free trial.

    Called from registration. Replaces the old behaviour of hardcoding a
    ten-year subscription for everyone who signed up.
    """
    days = days or getattr(settings, "TRIAL_DAYS", 14)
    today = timezone.localdate()

    subscription, created = Subscription.objects.get_or_create(
        company=company,
        defaults={
            "status": Subscription.TRIAL,
            "start_date": today,
            "end_date": today + timedelta(days=days),
        },
    )

    if created:
        subscription.sync_company()

    return subscription


def subscription_for(company):
    """
    The company's subscription row, creating a trial if it is missing.

    Companies that existed before billing was added keep their old
    Company.subscription_end date instead of getting a fresh trial.
    """
    try:
        return company.subscription
    except Subscription.DoesNotExist:
        pass

    end_date = company.subscription_end or (timezone.localdate() + timedelta(days=getattr(settings, "TRIAL_DAYS", 14)))

    subscription = Subscription.objects.create(
        company=company,
        status=Subscription.ACTIVE if end_date >= timezone.localdate() else Subscription.EXPIRED,
        start_date=company.subscription_start or timezone.localdate(),
        end_date=end_date,
        note="Created automatically from the old Company subscription dates.",
    )
    return subscription


@transaction.atomic
def activate_paid_plan(company, plan, payment=None, note=""):
    """Extend a company's subscription by one period of `plan`."""
    subscription = subscription_for(company)
    subscription.extend(days=plan.duration_days, plan=plan, note=note)

    if payment is not None:
        payment.status = SubscriptionPayment.PAID
        payment.paid_at = timezone.now()
        payment.save(update_fields=["status", "paid_at"])

    log.info(
        "Subscription activated: company=%s plan=%s until=%s",
        company.id, plan.code, subscription.end_date,
    )
    return subscription


# ---------------------------------------------------------------------------
# Razorpay
# ---------------------------------------------------------------------------

def razorpay_enabled():
    return bool(getattr(settings, "RAZORPAY_KEY_ID", "") and getattr(settings, "RAZORPAY_KEY_SECRET", ""))


def _client():
    import razorpay  # imported here so the app still runs without the package

    return razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))


def create_order(company, plan):
    """
    Create a payment row, plus a Razorpay order when keys are configured.

    Returns (payment, order_id). order_id is empty for manual/offline payment,
    which is what happens on a development machine with no Razorpay keys.
    """
    payment = SubscriptionPayment.objects.create(
        company=company,
        plan=plan,
        amount=plan.price,
        gateway=SubscriptionPayment.RAZORPAY if razorpay_enabled() else SubscriptionPayment.MANUAL,
    )

    if not razorpay_enabled():
        return payment, ""

    # Razorpay works in paise, so rupees are multiplied by 100.
    order = _client().order.create({
        "amount": int(plan.price * 100),
        "currency": "INR",
        "receipt": f"sub-{payment.id}",
        "notes": {
            "company_id": str(company.id),
            "company_name": company.company_name,
            "plan": plan.code,
            "payment_id": str(payment.id),
        },
    })

    payment.razorpay_order_id = order["id"]
    payment.save(update_fields=["razorpay_order_id"])

    return payment, order["id"]


def confirm_payment(company, order_id, payment_id, signature):
    """
    Verify what the browser sent back from Razorpay, then activate the plan.

    Never trust the browser: the signature proves the payment really happened.
    Returns the Subscription on success, or raises ValueError.
    """
    payment = (
        SubscriptionPayment.objects
        .filter(company=company, razorpay_order_id=order_id)
        .first()
    )

    if payment is None:
        raise ValueError("Unknown payment order.")

    if payment.status == SubscriptionPayment.PAID:
        return subscription_for(company)  # already handled (e.g. by the webhook)

    try:
        _client().utility.verify_payment_signature({
            "razorpay_order_id": order_id,
            "razorpay_payment_id": payment_id,
            "razorpay_signature": signature,
        })
    except Exception as exc:  # razorpay raises SignatureVerificationError
        payment.status = SubscriptionPayment.FAILED
        payment.failure_reason = str(exc)[:200]
        payment.save(update_fields=["status", "failure_reason"])
        raise ValueError("Payment signature could not be verified.") from exc

    payment.razorpay_payment_id = payment_id
    payment.razorpay_signature = signature
    payment.save(update_fields=["razorpay_payment_id", "razorpay_signature"])

    return activate_paid_plan(company, payment.plan, payment=payment)


def handle_webhook(body, signature):
    """
    Activate a subscription from a Razorpay webhook.

    The webhook is the reliable path: it arrives even if the customer closes the
    browser right after paying.
    """
    import json

    secret = getattr(settings, "RAZORPAY_WEBHOOK_SECRET", "")
    if not secret:
        raise ValueError("No webhook secret configured.")

    _client().utility.verify_webhook_signature(body.decode(), signature, secret)

    event = json.loads(body)
    if event.get("event") not in ("payment.captured", "order.paid"):
        return None

    entity = event["payload"].get("payment", {}).get("entity", {})
    order_id = entity.get("order_id")

    payment = SubscriptionPayment.objects.filter(razorpay_order_id=order_id).first()
    if payment is None or payment.status == SubscriptionPayment.PAID:
        return None

    payment.razorpay_payment_id = entity.get("id", "")
    payment.save(update_fields=["razorpay_payment_id"])

    return activate_paid_plan(payment.company, payment.plan, payment=payment)
