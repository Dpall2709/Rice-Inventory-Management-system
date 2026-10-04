"""
Supplier list: search, filter, sort, paginate, and show what you owe each mill.

The balance every row shows is:

    opening balance  +  everything purchased  -  everything paid

Those two sums are fetched with subqueries, so the page runs a fixed number of
queries no matter how many suppliers there are.
"""

from django.core.paginator import Paginator
from django.db.models import Count, DecimalField, F, OuterRef, Q, Subquery, Sum, Value
from django.db.models.functions import Coalesce

from core.models import Mill, Payment, Purchase
from core.tenancy import company_of

from ..base_imports import *

SORT_FIELDS = {
    "name": "mill_name",
    "-name": "-mill_name",
    "balance": "balance",
    "-balance": "-balance",
    "purchased": "purchased",
    "-purchased": "-purchased",
    "new": "-created_at",
    "old": "created_at",
}

money = DecimalField(max_digits=14, decimal_places=2)


def mill_queryset(company):
    """Suppliers of this company, each annotated with its money figures."""

    purchased = (
        Purchase.objects
        .filter(company=company, mill=OuterRef("pk"))
        .values("mill")
        .annotate(total=Sum("total_amount"))
        .values("total")[:1]
    )

    paid = (
        Payment.objects
        .filter(company=company, related_type="purchase", mill=OuterRef("pk"))
        .values("mill")
        .annotate(total=Sum("amount"))
        .values("total")[:1]
    )

    bills = (
        Purchase.objects
        .filter(company=company, mill=OuterRef("pk"))
        .values("mill")
        .annotate(n=Count("id"))
        .values("n")[:1]
    )
    last_bill = (
        Purchase.objects
        .filter(company=company, mill=OuterRef("pk"))
        .order_by("-purchase_date")
        .values("purchase_date")[:1]
    )

    zero = Value(0, output_field=money)

    return (
        Mill.objects
        .for_company(company)
        .annotate(
            purchased=Coalesce(Subquery(purchased, output_field=money), zero),
            paid=Coalesce(Subquery(paid, output_field=money), zero),
            bill_count=Coalesce(Subquery(bills), Value(0)),
            last_bill=Subquery(last_bill),
        )
        .annotate(
            balance=F("opening_balance") + F("purchased") - F("paid"),
        )
    )


@login_required
def mill_list(request):
    company = company_of(request)

    q = request.GET.get("q", "").strip()
    status = request.GET.get("status", "active")
    sort = request.GET.get("sort", "name")
    balance = request.GET.get("balance", "")

    mills = mill_queryset(company)

    if status == "active":
        mills = mills.filter(is_active=True)
    elif status == "inactive":
        mills = mills.filter(is_active=False)

    if q:
        mills = mills.filter(
            Q(mill_name__icontains=q)
            | Q(owner_name__icontains=q)
            | Q(mobile__icontains=q)
            | Q(gst_number__icontains=q)
            | Q(city__icontains=q)
        )

    if balance == "owe":
        mills = mills.filter(balance__gt=0)
    elif balance == "settled":
        mills = mills.filter(balance=0)
    elif balance == "advance":
        mills = mills.filter(balance__lt=0)

    mills = mills.order_by(SORT_FIELDS.get(sort, "mill_name"))

    # Totals for the tiles, over everything the filter matched (not just page 1).
    totals = mills.aggregate(
        total_purchased=Coalesce(Sum("purchased"), Value(0, output_field=money)),
        total_paid=Coalesce(Sum("paid"), Value(0, output_field=money)),
        total_opening=Coalesce(Sum("opening_balance"), Value(0, output_field=money)),
    )
    outstanding = (
        totals["total_opening"] + totals["total_purchased"] - totals["total_paid"]
    )

    page = Paginator(mills, 25).get_page(request.GET.get("page"))
    for mill in page.object_list:
        owed_in_all = mill.opening_balance + mill.purchased
        mill.paid_percent = min(int(mill.paid * 100 / owed_in_all), 100) if owed_in_all > 0 else 100

    # Keeps the search and sort when moving between pages.
    params = request.GET.copy()
    params.pop("page", None)

    return render(request, "core/mill_list.html", {
        "page_obj": page,
        "mills": page.object_list,
        "q": q,
        "status": status,
        "sort": sort,
        "balance": balance,
        "filtered": bool(q or balance or status != "active" or sort != "name"),
        "owe_count": mill_queryset(company).filter(balance__gt=0).count(),
        "querystring": params.urlencode(),
        "total_count": page.paginator.count,
        "active_count": mill_queryset(company).filter(is_active=True).count(),
        "inactive_count": mill_queryset(company).filter(is_active=False).count(),
        "total_purchased": totals["total_purchased"],
        "total_paid": totals["total_paid"],
        "outstanding": outstanding,
    })
