"""
Entering and editing a purchase bill.

One screen records: the mill's bill, its rice lines with GST, the bill-level
charges, and whatever you paid at that moment.
"""

import json

from django.db import transaction
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _

from core.forms import PurchaseForm, PurchaseItemFormSet
from core.models import Payment, Product, Purchase
from core.permissions import manager_required
from core.services.invoice_number import next_purchase_ref, next_supplier_bill_no
from core.services.purchase_service import apply_totals, suggested_tax_type
from core.tenancy import company_of, tenant_object_or_404

from ..base_imports import *


def product_tax_map(company):
    """
    GST% and HSN of each rice, handed to the page as JSON so choosing a product
    fills its tax rate in automatically.
    """
    products = Product.objects.filter(company=company, is_active=True)
    return json.dumps({
        str(p.id): {
            "gst": float(p.gst_percent or 0),
            "hsn": p.hsn_code or "",
            "name": p.rice_name,
        }
        for p in products
    })


def _supplier_from(request, company):
    """The supplier named in ?mill=<id> (or the posted lock), if it is this company's."""
    raw = request.GET.get("mill") or request.POST.get("locked_mill") or ""
    if not raw.isdigit():
        return None
    from core.models import Mill

    return Mill.objects.for_company(company).filter(pk=int(raw), is_active=True).first()


def _lock_supplier(form, supplier):
    """The bill belongs to this supplier: no dropdown to pick another one."""
    from django import forms as django_forms

    form.fields["mill"].widget = django_forms.HiddenInput()
    form.fields["mill"].initial = supplier.id
    if form.is_bound:
        data = form.data.copy()
        data["mill"] = str(supplier.id)
        form.data = data


def next_bill_numbers(company):
    """{mill id: next automatic bill number} - shown as a hint in the form."""
    from core.models import Mill
    from core.services.invoice_number import peek_supplier_bill_no

    return json.dumps({
        str(mill.id): peek_supplier_bill_no(mill)
        for mill in Mill.objects.for_company(company).filter(is_active=True)
    })


def split_charges(purchase, form):
    """
    Decide where transport and labour belong.

    Each has one amount box and one tick box:

        ticked   - the MILL charged it on its bill, so it is added to the bill
                   total and you owe it to the mill
        unticked - YOU paid it (your truck, your labour), so the mill's bill
                   stays pure rice and the money is recorded as your expense

    Either way it counts towards the cost per kg - it is what the rice cost you.
    """
    data = form.cleaned_data

    transport = data.get("transport_amount") or 0
    labour = data.get("labour_amount") or 0

    purchase.freight_charge = transport if data.get("transport_by_mill") else 0
    purchase.labour_charge = labour if data.get("labour_by_mill") else 0

    return {
        "transport": (transport, bool(data.get("transport_by_mill"))),
        "labour": (labour, bool(data.get("labour_by_mill"))),
    }


def save_own_expenses(purchase, form):
    """
    Store what the buyer paid themselves.

    These never touch the mill's balance; they are part of the cost of the
    goods, which is what the cost-per-kg figure is built from.
    """
    from core.models import PurchaseExpense

    PurchaseExpense.objects.filter(purchase=purchase).delete()

    data = form.cleaned_data

    entries = []
    if not data.get("transport_by_mill"):
        entries.append((PurchaseExpense.TRANSPORT, data.get("transport_amount"), ""))
    if not data.get("labour_by_mill"):
        entries.append((PurchaseExpense.LABOUR, data.get("labour_amount"), ""))
    entries.append((PurchaseExpense.OTHER, data.get("expense_other"),
                    data.get("expense_other_note") or ""))

    created = []
    for category, amount, note in entries:
        if not amount or amount <= 0:
            continue
        created.append(PurchaseExpense.objects.create(
            purchase=purchase,
            category=category,
            amount=amount,
            notes=note,
            expense_date=purchase.purchase_date,
        ))

    return created


def record_payment(purchase, amount, mode, company):
    """A payment made while entering the bill, so the mill ledger is right at once."""
    if not amount or amount <= 0:
        return None

    return Payment.objects.create(
        company=company,
        related_type="purchase",
        mill=purchase.mill,
        purchase=purchase,
        amount=amount,
        payment_mode=mode or "Cash",
        payment_date=purchase.purchase_date,
        notes="Paid while entering the bill.",
    )


@login_required
def add_purchase(request):
    from .scan import attach_scan, clear_draft, draft_initial, get_draft

    company = company_of(request)

    # A bill scanned at /purchase/scan/ arrives here as ?scan=1 with its draft
    # in the session; the form is pre-filled and the user checks it.
    scan_draft = get_draft(request) if (request.GET.get("scan") or request.POST.get("scan")) else None

    # Opened from a supplier's page ("Add purchase bill"): the supplier is
    # fixed, and saving goes back to that supplier.
    supplier = _supplier_from(request, company)

    if request.method == "POST":
        form = PurchaseForm(request.POST, company=company)
        formset = PurchaseItemFormSet(request.POST, form_kwargs={"company": company})
        if supplier:
            _lock_supplier(form, supplier)

        if form.is_valid() and formset.is_valid():
            with transaction.atomic():
                purchase = form.save(commit=False)
                purchase.company = company
                purchase.total_amount = 0
                purchase.purchase_ref = next_purchase_ref(company, purchase.purchase_date)
                if not purchase.invoice_no:
                    purchase.invoice_no = next_supplier_bill_no(purchase.mill)
                purchase.save()

                items = []
                for item_form in formset.forms:
                    if item_form.cleaned_data.get("DELETE"):
                        continue
                    if not item_form.cleaned_data.get("product"):
                        continue

                    item = item_form.save(commit=False)
                    item.purchase = purchase
                    items.append(item)

                split_charges(purchase, form)

                apply_totals(
                    purchase,
                    items,
                    tax_type=form.cleaned_data["tax_type"],
                    discount=form.cleaned_data.get("discount_amount") or 0,
                    freight=purchase.freight_charge,
                    labour=purchase.labour_charge,
                )

                for item in items:
                    item.save()

                purchase.save()

                save_own_expenses(purchase, form)

                record_payment(
                    purchase,
                    form.cleaned_data.get("amount_paid_now") or 0,
                    form.cleaned_data.get("payment_mode"),
                    company,
                )

                if scan_draft:
                    attach_scan(purchase, scan_draft)
                    purchase.save(update_fields=["bill_file", "entry_source", "irn"])

            if scan_draft:
                clear_draft(request)

            messages.success(
                request,
                _("Purchase %(ref)s saved · %(bags)s bags · ₹ %(total)s") % {
                    "ref": purchase.purchase_ref,
                    "bags": purchase.total_bags,
                    "total": purchase.total_amount,
                },
            )

            if request.POST.get("save_and_new"):
                if supplier:
                    return redirect(f"{reverse('add_purchase')}?mill={supplier.id}")
                return redirect("add_purchase")

            if supplier:
                return redirect("mill_report_detail", mill_id=supplier.id)
            return redirect("purchase_detail", purchase_id=purchase.id)
    elif scan_draft:
        initial, lines = draft_initial(company, scan_draft)
        initial["purchase_date"] = initial["purchase_date"] or timezone.localdate()
        form = PurchaseForm(company=company, initial=initial)
        formset = PurchaseItemFormSet(initial=lines, form_kwargs={"company": company})
        formset.extra = max(len(lines), 1)
    else:
        initial = {"purchase_date": timezone.localdate()}
        if supplier:
            initial["mill"] = supplier.id
        form = PurchaseForm(company=company, initial=initial)
        if supplier:
            _lock_supplier(form, supplier)
        formset = PurchaseItemFormSet(form_kwargs={"company": company})

    return render(request, "core/purchase_form.html", {
        "form": form,
        "formset": formset,
        "mode": "add",
        "product_tax_json": product_tax_map(company),
        "scan": scan_draft,
        "supplier": supplier,
        "next_bill_numbers": next_bill_numbers(company),
    })


@login_required
@manager_required
def edit_purchase(request, purchase_id):
    company = company_of(request)
    purchase = tenant_object_or_404(Purchase, request, purchase_id)

    if request.method == "POST":
        form = PurchaseForm(request.POST, instance=purchase, company=company)
        formset = PurchaseItemFormSet(request.POST, instance=purchase, form_kwargs={"company": company})

        if form.is_valid() and formset.is_valid():
            with transaction.atomic():
                purchase = form.save(commit=False)

                formset.save()          # applies edits, additions and deletions
                items = list(purchase.purchaseitem_set.all())

                split_charges(purchase, form)

                apply_totals(
                    purchase,
                    items,
                    tax_type=form.cleaned_data["tax_type"],
                    discount=form.cleaned_data.get("discount_amount") or 0,
                    freight=purchase.freight_charge,
                    labour=purchase.labour_charge,
                )

                for item in items:
                    item.save()

                if not purchase.invoice_no:
                    purchase.invoice_no = next_supplier_bill_no(purchase.mill)
                purchase.save()

                save_own_expenses(purchase, form)

                record_payment(
                    purchase,
                    form.cleaned_data.get("amount_paid_now") or 0,
                    form.cleaned_data.get("payment_mode"),
                    company,
                )

            messages.success(request, _("Purchase %(ref)s updated.") % {
                "ref": purchase.purchase_ref or purchase.invoice_no,
            })
            return redirect("purchase_detail", purchase_id=purchase.id)
    else:
        from core.models import PurchaseExpense

        existing = {e.category: e for e in purchase.expenses.all()}
        other = existing.get(PurchaseExpense.OTHER)

        own_transport = getattr(existing.get(PurchaseExpense.TRANSPORT), "amount", None)
        own_labour = getattr(existing.get(PurchaseExpense.LABOUR), "amount", None)

        form = PurchaseForm(instance=purchase, company=company, initial={
            "transport_amount": purchase.freight_charge or own_transport,
            "transport_by_mill": bool(purchase.freight_charge),
            "labour_amount": purchase.labour_charge or own_labour,
            "labour_by_mill": bool(purchase.labour_charge),
            "expense_other": getattr(other, "amount", None),
            "expense_other_note": getattr(other, "notes", ""),
            "margin_percent": company.default_margin_percent,
        })
        formset = PurchaseItemFormSet(instance=purchase, form_kwargs={"company": company})

    return render(request, "core/purchase_form.html", {
        "form": form,
        "formset": formset,
        "purchase": purchase,
        "mode": "edit",
        "product_tax_json": product_tax_map(company),
    })
