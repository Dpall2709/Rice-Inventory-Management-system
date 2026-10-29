"""
Create a customer, supplier or product without leaving a sale or purchase.

The entry screens open a pop-up that loads the form from here (GET) and posts
it back (POST). A valid post answers with JSON - the new record's id, label
and the details the entry screen needs - so the page can add it to its
dropdowns and select it. An invalid post answers with the form again,
errors included, for the pop-up to show.
"""

from django.contrib.auth.decorators import login_required
from django.http import HttpResponseNotAllowed, JsonResponse
from django.shortcuts import render
from django.utils.translation import gettext as _

from core.forms import CustomerForm, MillForm, ProductForm
from core.services.catalog import seed_company_catalog
from core.tenancy import company_of

# Only the fields needed to start trading; the rest can be filled in later
# from the full customer / supplier page.
CUSTOMER_FIELDS = [
    "customer_name", "mobile", "gst_number", "billing_address", "city", "state",
    "default_cash_discount_percent",
]
SUPPLIER_FIELDS = ["mill_name", "mobile", "gst_number", "address", "city", "state"]
PRODUCT_FIELDS = [
    "name", "category", "unit", "rate_unit", "default_pack_size", "hsn_code", "gst_percent",
]


def customer_payload(company, customer):
    from core.services.sale_service import suggested_tax_type

    return {
        "name": customer.customer_name,
        "gst": customer.gst_number,
        "mobile": customer.mobile,
        "state": customer.state,
        "address": customer.full_billing_address,
        "shipping": customer.full_shipping_address,
        "tax_type": suggested_tax_type(company, customer),
        "cd": float(customer.default_cash_discount_percent or 0),
    }


def supplier_payload(company, mill):
    from core.services.invoice_number import peek_supplier_bill_no
    from core.services.purchase_service import suggested_tax_type

    return {
        "name": mill.mill_name,
        "gst": mill.gst_number,
        "state": mill.state,
        "tax_type": suggested_tax_type(company, mill),
        "next_bill_no": peek_supplier_bill_no(mill),
    }


def product_payload(product):
    return {
        "name": product.name,
        "gst": float(product.gst_percent or 0),
        "hsn": product.hsn_code or "",
        "pack_size": float(product.default_pack_size or 1),
        "unit": product.unit_label,
        "rate_unit": product.rate_unit_label,
        # A brand-new product has no stock and no cost history yet.
        "stock": {},
        "cost_per_kg": 0,
        "suggested_per_kg": 0,
    }


def _subset(form, names):
    """Show only `names`; every other field becomes optional and is skipped."""
    for name in list(form.fields):
        if name not in names:
            del form.fields[name]
    return form


def _respond(request, kind, form, title):
    status = 400 if form.is_bound else 200
    return render(request, "core/partials/quick_form.html", {
        "form": form,
        "kind": kind,
        "title": title,
    }, status=status)


def _limit_methods(request):
    if request.method not in ("GET", "POST"):
        return HttpResponseNotAllowed(["GET", "POST"])
    return None


@login_required
def quick_customer(request):
    if (refused := _limit_methods(request)):
        return refused
    company = company_of(request)

    form = CustomerForm(request.POST or None)
    _subset(form, CUSTOMER_FIELDS)
    form.fields["default_cash_discount_percent"].required = False
    if request.method == "POST" and form.is_valid():
        customer = form.save(commit=False)
        customer.company = company
        customer.default_cash_discount_percent = customer.default_cash_discount_percent or 0
        customer.save()
        return JsonResponse({
            "kind": "customer", "id": customer.id, "label": customer.customer_name,
            "data": customer_payload(company, customer),
        }, status=201)

    return _respond(request, "customer", form, _("New customer"))


@login_required
def quick_supplier(request):
    if (refused := _limit_methods(request)):
        return refused
    company = company_of(request)

    form = MillForm(request.POST or None, company=company)
    _subset(form, SUPPLIER_FIELDS)
    if request.method == "POST" and form.is_valid():
        mill = form.save(commit=False)
        mill.company = company
        mill.save()
        return JsonResponse({
            "kind": "supplier", "id": mill.id, "label": mill.mill_name,
            "data": supplier_payload(company, mill),
        }, status=201)

    return _respond(request, "supplier", form, _("New supplier"))


@login_required
def quick_product(request):
    if (refused := _limit_methods(request)):
        return refused
    company = company_of(request)
    if not company.units.exists():
        seed_company_catalog(company)

    form = ProductForm(request.POST or None, company=company)
    _subset(form, PRODUCT_FIELDS)
    if request.method == "POST" and form.is_valid():
        product = form.save(commit=False)
        product.company = company
        product.is_active = True
        product.save()
        return JsonResponse({
            "kind": "product", "id": product.id, "label": product.name,
            "data": product_payload(product),
        }, status=201)

    return _respond(request, "product", form, _("New product"))
