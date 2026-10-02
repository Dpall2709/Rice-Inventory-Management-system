"""
Brokers: the people who bring buyers, and the commission you owe them.

A broker is never deleted once he has sales or payments - he is deactivated,
so his history and his commission ledger stay intact.
"""

from django.db.models import Count, Q, Sum
from django.utils import timezone
from django.utils.translation import gettext as _

from core.forms import BrokerForm, ReceiptForm
from core.models import Broker, Payment
from core.permissions import manager_required
from core.services.customer_ledger import broker_statement
from core.tenancy import company_of, tenant_object_or_404

from ..base_imports import *


@login_required
def broker_list(request):
    company = company_of(request)

    q = request.GET.get("q", "").strip()
    show = request.GET.get("show", "active")

    brokers = Broker.objects.for_company(company).annotate(
        sale_count=Count("sale", distinct=True),
    ).order_by("broker_name")

    if show == "inactive":
        brokers = brokers.filter(is_active=False)
    elif show != "all":
        brokers = brokers.filter(is_active=True)

    if q:
        brokers = brokers.filter(
            Q(broker_name__icontains=q) | Q(mobile__icontains=q) | Q(city__icontains=q)
        )

    brokers = list(brokers)
    for broker in brokers:
        statement = broker_statement(company, broker)
        broker.owed = statement["owed"]
        broker.owes_us = statement["broker_owes_us"]
        broker.earned = statement["earned"]
        broker.total_bags = statement["total_bags"]

    return render(request, "core/broker_list.html", {
        "brokers": brokers,
        "q": q,
        "show": show,
        "total_owed": sum((b.owed for b in brokers), 0),
        "total_owes_us": sum((b.owes_us for b in brokers), 0),
        "inactive_count": Broker.objects.for_company(company).filter(is_active=False).count(),
    })


@login_required
def add_broker(request):
    company = company_of(request)

    if request.method == "POST":
        form = BrokerForm(request.POST, company=company)
        if form.is_valid():
            broker = form.save(commit=False)
            broker.company = company
            broker.save()
            messages.success(request, _("Broker %(name)s saved.") % {"name": broker.broker_name})
            return redirect("broker_report_detail", broker_id=broker.id)
    else:
        form = BrokerForm(company=company)

    return render(request, "core/broker_form.html", {"form": form, "mode": "add"})


@login_required
@manager_required
def edit_broker(request, broker_id):
    company = company_of(request)
    broker = tenant_object_or_404(Broker, request, broker_id)

    if request.method == "POST":
        form = BrokerForm(request.POST, instance=broker, company=company)
        if form.is_valid():
            form.save()
            messages.success(request, _("Broker %(name)s updated.") % {"name": broker.broker_name})
            return redirect("broker_report_detail", broker_id=broker.id)
    else:
        form = BrokerForm(instance=broker, company=company)

    return render(request, "core/broker_form.html", {"form": form, "mode": "edit", "broker": broker})


@login_required
@manager_required
def toggle_broker(request, broker_id):
    """Deactivate a broker (hidden from new sales, history kept) or bring him back."""
    broker = tenant_object_or_404(Broker, request, broker_id)

    if request.method == "POST":
        broker.is_active = not broker.is_active
        broker.save(update_fields=["is_active", "updated_at"])
        if broker.is_active:
            messages.success(request, _("%(name)s is active again.") % {"name": broker.broker_name})
        else:
            messages.success(
                request,
                _("%(name)s is deactivated. His sales and ledger are kept.") % {"name": broker.broker_name},
            )

    return redirect("broker_report_detail", broker_id=broker.id)


@login_required
def broker_report_detail(request, broker_id):
    company = company_of(request)
    broker = tenant_object_or_404(Broker, request, broker_id)
    statement = broker_statement(company, broker)

    # Profit on every truck he brought - for judging which broker deals pay.
    from decimal import Decimal

    from core.services.sale_service import sale_profit

    profit_total = Decimal("0")
    profit_known = 0
    for sale in statement["sales"]:
        sale.profit = sale_profit(sale)["profit"]
        if sale.profit is not None:
            profit_total += sale.profit
            profit_known += 1

    return render(request, "core/broker_report_detail.html", {
        "broker": broker,
        "statement": statement,
        "collections": statement["collections"],
        "collection_rows": list(reversed(statement["collections"]["rows"])),
        "sales": statement["sales"],
        "history": statement["history"],
        "profit_total": profit_total,
        "profit_known": profit_known,
    })


@login_required
def add_broker_payment(request, broker_id):
    """Commission paid to the broker."""
    company = company_of(request)
    broker = tenant_object_or_404(Broker, request, broker_id)
    statement = broker_statement(company, broker)

    if request.method == "POST":
        form = ReceiptForm(request.POST)
        if form.is_valid():
            data = form.cleaned_data
            Payment.objects.create(
                company=company,
                related_type="broker",
                broker=broker,
                amount=data["amount"],
                payment_mode=data["payment_mode"],
                payment_date=data["payment_date"],
                notes=data["notes"],
            )
            messages.success(
                request,
                _("₹ %(amount)s commission paid to %(name)s.") % {
                    "amount": data["amount"], "name": broker.broker_name,
                },
            )
            return redirect("broker_report_detail", broker_id=broker.id)
    else:
        form = ReceiptForm(initial={
            "amount": statement["owed"] if statement["owed"] > 0 else None,
            "payment_date": timezone.localdate(),
            "payment_mode": "Cash",
        })

    return render(request, "core/receipt_form.html", {
        "form": form,
        "broker": broker,
        "due": statement["owed"],
        "kind": "broker",
    })


@login_required
def add_broker_receipt(request, broker_id):
    """Money the broker paid you for trucks he collected on (applied oldest first)."""
    from core.services.customer_ledger import broker_collections

    company = company_of(request)
    broker = tenant_object_or_404(Broker, request, broker_id)
    collections = broker_collections(company, broker)

    if request.method == "POST":
        form = ReceiptForm(request.POST)
        if form.is_valid():
            data = form.cleaned_data
            Payment.objects.create(
                company=company,
                related_type="sale",
                broker=broker,
                amount=data["amount"],
                payment_mode=data["payment_mode"],
                payment_date=data["payment_date"],
                notes=data["notes"],
            )
            messages.success(
                request,
                _("₹ %(amount)s received from %(name)s. It is applied to his oldest unpaid trucks first.") % {
                    "amount": data["amount"], "name": broker.broker_name,
                },
            )
            return redirect("broker_report_detail", broker_id=broker.id)
    else:
        form = ReceiptForm(initial={
            "amount": collections["total_due"] if collections["total_due"] > 0 else None,
            "payment_date": timezone.localdate(),
            "payment_mode": "Bank",
        })

    return render(request, "core/receipt_form.html", {
        "form": form,
        "broker": broker,
        "due": collections["total_due"],
        "kind": "broker_receipt",
    })
