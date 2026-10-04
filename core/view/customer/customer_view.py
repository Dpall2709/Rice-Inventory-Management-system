from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django.shortcuts import (
    get_object_or_404,
    redirect,
    render
)
from django.urls import reverse

from core.models import Customer
from core.forms import CustomerForm
from core.permissions import manager_required
from core.services.customer_ledger import customer_balances, customer_statement
from core.tenancy import company_of, tenant_object_or_404

# How the customer form is grouped on screen.
FORM_SECTIONS = [
    (gettext_lazy("Customer"), "customer_name,mobile,email"),
    (gettext_lazy("Tax"), "gst_number"),
    (gettext_lazy("Address"), "billing_address,shipping_address,city,state,country,pincode"),
    (gettext_lazy("Balance & discount"), "opening_balance,default_cash_discount_percent"),
]


@login_required
def customer_list(request):

    company = request.user.userprofile.company

    q = request.GET.get("q", "").strip()

    customers = Customer.objects.filter(
        company=company,
        is_active=True
    ).order_by("-created_at")

    if q:
        customers = customers.filter(
            Q(customer_name__icontains=q) |
            Q(mobile__icontains=q) |
            Q(gst_number__icontains=q)
        )

    customers = list(customers)
    balances = customer_balances(company, customers)
    for customer in customers:
        customer.balance_due = balances.get(customer.id, 0)

    return render(
        request,
        "core/customer_list.html",
        {
            "customers": customers,
            "q": q,
            "total_receivable": sum((c.balance_due for c in customers), 0),
        }
    )


@login_required
def add_customer(request):

    company = request.user.userprofile.company

    if request.method == "POST":

        form = CustomerForm(request.POST)

        if form.is_valid():

            customer = form.save(commit=False)

            customer.company = company

            customer.save()

            messages.success(
                request,
                "✅ " + _("Customer saved successfully!")
            )

            # Added from the sale screen: go straight back to it, with this
            # customer already chosen.
            if request.POST.get("next") == "sale":
                return redirect(f"{reverse('add_sale')}?customer={customer.id}")

            return redirect("customer_ledger", customer_id=customer.id)

    else:

        form = CustomerForm()

    return render(
        request,
        "core/customer_form.html",
        {
            "form": form,
            "mode": "add",
            "sections": FORM_SECTIONS,
            "next": request.GET.get("next") or request.POST.get("next", ""),
        }
    )


@login_required
def edit_customer(request, customer_id):

    company = request.user.userprofile.company

    customer = get_object_or_404(
        Customer,
        id=customer_id,
        company=company
    )

    if request.method == "POST":

        form = CustomerForm(
            request.POST,
            instance=customer
        )

        if form.is_valid():

            form.save()

            messages.success(
                request,
                "✅ " + _("Customer updated successfully!")
            )

            return redirect("customer_list")

    else:

        form = CustomerForm(
            instance=customer
        )

    return render(
        request,
        "core/customer_form.html",
        {
            "form": form,
            "customer": customer,
            "mode": "edit",
            "sections": FORM_SECTIONS,
        }
    )


@login_required
@manager_required
def delete_customer(request, customer_id):

    company = request.user.userprofile.company

    customer = get_object_or_404(
        Customer,
        id=customer_id,
        company=company
    )

    if request.method == "POST":

        customer.is_active = False
        customer.save()

        messages.success(
            request,
            "🗑 " + _("Customer deactivated successfully!")
        )

        return redirect("customer_list")

    return render(
        request,
        "core/delete_customer.html",
        {
            "customer": customer
        }
    )

@login_required
def customer_ledger(request, customer_id):
    """
    One customer's account: every invoice with what is paid and due, every
    receipt, and the running balance - the khata for this buyer.
    """
    company = company_of(request)
    customer = tenant_object_or_404(Customer, request, customer_id)
    statement = customer_statement(company, customer)

    # Profit on everything this customer bought, direct or through a broker.
    from decimal import Decimal

    from core.models import Sale
    from core.services.trade_register import register_rows

    rows = {r["sale"].id: r for r in register_rows(company, Sale.objects.for_company(company).filter(customer=customer))}
    profit_total = profit_earned = Decimal("0")
    for sale in [row["sale"] for row in statement["rows"]] + statement["broker_sales"]:
        row = rows.get(sale.id)
        sale.profit = row["profit"] if row else None
        sale.profit_earned = row["profit_earned"] if row else None
        sale.profit_pending = row["profit_pending"] if row else None
        if sale.profit is not None:
            profit_total += sale.profit
            profit_earned += sale.profit_earned

    return render(request, "core/customer_ledger.html", {
        "profit_total": profit_total,
        "profit_earned": profit_earned,
        "broker_sales": list(reversed(statement["broker_sales"])),
        "customer": customer,
        "statement": statement,
        "rows": list(reversed(statement["rows"])),
        "history": statement["history"],
        "overdue_count": sum(1 for row in statement["rows"] if row["overdue"]),
    })
