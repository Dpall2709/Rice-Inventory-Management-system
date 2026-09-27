"""
Purchase list and purchase detail.
"""

from django.core.paginator import Paginator
from django.db.models import DecimalField, F, OuterRef, Q, Subquery, Sum, Value
from django.db.models.functions import Coalesce

from decimal import Decimal, InvalidOperation

from django.shortcuts import get_object_or_404

from core.models import Mill, Payment, Purchase, PurchaseExpense, PurchaseItem
from core.services.costing import line_costing, purchase_costing
from core.services.ledger import paid_map_for_purchases, purchase_payment_status
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
    date_from = request.GET.get("from", "")
    date_to = request.GET.get("to", "")

    paid = (
        Payment.objects
        .filter(company=company, related_type="purchase", purchase=OuterRef("pk"))
        .values("purchase")
        .annotate(total=Sum("amount"))
        .values("total")[:1]
    )

    zero = Value(0, output_field=money)

    purchases = (
        Purchase.objects
        .for_company(company)
        .select_related("mill")
        .annotate(
            paid=Coalesce(Subquery(paid, output_field=money), zero),
            bags=Coalesce(Sum("purchaseitem__bag_count"), Value(0)),
        )
        .annotate(due=F("total_amount") - F("paid"))
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

    if status == "due":
        purchases = purchases.filter(due__gt=0)
    elif status == "paid":
        purchases = purchases.filter(due__lte=0)

    totals = purchases.aggregate(
        total_value=Coalesce(Sum("total_amount"), zero),
        total_paid=Coalesce(Sum("paid"), zero),
        total_tax=Coalesce(
            Sum(F("cgst_amount") + F("sgst_amount") + F("igst_amount")), zero
        ),
    )
    totals["total_due"] = totals["total_value"] - totals["total_paid"]

    page = Paginator(purchases.order_by("-purchase_date", "-id"), 25).get_page(
        request.GET.get("page")
    )

    # Payments made to a mill without naming a bill still count. This applies
    # them the same way the supplier ledger does, so both screens agree.
    settled = paid_map_for_purchases(company, page.object_list)
    for purchase in page.object_list:
        row = settled.get(purchase.id)
        if row:
            purchase.paid = row["paid"]
            purchase.due = row["due"]
            purchase.applied_from_account = row["applied_from_account"]

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
            messages.error(request, "Enter how much you spent.")
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
            messages.success(request, f"Expense of ₹ {amount} added to this bill.")

    return redirect("purchase_detail", purchase_id=purchase.id)


@login_required
@manager_required
def delete_purchase_expense(request, purchase_id, expense_id):
    """Remove an expense line from a bill."""
    purchase = tenant_object_or_404(Purchase, request, purchase_id)

    if request.method == "POST":
        expense = get_object_or_404(PurchaseExpense, id=expense_id, purchase=purchase)
        expense.delete()
        messages.success(request, "Expense removed.")

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
                "This bill has payments recorded against it, so it cannot be deleted. "
                "Delete the payments first, or edit the bill instead.",
            )
            return redirect("purchase_detail", purchase_id=purchase.id)

        ref = purchase.purchase_ref or purchase.invoice_no
        purchase.delete()
        messages.success(request, f"Purchase {ref} deleted, along with its stock lines.")
        return redirect("purchase_list")

    return render(request, "core/delete_purchase.html", {
        "purchase": purchase,
        "items": PurchaseItem.objects.filter(purchase=purchase).select_related("product"),
        "payment_count": payments.count(),
        "can_delete": not payments.exists(),
    })
