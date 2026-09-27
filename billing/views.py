"""
Billing screens.

    /billing/                     the company's own subscription + plans
    /billing/checkout/<code>/     start paying for a plan
    /billing/payment/success/     browser returns here after Razorpay
    /billing/webhook/razorpay/    server-to-server confirmation
    /billing/manage/              YOUR screen: every company and its status
"""

from django.conf import settings
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from core.models import Company
from core.permissions import owner_required
from core.tenancy import company_of

from . import services
from .models import Plan, Subscription, SubscriptionPayment


@login_required
def home(request):
    """The tenant's own billing page: status, plans, payment history."""
    company = company_of(request)
    subscription = services.subscription_for(company)

    return render(request, "billing/home.html", {
        "subscription": subscription,
        "plans": Plan.objects.filter(is_active=True),
        "payments": SubscriptionPayment.objects.filter(company=company)[:20],
        "razorpay_enabled": services.razorpay_enabled(),
    })


@login_required
@owner_required
def checkout(request, code):
    """Only the account owner may spend money."""
    company = company_of(request)
    plan = get_object_or_404(Plan, code=code, is_active=True)

    payment, order_id = services.create_order(company, plan)

    return render(request, "billing/checkout.html", {
        "plan": plan,
        "payment": payment,
        "order_id": order_id,
        "razorpay_key": getattr(settings, "RAZORPAY_KEY_ID", ""),
        "razorpay_enabled": services.razorpay_enabled(),
        "company": company,
        "amount_paise": int(plan.price * 100),
    })


@login_required
@owner_required
def payment_success(request):
    """Razorpay's checkout script posts the result here."""
    if request.method != "POST":
        return redirect("billing:home")

    company = company_of(request)

    try:
        services.confirm_payment(
            company,
            order_id=request.POST.get("razorpay_order_id", ""),
            payment_id=request.POST.get("razorpay_payment_id", ""),
            signature=request.POST.get("razorpay_signature", ""),
        )
    except ValueError as exc:
        messages.error(request, f"Payment could not be confirmed: {exc}")
        return redirect("billing:home")

    messages.success(request, "Payment received. Your subscription is active.")
    return redirect("billing:home")


@csrf_exempt
def razorpay_webhook(request):
    """
    Razorpay calls this directly. No login, no CSRF - the signature is the proof.
    """
    if request.method != "POST":
        return HttpResponseBadRequest("POST only")

    signature = request.headers.get("X-Razorpay-Signature", "")

    try:
        services.handle_webhook(request.body, signature)
    except Exception as exc:
        return HttpResponseBadRequest(f"rejected: {exc}")

    return HttpResponse("ok")


# ---------------------------------------------------------------------------
# Your own admin screen (not for tenants)
# ---------------------------------------------------------------------------

@staff_member_required
def manage_companies(request):
    """Who is paying, who is expiring, who has stopped."""
    companies = (
        Company.objects
        .select_related("subscription", "subscription__plan")
        .order_by("company_name")
    )

    rows = []
    for company in companies:
        subscription = services.subscription_for(company)
        rows.append({
            "company": company,
            "subscription": subscription,
            "days_left": subscription.days_left,
        })

    return render(request, "billing/manage_companies.html", {
        "rows": rows,
        "plans": Plan.objects.filter(is_active=True),
        "today": timezone.localdate(),
    })


@staff_member_required
def extend_subscription(request, company_id):
    """Extend a subscription by hand, for money received offline (UPI, bank)."""
    if request.method != "POST":
        return redirect("billing:manage_companies")

    company = get_object_or_404(Company, id=company_id)
    subscription = services.subscription_for(company)

    days = int(request.POST.get("days") or 0)
    plan_code = request.POST.get("plan_code") or ""
    note = request.POST.get("note", "")[:200]

    plan = Plan.objects.filter(code=plan_code).first() if plan_code else None

    if plan and not days:
        days = plan.duration_days

    if days <= 0:
        messages.error(request, "Enter how many days to add.")
        return redirect("billing:manage_companies")

    subscription.extend(days=days, plan=plan, note=note or "Extended manually by staff.")

    if plan:
        SubscriptionPayment.objects.create(
            company=company,
            plan=plan,
            amount=plan.price,
            gateway=SubscriptionPayment.MANUAL,
            status=SubscriptionPayment.PAID,
            paid_at=timezone.now(),
        )

    messages.success(
        request,
        f"{company.company_name} is now active until {subscription.end_date}.",
    )
    return redirect("billing:manage_companies")
