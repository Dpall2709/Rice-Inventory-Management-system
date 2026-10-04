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
from django.utils.translation import gettext as _
from django.utils.translation import gettext_noop

from core.models import Mill, Payment, Purchase
from core.services.ledger import mill_statement, purchase_payment_status
from core.tenancy import company_of, tenant_object_or_404

from ..base_imports import *

# Stored in the database as-is (English). gettext_noop only marks them for
# translation; the template translates the dropdown label, never the value.
PAYMENT_MODES = [gettext_noop("Cash"), gettext_noop("UPI"), gettext_noop("Bank transfer"), gettext_noop("Cheque")]


def read_payment(post):
    """Check what was typed. Returns (cleaned values, errors)."""
    errors = {}

    try:
        amount = Decimal((post.get("amount") or "").replace(",", "").strip())
    except (InvalidOperation, AttributeError):
        amount = None

    if amount is None:
        errors["amount"] = _("Enter the amount paid, in rupees.")
    elif amount <= 0:
        errors["amount"] = _("The amount must be more than zero.")

    mode = (post.get("payment_mode") or "").strip()
    if not mode:
        errors["payment_mode"] = _("Choose how you paid.")

    raw_date = (post.get("payment_date") or "").strip()
    try:
        paid_on = date.fromisoformat(raw_date) if raw_date else timezone.localdate()
    except ValueError:
        paid_on = None
        errors["payment_date"] = _("Enter a valid date.")

    if paid_on and paid_on > timezone.localdate():
        errors["payment_date"] = _("A payment cannot be dated in the future.")

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
                _(
                    "₹ %(amount)s saved. That is ₹ %(extra)s more than you owed "
                    "%(mill)s, so it is kept as an advance with the mill."
                ) % {"amount": values["amount"], "extra": extra, "mill": mill.mill_name},
            )
        else:
            messages.success(
                request,
                _(
                    "₹ %(amount)s paid to %(mill)s. "
                    "It has been applied to the oldest unpaid bills first."
                ) % {"amount": values["amount"], "mill": mill.mill_name},
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
                _(
                    "Bill %(invoice_no)s is settled. The extra ₹ %(extra)s has been "
                    "applied to %(mill)s's other unpaid bills "
                    "(or kept as advance if none are left)."
                ) % {"invoice_no": purchase.invoice_no, "extra": extra, "mill": purchase.mill.mill_name},
            )
        else:
            messages.success(
                request,
                _("₹ %(amount)s paid against bill %(invoice_no)s.")
                % {"amount": values["amount"], "invoice_no": purchase.invoice_no},
            )

        return redirect("purchase_detail", purchase_id=purchase.id)

    return render_form(request, context)
