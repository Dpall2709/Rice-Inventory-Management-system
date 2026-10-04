"""
Purchase list and purchase detail.
"""

from django.core.paginator import Paginator
from django.db.models import DecimalField, F, OuterRef, Q, Subquery, Sum, Value
from django.db.models.functions import Coalesce

from decimal import Decimal, InvalidOperation

from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.translation import gettext as _

from core.models import Mill, Payment, Purchase, PurchaseExpense, PurchaseItem
from core.services.costing import line_costing, purchase_costing
from core.services.ledger import paid_map_for_purchases, purchase_payment_status
from core.services.periods import date_range, period_chips
from core.permissions import manager_required
from core.tenancy import company_of, tenant_object_or_404

from ..base_imports import *

money = DecimalField(max_digits=14, decimal_places=2)


@login_required
def purchase_list(request):
    company = company_of(request)

    q = request.GET.get("q", "").strip()
    mill_id = request.GET.get("mill", "")
    status = request.GET.get("status", "")
    date_from, date_to = date_range(request.GET)

    purchases = (
        Purchase.objects
        .for_company(company)
        .select_related("mill")
        .prefetch_related("purchaseitem_set__product")
        .annotate(bags=Coalesce(Sum("purchaseitem__bag_count"), Value(0)))
        .order_by("-purchase_date", "-id")
    )

    if q:
        purchases = purchases.filter(
            Q(invoice_no__icontains=q)
            | Q(purchase_ref__icontains=q)
            | Q(mill__mill_name__icontains=q)
        )
    if mill_id.isdigit():
        purchases = purchases.filter(mill_id=int(mill_id))
    if date_from:
        purchases = purchases.filter(purchase_date__gte=date_from)
    if date_to:
        purchases = purchases.filter(purchase_date__lte=date_to)

    # Paid / due per bill the way the supplier ledger works it out: money paid
    # to the mill without naming a bill also settles its oldest bills. The
    # Paid / Unpaid filter and the totals use the same figures, so a bill the
    # list shows as paid never turns up under "Only unpaid".
    purchases = list(purchases)
    settled = paid_map_for_purchases(company, purchases)
    for purchase in purchases:
        row = settled.get(purchase.id) or {}
        purchase.paid = row.get("paid", Decimal("0"))
        purchase.due = row.get("due", purchase.total_amount)
        purchase.applied_from_account = row.get("applied_from_account", Decimal("0"))
        purchase.paid_percent = (
            min(int(purchase.paid * 100 / purchase.total_amount), 100) if purchase.total_amount else 100
        )
        purchase.weight_kg = sum((item.total_kg for item in purchase.purchaseitem_set.all()), Decimal("0"))
        purchase.rice = sorted({item.product.rice_name for item in purchase.purchaseitem_set.all()})

    if status == "due":
        purchases = [p for p in purchases if p.due > 0]
    elif status == "partial":
        purchases = [p for p in purchases if p.due > 0 and p.paid > 0]
    elif status == "paid":
        purchases = [p for p in purchases if p.due <= 0]

    totals = {
        "total_value": sum((p.total_amount for p in purchases), Decimal("0")),
        "total_paid": sum((p.paid for p in purchases), Decimal("0")),
        "total_due": sum((p.due for p in purchases if p.due > 0), Decimal("0")),
        "total_tax": sum((p.cgst_amount + p.sgst_amount + p.igst_amount for p in purchases), Decimal("0")),
        "total_bags": sum((int(p.bags or 0) for p in purchases)),
        "total_kg": sum((p.weight_kg for p in purchases), Decimal("0")),
        "bills_paid": sum(1 for p in purchases if p.due <= 0),
        "bills_partial": sum(1 for p in purchases if p.due > 0 and p.paid > 0),
        "bills_due": sum(1 for p in purchases if p.due > 0 and p.paid <= 0),
    }

    page = Paginator(purchases, 25).get_page(request.GET.get("page"))

    params = request.GET.copy()
    params.pop("page", None)

    return render(request, "core/purchase_list.html", {
        "page_obj": page,
        "purchases": page.object_list,
        "mills": Mill.objects.for_company(company).order_by("mill_name"),
        "q": q,
        "mill_id": mill_id,
        "status": status,
        "date_from": date_from,
        "date_to": date_to,
        "periods": period_chips(timezone.localdate(), date_from, date_to),
        "filtered": bool(q or mill_id or status or date_from or date_to),
        "querystring": params.urlencode(),
        "count": page.paginator.count,
        **totals,
    })


@login_required
def purchase_detail(request, purchase_id):
    company = company_of(request)
    purchase = tenant_object_or_404(
        Purchase.objects.select_related("mill"), request, purchase_id
    )

    items = (
        PurchaseItem.objects
        .filter(purchase=purchase)
        .select_related("product")
        .order_by("id")
    )

    payments = (
        Payment.objects
        .filter(company=company, related_type="purchase", purchase=purchase)
        .order_by("-payment_date", "-id")
    )

    # A margin can be tried out from the page without saving anything.
    margin = request.GET.get("margin")
    try:
        margin = Decimal(margin) if margin else None
    except (InvalidOperation, TypeError):
        margin = None

    status = purchase_payment_status(company, purchase)

    # Where money that settled this bill came from, when it was not paid
    # against this bill directly - so the screen can explain the difference.
    from core.services.ledger import mill_statement

    statement = mill_statement(company, purchase.mill)
    extra_sources = [
        (bill, amount) for bill, amount in statement["overpaid_by_bill"]
        if bill is not None and bill.id != purchase.id
    ]

    return render(request, "core/purchase_detail.html", {
        "purchase": purchase,
        "items": items,
        "payments": payments,
        "paid": status["paid"],
        "due": status["due"],
        "direct_paid": status["direct_paid"],
        "entered_against_bill": status.get("entered_against_bill", status["direct_paid"]),
        "applied_from_account": status["applied_from_account"],
        "overpaid_sources": extra_sources,
        "on_account_total": statement["on_account"],
        "expenses": purchase.expenses.all(),
        "costing": purchase_costing(purchase, margin),
        "line_costs": line_costing(purchase, margin),
        "expense_categories": PurchaseExpense.CATEGORIES,
    })


@login_required
def add_purchase_expense(request, purchase_id):
    """Record something you paid for this bill after it was entered."""
    purchase = tenant_object_or_404(Purchase, request, purchase_id)

    if request.method == "POST":
        try:
            amount = Decimal(request.POST.get("amount") or 0)
        except (InvalidOperation, TypeError):
            amount = Decimal(0)

        if amount <= 0:
            messages.error(request, _("Enter how much you spent."))
        else:
            PurchaseExpense.objects.create(
                purchase=purchase,
                category=request.POST.get("category") or PurchaseExpense.OTHER,
                amount=amount,
                paid_to=request.POST.get("paid_to", "")[:150],
                payment_mode=request.POST.get("payment_mode", "")[:50],
                expense_date=request.POST.get("expense_date") or purchase.purchase_date,
                notes=request.POST.get("notes", "")[:200],
            )
            messages.success(request, _("Expense of ₹ %(amount)s added to this bill.") % {"amount": amount})

    return redirect("purchase_detail", purchase_id=purchase.id)


@login_required
@manager_required
def delete_purchase_expense(request, purchase_id, expense_id):
    """Remove an expense line from a bill."""
    purchase = tenant_object_or_404(Purchase, request, purchase_id)

    if request.method == "POST":
        expense = get_object_or_404(PurchaseExpense, id=expense_id, purchase=purchase)
        expense.delete()
        messages.success(request, _("Expense removed."))

    return redirect("purchase_detail", purchase_id=purchase.id)


@login_required
@manager_required
def delete_purchase(request, purchase_id):
    """
    Deleting a bill removes its stock as well, so it is only allowed while no
    payment has been recorded against it.
    """
    purchase = tenant_object_or_404(Purchase, request, purchase_id)

    payments = Payment.objects.filter(
        company=company_of(request), related_type="purchase", purchase=purchase
    )

    if request.method == "POST":
        if payments.exists():
            messages.error(
                request,
                _("This bill has payments recorded against it, so it cannot be deleted. "
                  "Delete the payments first, or edit the bill instead."),
            )
            return redirect("purchase_detail", purchase_id=purchase.id)

        ref = purchase.purchase_ref or purchase.invoice_no
        purchase.delete()
        messages.success(request, _("Purchase %(ref)s deleted, along with its stock lines.") % {"ref": ref})
        return redirect("purchase_list")

    return render(request, "core/delete_purchase.html", {
        "purchase": purchase,
        "items": PurchaseItem.objects.filter(purchase=purchase).select_related("product"),
        "payment_count": payments.count(),
        "can_delete": not payments.exists(),
    })
