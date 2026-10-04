"""
Truck register - every sale truck from mill to party in one table, with the
money on both sides and the profit, filterable and downloadable as Excel.
"""

from datetime import date, timedelta

from django.utils import timezone
from django.utils.translation import gettext as _

from core.models import Broker, Customer, Mill, Sale
from core.services.trade_register import STATUS_LABELS, group_summary, register_excel, register_rows, register_totals
from core.tenancy import company_of

from ..base_imports import *


def _parse(value):
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


@login_required
def trade_register(request):
    company = company_of(request)
    today = timezone.localdate()

    default_from = today - timedelta(days=90)
    date_from = _parse(request.GET.get("from")) or default_from
    date_to = _parse(request.GET.get("to")) or today
    if date_from > date_to:
        date_from, date_to = date_to, date_from
    customer_id = request.GET.get("customer", "")
    broker_id = request.GET.get("broker", "")
    mill_id = request.GET.get("mill", "")
    status = request.GET.get("status", "")

    sales = Sale.objects.for_company(company).filter(sale_date__range=(date_from, date_to))
    if customer_id.isdigit():
        sales = sales.filter(customer_id=int(customer_id))
    if broker_id.isdigit():
        sales = sales.filter(broker_id=int(broker_id))
    if mill_id.isdigit():
        sales = sales.filter(lots__mill_id=int(mill_id)).distinct()

    rows = register_rows(company, sales)
    if status in STATUS_LABELS:
        rows = [row for row in rows if row["status"] == status]
    # Newest truck on top: today's bill first.
    rows.sort(key=lambda row: (row["sale"].sale_date, row["sale"].id), reverse=True)
    totals = register_totals(rows)

    # Quick period buttons
    month_start = today.replace(day=1)
    last_month_end = month_start - timedelta(days=1)
    first_sale = Sale.objects.for_company(company).order_by("sale_date").values_list("sale_date", flat=True).first()
    periods = [
        (_("Today"), today, today),
        (_("This month"), month_start, today),
        (_("Last month"), last_month_end.replace(day=1), last_month_end),
        (_("Last 3 months"), default_from, today),
        (_("This year"), today.replace(month=1, day=1), today),
        (_("All time"), min(first_sale or today, today), today),
    ]
    periods = [
        {"label": label, "from": start, "to": end, "active": (start, end) == (date_from, date_to)}
        for label, start, end in periods
    ]
    filtered = any([customer_id, broker_id, mill_id, status]) or (date_from, date_to) != (default_from, today)

    title = _("Truck register %(start)s to %(end)s") % {
        "start": date_from.strftime("%d %b %Y"), "end": date_to.strftime("%d %b %Y"),
    }

    if request.GET.get("export") == "xlsx":
        return register_excel(company, rows, totals, title)

    params = request.GET.copy()
    params["export"] = "xlsx"

    return render(request, "core/trade_register.html", {
        "rows": rows,
        "totals": totals,
        "group_tables": [
            (_("Profit by broker"), "🤝", group_summary(rows, "broker"), "broker"),
            (_("Profit by customer"), "👥", group_summary(rows, "customer"), "customer"),
        ],
        "title": title,
        "date_from": date_from,
        "date_to": date_to,
        "customer_id": customer_id,
        "broker_id": broker_id,
        "mill_id": mill_id,
        "status": status,
        "statuses": STATUS_LABELS.items(),
        "customers": Customer.objects.for_company(company).order_by("customer_name"),
        "brokers": Broker.objects.for_company(company).order_by("broker_name"),
        "mills": Mill.objects.for_company(company).order_by("mill_name"),
        "export_query": params.urlencode(),
        "periods": periods,
        "filtered": filtered,
    })
