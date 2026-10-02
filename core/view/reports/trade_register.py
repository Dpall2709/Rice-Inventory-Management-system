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

    date_from = _parse(request.GET.get("from")) or (today - timedelta(days=90))
    date_to = _parse(request.GET.get("to")) or today
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
    totals = register_totals(rows)

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
        "by_broker": group_summary(rows, "broker"),
        "by_customer": group_summary(rows, "customer"),
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
    })
