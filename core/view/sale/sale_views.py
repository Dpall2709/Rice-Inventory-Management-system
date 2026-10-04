"""
Selling: the sale list, the invoice entry screen, the invoice page, and money
received from customers.

A sale is always made to a Customer from the customer master, so every rupee
billed shows up in that customer's ledger. The buyer's name, GST number and
addresses are copied onto the sale when it is saved, so a later change to the
customer never rewrites an invoice that was already given.
"""

from decimal import Decimal

from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _

from core.forms import ReceiptForm, SaleForm, SaleItemFormSet
from core.models import Broker, Customer, Payment, Product, Sale
from core.permissions import manager_required
from core.services.costing import product_costing
from core.services.invoice_number import next_sale_invoice_no
from core.services.customer_ledger import (
    customer_statement,
    sale_payment_status,
    status_map_for_sales,
)
from core.services.sale_service import (
    StockError,
    sale_profit,
    earned_profit,
    payment_status,
    save_sale,
    stock_lots,
    product_stock,
    suggested_tax_type,
)
from core.services.periods import date_range, period_chips
from core.services.trade_register import register_rows
from core.tenancy import company_of, tenant_object_or_404

from ..base_imports import *


# --------------------------------------------------------------------------
# List
# --------------------------------------------------------------------------

@login_required
def sale_list(request):
    company = company_of(request)

    q = request.GET.get("q", "").strip()
    customer_id = request.GET.get("customer", "")
    broker_id = request.GET.get("broker", "")
    status = request.GET.get("status", "")
    date_from, date_to = date_range(request.GET)

    sales = (
        Sale.objects
        .for_company(company)
        .select_related("customer", "broker")
        .order_by("-sale_date", "-id")
    )

    if q:
        sales = sales.filter(
            Q(invoice_no__icontains=q)
            | Q(customer_name__icontains=q)
            | Q(broker__broker_name__icontains=q)
            | Q(vehicle_number__icontains=q)
        )
    if customer_id.isdigit():
        sales = sales.filter(customer_id=int(customer_id))
    if broker_id.isdigit():
        sales = sales.filter(broker_id=int(broker_id))
    if date_from:
        sales = sales.filter(sale_date__gte=date_from)
    if date_to:
        sales = sales.filter(sale_date__lte=date_to)

    # Money, cost and profit come from the truck register rows, so this list,
    # the register, the party pages and the dashboard always agree.
    register = {row["sale"].id: row for row in register_rows(company, sales)}
    settled = status_map_for_sales(company, list(sales))
    sales = list(sales)
    for sale in sales:
        row = register[sale.id]
        sale.paid = row["received"]
        sale.due = row["due"]
        sale.party_owes = row["net_receivable"]
        sale.cost = row["total_cost"]
        sale.profit = row["profit"]
        sale.profit_earned = row["profit_earned"]
        sale.profit_pending = row["profit_pending"]
        sale.status = row["payment_status"]
        sale.overdue = (settled.get(sale.id) or {}).get("overdue", False)
        sale.paid_percent = row["paid_percent"]
        sale.unloaded = bool(sale.unload_date)

    if status == "due":
        sales = [s for s in sales if s.due > 0]
    elif status == "partial":
        sales = [s for s in sales if s.status == "partial"]
    elif status == "overdue":
        sales = [s for s in sales if s.overdue]
    elif status == "paid":
        sales = [s for s in sales if s.due <= 0]

    totals = {
        "total_value": sum((s.total_amount for s in sales), Decimal("0")),
        "total_received": sum((s.paid for s in sales), Decimal("0")),
        "total_due": sum((s.due for s in sales), Decimal("0")),
        "total_bags": sum((int(s.total_bags or 0) for s in sales)),
        "total_tax": sum((s.gst_amount or 0 for s in sales), Decimal("0")),
        "total_cost": sum((s.cost for s in sales if s.profit is not None), Decimal("0")),
        "total_profit_earned": sum((s.profit_earned for s in sales if s.profit is not None), Decimal("0")),
        "total_profit": sum((s.profit for s in sales if s.profit is not None), Decimal("0")),
        "bills_paid": sum(1 for s in sales if s.status == "paid"),
        "bills_partial": sum(1 for s in sales if s.status == "partial"),
        "bills_due": sum(1 for s in sales if s.status == "due"),
        "bills_overdue": sum(1 for s in sales if s.overdue),
    }

    page = Paginator(sales, 25).get_page(request.GET.get("page"))

    params = request.GET.copy()
    params.pop("page", None)

    return render(request, "core/sale_list.html", {
        "page_obj": page,
        "sales": page.object_list,
        "customers": Customer.objects.for_company(company).order_by("customer_name"),
        "brokers": Broker.objects.for_company(company).order_by("broker_name"),
        "q": q,
        "customer_id": customer_id,
        "broker_id": broker_id,
        "status": status,
        "date_from": date_from,
        "date_to": date_to,
        "periods": period_chips(timezone.localdate(), date_from, date_to),
        "filtered": bool(q or customer_id or broker_id or status or date_from or date_to),
        "querystring": params.urlencode(),
        "count": page.paginator.count,
        **totals,
    })


# --------------------------------------------------------------------------
# Entry screen
# --------------------------------------------------------------------------

def _form_data(company, sale=None):
    """
    Everything the entry screen needs to fill fields in as the user types,
    handed to the page with json_script.
    """
    customers = {}
    for customer in Customer.objects.for_company(company):
        customers[str(customer.id)] = {
            "name": customer.customer_name,
            "gst": customer.gst_number,
            "mobile": customer.mobile,
            "state": customer.state,
            "address": customer.full_billing_address,
            "shipping": customer.full_shipping_address,
            "tax_type": suggested_tax_type(company, customer),
            "cd": float(customer.default_cash_discount_percent or 0),
        }

    brokers = {
        str(broker.id): {
            "type": broker.commission_type,
            "rate": float(broker.commission_rate or 0),
            "cd": float(broker.default_cash_discount_percent or 0),
        }
        for broker in Broker.objects.for_company(company)
    }

    stock = product_stock(company, exclude_sale=sale)
    products = {}
    for product in Product.objects.for_company(company):
        costing = product_costing(company, product)
        products[str(product.id)] = {
            "name": product.rice_name,
            "gst": float(product.gst_percent or 0),
            "hsn": product.hsn_code or "",
            "cost_per_kg": float(costing["cost_per_kg"]),
            "suggested_per_kg": float(costing["suggested_per_kg"]),
            "stock": {
                str(weight): bags
                for (product_id, weight), bags in stock.items()
                if product_id == product.id
            },
        }

    lots = {
        str(lot.id): {
            "product": lot.product_id,
            "bag_weight": lot.bag_weight,
            "left": lot.bags_left,
            "mill": lot.purchase.mill.mill_name,
            "date": f"{lot.purchase.purchase_date:%d %b %Y}",
            "rate": float(lot.purchase_price or 0),
            "bill": lot.purchase.invoice_no,
            # e.g. "Piyush Rice Mill · 02 Oct 2026 · ₹30.00/kg · 500 bags left (bill 245)"
            "label": f"{lot.purchase.mill.mill_name} · {lot.purchase.purchase_date:%d %b %Y} · "
                     f"₹{lot.purchase_price}/kg · {lot.bags_left} bags left (bill {lot.purchase.invoice_no})",
        }
        for lot in stock_lots(company, exclude_sale=sale)
    }

    return {
        "loading_rate": float(company.default_loading_rate_per_kg or 0),
        "customers": customers,
        "brokers": brokers,
        "products": products,
        "lots": lots,
    }


def _apply_customer(sale, customer):
    """Copy the buyer's details onto the invoice as they are today."""
    sale.customer = customer
    sale.customer_name = customer.customer_name
    sale.customer_gst = (customer.gst_number or "").upper()
    sale.billing_address = customer.full_billing_address
    sale.shipping_address = customer.full_shipping_address
    sale.place_of_supply = customer.state or ""


def _render_form(request, company, form, formset, mode, sale=None, stock_errors=None):
    return render(request, "core/sale_form.html", {
        "form": form,
        "formset": formset,
        "mode": mode,
        "sale": sale,
        "stock_errors": stock_errors or [],
        "form_data": _form_data(company, sale),
        "has_customers": Customer.objects.for_company(company).filter(is_active=True).exists(),
        "has_stock": bool(stock_lots(company, exclude_sale=sale)),
    })


def _save(company, form, formset, mode):
    """Shared by add and edit. Returns (sale, None), or (None, stock errors)."""
    sale = form.save(commit=False)
    _apply_customer(sale, form.cleaned_data["customer"])

    items = formset.filled_items()

    try:
        if mode == "add":
            # The number is taken inside the same transaction, so a sale that
            # fails the stock check does not burn an invoice number.
            with transaction.atomic():
                sale.invoice_no = next_sale_invoice_no(company)
                save_sale(sale, items, company)
        else:
            save_sale(sale, items, company)
    except StockError as error:
        return None, error.messages

    return sale, None


@login_required
def add_sale(request):
    company = company_of(request)

    if request.method == "POST":
        form = SaleForm(request.POST, company=company)
        formset = SaleItemFormSet(request.POST, form_kwargs={"company": company})

        if form.is_valid() and formset.is_valid():
            sale, stock_errors = _save(company, form, formset, "add")

            if sale is not None:
                messages.success(
                    request,
                    _("Invoice %(no)s saved · %(bags)s bags · ₹ %(total)s") % {
                        "no": sale.invoice_no, "bags": sale.total_bags, "total": sale.total_amount,
                    },
                )
                if request.POST.get("save_and_new"):
                    return redirect("add_sale")
                return redirect("sale_detail", sale_id=sale.id)

            return _render_form(request, company, form, formset, "add", stock_errors=stock_errors)
    else:
        initial = {"sale_date": timezone.localdate(), "tax_type": Sale.CGST_SGST}

        # "New sale" from a customer's page arrives with ?customer=<id>.
        customer_id = request.GET.get("customer", "")
        if customer_id.isdigit():
            customer = Customer.objects.for_company(company).filter(id=int(customer_id)).first()
            if customer:
                initial["customer"] = customer.id
                initial["tax_type"] = suggested_tax_type(company, customer)
                initial["cash_discount_percent"] = customer.default_cash_discount_percent

        form = SaleForm(company=company, initial=initial)
        formset = SaleItemFormSet(form_kwargs={"company": company})

    return _render_form(request, company, form, formset, "add")


@login_required
@manager_required
def edit_sale(request, sale_id):
    company = company_of(request)
    sale = tenant_object_or_404(Sale, request, sale_id)

    if request.method == "POST":
        form = SaleForm(request.POST, instance=sale, company=company)
        formset = SaleItemFormSet(request.POST, instance=sale, form_kwargs={"company": company})

        if form.is_valid() and formset.is_valid():
            saved, stock_errors = _save(company, form, formset, "edit")

            if saved is not None:
                messages.success(request, _("Invoice %(no)s updated.") % {"no": saved.invoice_no})
                return redirect("sale_detail", sale_id=saved.id)

            return _render_form(request, company, form, formset, "edit", sale=sale, stock_errors=stock_errors)
    else:
        form = SaleForm(instance=sale, company=company)
        formset = SaleItemFormSet(instance=sale, form_kwargs={"company": company})

    return _render_form(request, company, form, formset, "edit", sale=sale)


# --------------------------------------------------------------------------
# Invoice page
# --------------------------------------------------------------------------

@login_required
def sale_detail(request, sale_id):
    company = company_of(request)
    sale = tenant_object_or_404(
        Sale.objects.select_related("customer", "broker"), request, sale_id
    )

    items = list(sale.items.select_related("product", "mill"))
    status = sale_payment_status(company, sale)

    payments = (
        Payment.objects
        .filter(company=company, related_type="sale", sale=sale)
        .order_by("-payment_date", "-id")
    )

    profit = sale_profit(sale)
    # Same rule as the truck register: profit counts as earned only as the
    # money comes in.
    profit["sale_amount"] = profit["settlement"]["net_receivable"]
    profit["earned"], profit["pending"] = earned_profit(profit["profit"], profit["sale_amount"], status["paid"])
    profit["payment_status"] = payment_status(status["paid"], status["due"])

    share_text = _(
        "Invoice %(no)s dated %(date)s\n%(bags)s bags · ₹ %(total)s\nBalance due: ₹ %(due)s\n- %(company)s"
    ) % {
        "no": sale.invoice_no,
        "date": sale.sale_date.strftime("%d %b %Y"),
        "bags": sale.total_bags,
        "total": sale.total_amount,
        "due": status["due"],
        "company": company.company_name,
    }

    return render(request, "core/sale_detail.html", {
        "sale": sale,
        "items": items,
        "status": status,
        "paid": status["paid"],
        "due": status["due"],
        "applied_from_account": status["applied_from_account"],
        "payments": payments,
        "profit": profit,
        "share_text": share_text,
    })


@login_required
def sale_print(request, sale_id):
    """
    Print the invoice exactly as the PDF looks: the page shows the invoice PDF
    and opens the browser's print dialog on it, so the printed copy and the
    downloaded copy are the same document.
    """
    sale = tenant_object_or_404(Sale, request, sale_id)

    return render(request, "core/sale_print.html", {
        "sale": sale,
        "pdf_url": reverse("sale_invoice_pdf", args=[sale.id]),
        "statement_url": reverse("sale_statement_pdf", args=[sale.id]) if sale.unload_date else "",
    })


@login_required
@manager_required
def delete_sale(request, sale_id):
    company = company_of(request)
    sale = tenant_object_or_404(Sale, request, sale_id)

    payment_count = Payment.objects.filter(company=company, related_type="sale", sale=sale).count()
    can_delete = payment_count == 0

    if request.method == "POST" and can_delete:
        invoice_no = sale.invoice_no
        sale.delete()
        messages.success(
            request,
            _("Invoice %(no)s deleted. Its bags are back in stock.") % {"no": invoice_no},
        )
        return redirect("sale_list")

    return render(request, "core/delete_sale.html", {
        "sale": sale,
        "items": sale.items.select_related("product"),
        "can_delete": can_delete,
        "payment_count": payment_count,
    })


# --------------------------------------------------------------------------
# Money received
# --------------------------------------------------------------------------

def _receipt_page(request, context):
    return render(request, "core/receipt_form.html", context)


@login_required
def add_sale_payment(request, sale_id):
    """Money received against one invoice."""
    company = company_of(request)
    sale = tenant_object_or_404(Sale.objects.select_related("customer"), request, sale_id)
    status = sale_payment_status(company, sale)

    if request.method == "POST":
        form = ReceiptForm(request.POST)
        if form.is_valid():
            data = form.cleaned_data
            from core.services.customer_ledger import collected_by_broker

            via_broker = collected_by_broker(sale)
            Payment.objects.create(
                company=company,
                related_type="sale",
                sale=sale,
                # On a broker truck the money comes from the broker and goes into
                # his account; on a direct sale it is the customer's.
                customer=None if via_broker else sale.customer,
                broker=sale.broker if via_broker else None,
                amount=data["amount"],
                payment_mode=data["payment_mode"],
                payment_date=data["payment_date"],
                notes=data["notes"],
            )

            extra = data["amount"] - status["due"]
            if extra > 0 and via_broker:
                messages.warning(
                    request,
                    _("Invoice %(no)s is settled. The extra ₹ %(extra)s is applied to %(broker)s's "
                      "other unpaid trucks (or kept as advance).") % {
                        "no": sale.invoice_no, "extra": extra, "broker": sale.broker.broker_name,
                    },
                )
            elif extra > 0 and sale.customer_id:
                messages.warning(
                    request,
                    _("Invoice %(no)s is settled. The extra ₹ %(extra)s is applied to %(customer)s's "
                      "other unpaid invoices (or kept as advance).") % {
                        "no": sale.invoice_no, "extra": extra, "customer": sale.customer_name,
                    },
                )
            else:
                messages.success(
                    request,
                    _("₹ %(amount)s received against invoice %(no)s.") % {
                        "amount": data["amount"], "no": sale.invoice_no,
                    },
                )
            return redirect("sale_detail", sale_id=sale.id)
    else:
        form = ReceiptForm(initial={
            "amount": status["due"] if status["due"] > 0 else None,
            "payment_date": timezone.localdate(),
            "payment_mode": "Cash",
        })

    from core.services.customer_ledger import collected_by_broker

    return _receipt_page(request, {
        "form": form,
        "sale": sale,
        "customer": sale.customer,
        "broker": sale.broker if collected_by_broker(sale) else None,
        "due": status["due"],
        "kind": "sale",
    })


@login_required
def add_customer_payment(request, customer_id):
    """Money received from a customer without naming an invoice."""
    company = company_of(request)
    customer = tenant_object_or_404(Customer, request, customer_id)
    statement = customer_statement(company, customer)

    if request.method == "POST":
        form = ReceiptForm(request.POST)
        if form.is_valid():
            data = form.cleaned_data
            Payment.objects.create(
                company=company,
                related_type="sale",
                customer=customer,
                amount=data["amount"],
                payment_mode=data["payment_mode"],
                payment_date=data["payment_date"],
                notes=data["notes"],
            )

            extra = data["amount"] - statement["total_due"]
            if extra > 0:
                messages.warning(
                    request,
                    _("₹ %(amount)s saved. That is ₹ %(extra)s more than %(customer)s owed, "
                      "so it is kept as an advance.") % {
                        "amount": data["amount"], "extra": extra, "customer": customer.customer_name,
                    },
                )
            else:
                messages.success(
                    request,
                    _("₹ %(amount)s received from %(customer)s. It is applied to the oldest unpaid invoices first.") % {
                        "amount": data["amount"], "customer": customer.customer_name,
                    },
                )
            return redirect("customer_ledger", customer_id=customer.id)
    else:
        form = ReceiptForm(initial={
            "amount": statement["total_due"] if statement["total_due"] > 0 else None,
            "payment_date": timezone.localdate(),
            "payment_mode": "Cash",
        })

    return _receipt_page(request, {
        "form": form,
        "sale": None,
        "customer": customer,
        "due": statement["total_due"],
        "advance": statement["advance"],
        "kind": "customer",
    })


@login_required
@manager_required
def delete_payment(request, payment_id):
    """Remove a receipt or a commission payment entered by mistake."""
    company = company_of(request)
    payment = tenant_object_or_404(
        Payment.objects.select_related("sale", "customer", "broker"), request, payment_id
    )

    if payment.related_type == "sale":
        if payment.sale_id:
            back = redirect("sale_detail", sale_id=payment.sale_id)
        elif payment.customer_id:
            back = redirect("customer_ledger", customer_id=payment.customer_id)
        elif payment.broker_id:
            back = redirect("broker_report_detail", broker_id=payment.broker_id)
        else:
            back = redirect("sale_list")
    elif payment.related_type == "broker" and payment.broker_id:
        back = redirect("broker_report_detail", broker_id=payment.broker_id)
    else:
        # Mill payments are managed from the purchase side.
        return redirect("dashboard")

    if request.method == "POST":
        amount = payment.amount
        payment.delete()
        messages.success(request, _("Payment of ₹ %(amount)s deleted.") % {"amount": amount})

    return back


# --------------------------------------------------------------------------
# Unloading & settlement
# --------------------------------------------------------------------------

@login_required
@manager_required
def settle_sale(request, sale_id):
    """
    Record what happened when the truck reached the party: the weight they
    received, their cash discount, freight they paid the driver and any other
    cut. The customer's ledger then shows what they really owe.
    """
    from core.forms import SettlementForm
    from core.services.sale_service import apply_settlement

    company = company_of(request)
    sale = tenant_object_or_404(Sale.objects.select_related("customer", "broker"), request, sale_id)

    if request.method == "POST":
        form = SettlementForm(request.POST, instance=sale)
        if form.is_valid():
            sale = form.save(commit=False)
            figures = apply_settlement(sale)
            sale.save()
            messages.success(
                request,
                _("Truck %(no)s settled · %(kg)s kg received · party owes ₹ %(net)s") % {
                    "no": sale.invoice_no, "kg": figures["received_kg"], "net": figures["net_receivable"],
                },
            )
            return redirect("sale_detail", sale_id=sale.id)
    else:
        initial = {}
        if not sale.unload_date:
            initial = {
                "unload_date": timezone.localdate(),
                "received_weight_kg": sale.total_quantity_kg,
            }
            if not sale.cash_discount_percent:
                if sale.broker_id and sale.collect_from == Sale.COLLECT_FROM_BROKER:
                    initial["cash_discount_percent"] = sale.broker.default_cash_discount_percent
                elif sale.customer_id:
                    initial["cash_discount_percent"] = sale.customer.default_cash_discount_percent
        form = SettlementForm(instance=sale, initial=initial)

    return render(request, "core/sale_settle.html", {
        "form": form,
        "sale": sale,
        "profit": sale_profit(sale),
    })
