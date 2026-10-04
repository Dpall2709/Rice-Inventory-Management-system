from decimal import Decimal, InvalidOperation
from django.shortcuts import render, redirect, get_object_or_404
from .models import Purchase, PurchaseItem, Mill, Product, Payment, SaleItem, Sale, Broker
from django.db import transaction
from django.db.models import Q, Sum, F, FloatField, ExpressionWrapper
from django.contrib import messages
from django.http import HttpResponse
from openpyxl import Workbook
from openpyxl.utils import get_column_letter
from datetime import datetime
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from datetime import datetime
import json
from django.utils import timezone
from io import BytesIO
from django.conf import settings
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
from reportlab.lib import colors
import qrcode
from reportlab.lib.utils import ImageReader
from num2words import num2words
from reportlab.pdfbase.pdfmetrics import stringWidth
from .permissions import manager_required, owner_required
from .services.ledger import mill_statement
from .services.mill_report import build_excel, build_pdf
from .tenancy import company_of, tenant_object_or_404
from .function.sale_invoice_pdf import sale_invoice_pdf, sale_statement_pdf  
from django.contrib.auth.decorators import login_required
from django.utils.translation import gettext as _

# @login_required
# def product_list(request):
#     q = request.GET.get("q", "").strip()
#     company = request.user.userprofile.company
#     products = Product.objects.all().order_by("-id")  # ✅ no created_at in your model

#     if q:
#         products = products.filter(
#             Q(rice_name__icontains=q) |
#             Q(hsn_code__icontains=q)
#         )

#     return render(request, "core/product_list.html", {"products": products})

@login_required
def product_list(request):
    q = request.GET.get("q", "").strip()

    # Get logged-in user's company
    company = request.user.userprofile.company

    # Only products belonging to this company
    products = Product.objects.filter(
        company=company
    ).order_by("-id")

    if q:
        products = products.filter(
            Q(rice_name__icontains=q) |
            Q(hsn_code__icontains=q)
        )

    return render(
        request,
        "core/product_list.html",
        {
            "products": products
        }
    )

@login_required
def add_product(request):
    company = request.user.userprofile.company
    if request.method == "POST":
        Product.objects.create(
            company=company,
            rice_name=request.POST.get("rice_name"),
            hsn_code=request.POST.get("hsn_code", ""),
            gst_percent=request.POST.get("gst_percent") or 0,
            is_active=True if request.POST.get("is_active") == "on" else False,
        )
        messages.success(request, "✅ " + _("Product saved successfully!"))
        return redirect("product_list")

    return render(request, "core/add_product.html")

@login_required
def edit_product(request, product_id):
    company = request.user.userprofile.company
    product = get_object_or_404(Product, id=product_id, company=company,)

    if request.method == "POST":
        product.rice_name = request.POST.get("rice_name")
        product.hsn_code = request.POST.get("hsn_code", "")
        product.gst_percent = request.POST.get("gst_percent") or 0
        product.is_active = True if request.POST.get("is_active") == "on" else False
        product.save()

        messages.success(request, "✅ " + _("Product updated successfully!"))
        return redirect("product_list")

    return render(request, "core/edit_product.html", {"product": product})

@login_required
@manager_required
def delete_product(request, product_id):
    company = request.user.userprofile.company
    product = get_object_or_404(Product, id=product_id, company=company,)

    if request.method == "POST":
        # A rice that has been sold is part of customer invoices, so it can
        # only be switched off, never removed.
        if product.saleitem_set.exists():
            product.is_active = False
            product.save(update_fields=["is_active"])
            messages.warning(
                request,
                _("%(name)s is on sale invoices, so it was deactivated instead of deleted.")
                % {"name": product.rice_name},
            )
            return redirect("product_list")

        product.delete()
        messages.success(request, "🗑 " + _("Product deleted successfully!"))
        return redirect("product_list")

    return render(request, "core/delete_product.html", {"product": product})

@login_required
def product_report(request, product_id):

    # Get logged-in user's company
    company = request.user.userprofile.company

    # Only allow access to product belonging to this company
    product = get_object_or_404(
        Product,
        id=product_id,
        company=company
    )

    total_purchase_bags = (
        PurchaseItem.objects
        .filter(
            product=product,
            purchase__company=company
        )
        .aggregate(
            s=Sum("bag_count")
        )["s"] or 0
    )

    total_sale_bags = (
        SaleItem.objects
        .filter(
            product=product,
            sale__company=company
        )
        .aggregate(
            s=Sum("bag_count")
        )["s"] or 0
    )

    current_stock_bags = (
        total_purchase_bags - total_sale_bags
    )

    purchase_items = (
        PurchaseItem.objects
        .select_related(
            "purchase",
            "purchase__mill"
        )
        .filter(
            product=product,
            purchase__company=company
        )
        .order_by(
            "-purchase__purchase_date"
        )
    )

    return render(
        request,
        "core/product_report.html",
        {
            "product": product,
            "total_purchase_bags": total_purchase_bags,
            "total_sale_bags": total_sale_bags,
            "current_stock_bags": current_stock_bags,
            "purchase_items": purchase_items,
        }
    )
@login_required
def mill_report_detail(request, mill_id):

    # Get mill only from the logged-in user's company
    company = request.user.userprofile.company

    mill = get_object_or_404(
        Mill,
        id=mill_id,
        company=company
    )

    # All purchases belonging to this mill AND company
    purchases = (
        Purchase.objects
        .filter(
            company=company,
            mill=mill
        )
        .order_by("-purchase_date", "-id")
    )

    # All purchase payments belonging to this mill AND company
    payments = (
        Payment.objects
        .filter(
            company=company,
            related_type="purchase",
            mill=mill
        )
        .order_by("-payment_date", "-id")
    )

    # Totals
    total_purchase = (
        purchases.aggregate(s=Sum("total_amount"))["s"] or 0
    )

    total_paid = (
        payments.aggregate(s=Sum("amount"))["s"] or 0
    )

    balance = (
        float(mill.opening_balance)
        + float(total_purchase)
        - float(total_paid)
    )

    # All purchase items belonging to this mill/company
    all_items = PurchaseItem.objects.filter(
        purchase__company=company,
        purchase__mill=mill
    )

    grand_total_bags = (
        all_items.aggregate(s=Sum("bag_count"))["s"] or 0
    )

    grand_total_kg = (
        all_items.aggregate(
            s=Sum(
                F("bag_weight") * F("bag_count")
            )
        )["s"] or 0
    )

    # Money paid to the mill in general is applied to the oldest debt first, so
    # the invoice rows always add up to the balance shown at the top.
    statement = mill_statement(company, mill)

    purchase_rows = []

    for entry in reversed(statement["rows"]):
        purchase = entry["purchase"]
        items = list(purchase.purchaseitem_set.all())

        total_bags = sum(item.bag_count or 0 for item in items)
        total_kg = sum(
            (item.total_kg or (item.bag_weight or 0) * (item.bag_count or 0))
            for item in items
        )

        avg_rate = 0
        if total_kg:
            avg_rate = float(purchase.taxable_amount or purchase.total_amount) / float(total_kg)

        # The rates actually paid, which is what a person checking a bill wants
        # to see. The average only matters when one bill mixes rates.
        rates = []
        for item in items:
            rate = float(item.purchase_price or 0)
            if rate not in rates:
                rates.append(rate)

        purchase_rows.append({
            "id": purchase.id,
            "purchase_date": purchase.purchase_date,
            "invoice_no": purchase.invoice_no,
            "purchase_ref": purchase.purchase_ref,
            "tax_type": purchase.tax_type,
            "gst_amount": purchase.gst_amount,

            "total_bags": total_bags,
            "total_kg": total_kg,
            "avg_rate": round(avg_rate, 2),
            "rates": rates,
            "single_rate": rates[0] if len(rates) == 1 else None,

            "items": items,

            "total_amount": entry["total"],
            "paid": entry["paid"],
            "direct_paid": entry["direct_paid"],
            "applied_from_account": entry["applied_from_account"],
            "due": entry["due"],
            "status": entry["status"],
        })

    total_purchase = statement["total_purchased"]
    total_paid = statement["total_paid"]
    balance = statement["total_due"]

    return render(
        request,
        "core/mill_report_detail.html",
        {
            "mill": mill,

            "purchases": purchases,
            "payments": payments,

            "total_purchase": total_purchase,
            "total_paid": total_paid,
            "balance": round(balance, 2),

            "grand_total_bags": grand_total_bags,
            "grand_total_kg": grand_total_kg,

            "purchase_rows": purchase_rows,
            "statement": statement,
            "on_account": statement["on_account"],
            "advance": statement["advance"],
            "opening_due": statement["opening_due"],
        }
    )
@login_required
def mill_report_excel(request, mill_id):
    """Download the supplier statement as an Excel workbook."""
    company = company_of(request)
    mill = tenant_object_or_404(Mill, request, mill_id)

    return build_excel(company, mill)


@login_required
def mill_report_pdf(request, mill_id):
    """The supplier statement as a PDF, ready to send to the mill."""
    company = company_of(request)
    mill = tenant_object_or_404(Mill, request, mill_id)

    return build_pdf(company, mill)


from io import BytesIO
from decimal import Decimal
import qrcode

from django.conf import settings
from django.http import HttpResponse
from django.shortcuts import get_object_or_404

from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase.pdfmetrics import stringWidth

from .models import Sale, SaleItem



def _amount_words(n: Decimal):
    number = int(n)
    words = num2words(number, lang='en_IN')
    return words.title() + " Only"

from django.contrib.auth import authenticate, login, logout
from django.shortcuts import render, redirect
from django.contrib import messages
from core.models import UserProfile



def login_view(request):

    if request.user.is_authenticated:
        return redirect("dashboard")

    if request.method == "POST":

        username = request.POST.get("username")
        password = request.POST.get("password")

        user = authenticate(
            request,
            username=username,
            password=password
        )

        if user is None:
            messages.error(request, _("Invalid username or password."))
            return render(request, "core/login.html")

        try:
            profile = UserProfile.objects.select_related("company").get(user=user)

        except UserProfile.DoesNotExist:
            messages.error(request, "Your account is not configured correctly.")
            return render(request, "core/login.html")

        if not profile.is_active:
            messages.error(request, "Your account has been deactivated.")
            return render(request, "core/login.html")

        if not profile.company.is_active:
            messages.error(request, "Your company account is inactive.")
            return render(request, "core/login.html")

        login(request, user)

        messages.success(
            request,
            f"Welcome {user.first_name or user.username}!"
        )

        return redirect("dashboard")

    return render(request, "core/login.html")


def logout_view(request):

    logout(request)

    messages.success(request, "Logged out successfully.")

    return redirect("login")