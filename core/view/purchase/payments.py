"""
Paying a supplier.

Two entry points, one screen:

    /payment/mill/add/<mill>/          pay the mill (applied to the oldest bills)
    /payment/purchase/add/<purchase>/  pay one particular bill

Both are scoped to the logged-in company. The bill version used to fetch the
bill by id alone, so anyone could post a payment onto another company's bill by
editing the URL.
"""

from datetime import date
from decimal import Decimal, InvalidOperation

from django.utils import timezone

from core.models import Mill, Payment, Purchase
from core.services.ledger import mill_statement, purchase_payment_status
from core.tenancy import company_of, tenant_object_or_404

from ..base_imports import *

PAYMENT_MODES = ["Cash", "UPI", "Bank transfer", "Cheque"]


def read_payment(post):
    """Check what was typed. Returns (cleaned values, errors)."""
    errors = {}

    try:
        amount = Decimal((post.get("amount") or "").replace(",", "").strip())
    except (InvalidOperation, AttributeError):
        amount = None

    if amount is None:
        errors["amount"] = "Enter the amount paid, in rupees."
    elif amount <= 0:
        errors["amount"] = "The amount must be more than zero."

    mode = (post.get("payment_mode") or "").strip()
    if not mode:
        errors["payment_mode"] = "Choose how you paid."

    raw_date = (post.get("payment_date") or "").strip()
    try:
        paid_on = date.fromisoformat(raw_date) if raw_date else timezone.localdate()
    except ValueError:
        paid_on = None
        errors["payment_date"] = "Enter a valid date."

    if paid_on and paid_on > timezone.localdate():
        errors["payment_date"] = "A payment cannot be dated in the future."

    return {
        "amount": amount,
        "payment_mode": mode,
        "payment_date": paid_on,
        "notes": (post.get("notes") or "").strip()[:500],
    }, errors


def render_form(request, context):
    context.setdefault("modes", PAYMENT_MODES)
    context.setdefault("today", timezone.localdate())
    return render(request, "core/payment_form.html", context)


@login_required
def add_mill_payment(request, mill_id):
    """Money paid to the supplier without naming a bill."""
    company = company_of(request)
    mill = tenant_object_or_404(Mill, request, mill_id)
    statement = mill_statement(company, mill)

    context = {
        "mill": mill,
        "purchase": None,
        "due": statement["total_due"],
        "advance": statement["advance"],
        "values": {},
        "errors": {},
    }

    if request.method == "POST":
        values, errors = read_payment(request.POST)

        if errors:
            context.update(values=request.POST, errors=errors)
            return render_form(request, context)

        Payment.objects.create(
            company=company,
            related_type="purchase",
            mill=mill,
            purchase=None,
            amount=values["amount"],
            payment_mode=values["payment_mode"],
            payment_date=values["payment_date"],
            notes=values["notes"],
        )

        extra = values["amount"] - statement["total_due"]
        if extra > 0:
            messages.warning(
                request,
                f"₹ {values['amount']} saved. That is ₹ {extra} more than you owed "
                f"{mill.mill_name}, so it is kept as an advance with the mill.",
            )
        else:
            messages.success(
                request,
                f"₹ {values['amount']} paid to {mill.mill_name}. "
                "It has been applied to the oldest unpaid bills first.",
            )

        return redirect("mill_report_detail", mill_id=mill.id)

    return render_form(request, context)


@login_required
def add_purchase_payment(request, purchase_id):
    """Money paid against one particular bill."""
    company = company_of(request)
    purchase = tenant_object_or_404(
        Purchase.objects.select_related("mill"), request, purchase_id
    )
    status = purchase_payment_status(company, purchase)

    context = {
        "mill": purchase.mill,
        "purchase": purchase,
        "due": status["due"],
        "values": {"amount": status["due"] if status["due"] > 0 else ""},
        "errors": {},
    }

    if request.method == "POST":
        values, errors = read_payment(request.POST)

        if errors:
            context.update(values=request.POST, errors=errors)
            return render_form(request, context)

        Payment.objects.create(
            company=company,
            related_type="purchase",
            mill=purchase.mill,
            purchase=purchase,
            amount=values["amount"],
            payment_mode=values["payment_mode"],
            payment_date=values["payment_date"],
            notes=values["notes"],
        )

        extra = values["amount"] - status["due"]
        if extra > 0:
            messages.warning(
                request,
                f"Bill {purchase.invoice_no} is settled. The extra ₹ {extra} has been "
                f"applied to {purchase.mill.mill_name}'s other unpaid bills "
                "(or kept as advance if none are left).",
            )
        else:
            messages.success(request, f"₹ {values['amount']} paid against bill {purchase.invoice_no}.")

        return redirect("purchase_detail", purchase_id=purchase.id)

    return render_form(request, context)
