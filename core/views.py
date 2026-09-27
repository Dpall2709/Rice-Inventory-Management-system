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
from .function.add_sale import add_sale
from .function.sale_invoice_pdf import sale_invoice_pdf  
from django.contrib.auth.decorators import login_required

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
        messages.success(request, "✅ Product saved successfully!")
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

        messages.success(request, "✅ Product updated successfully!")
        return redirect("product_list")

    return render(request, "core/edit_product.html", {"product": product})

@login_required
@manager_required
def delete_product(request, product_id):
    company = request.user.userprofile.company
    product = get_object_or_404(Product, id=product_id, company=company,)

    if request.method == "POST":
        product.delete()
        messages.success(request, "🗑 Product deleted successfully!")
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


@login_required
def sale_list(request):
    q = request.GET.get("q", "").strip()

    # Get logged-in user's company
    company = request.user.userprofile.company

    # Only show sales belonging to this company
    sales = (
        Sale.objects
        .select_related("broker")
        .filter(company=company)
        .order_by("-sale_date", "-id")
    )

    if q:
        sales = sales.filter(
            Q(customer_name__icontains=q) |
            Q(invoice_no__icontains=q) |
            Q(broker__broker_name__icontains=q)
        )

    rows = []

    for s in sales:

        paid = Payment.objects.filter(
            company=company,
            related_type="sale",
            sale=s
        ).aggregate(x=Sum("amount"))["x"] or 0

        due = float(s.total_amount) - float(paid)

        if due <= 0:
            status = "PAID"
        elif paid > 0:
            status = "PARTIAL"
        else:
            status = "DUE"

        rows.append({
            "id": s.id,
            "sale_date": s.sale_date,
            "invoice_no": s.invoice_no,
            "customer_name": s.customer_name,
            "broker": s.broker,
            "total_amount": s.total_amount,
            "paid": paid,
            "due": round(due, 2),
            "status": status,
        })

    return render(request, "core/sale_list.html", {
        "rows": rows,
        "q": q,
    })

from django.db.models import Sum
@login_required
def sale_detail(request, sale_id):
    company = request.user.userprofile.company
    sale = get_object_or_404(Sale, id=sale_id, company=company)
    

    # internal breakup items (BUY cost)
    items = SaleItem.objects.filter(sale=sale).select_related("mill", "product")

    # Rice payments only
    payments = Payment.objects.filter(
        related_type="sale",
        sale=sale
    ).order_by("-payment_date", "-id")

    # ✅ selling side totals (rice invoice)
    rice_total = float(sale.taxable_amount) + float(sale.gst_amount)

    # total kg from sale header
    total_kg = float(sale.total_quantity_kg or 0)

    # ✅ selling rate per kg (auto)
    selling_rate_per_kg = 0
    if total_kg > 0:
        selling_rate_per_kg = float(sale.taxable_amount) / total_kg

    # ✅ total bags from breakup rows
    total_bags = items.aggregate(s=Sum("bag_count"))["s"] or 0

    # ✅ rice received = advance + other payments
    paid_extra = payments.aggregate(s=Sum("amount"))["s"] or 0
    rice_received_total = float(sale.advance_received) + float(paid_extra)
    rice_due = rice_total - rice_received_total
    if rice_due < 0:
        rice_due = 0

    # ✅ transport due (separate)
    transport_due = float(sale.transport_charge) - (
        float(sale.transport_paid_by_dealer) + float(sale.transport_paid_by_customer)
    )
    if transport_due < 0:
        transport_due = 0

    # ✅ buy cost total from breakup rows
    buy_cost_total = items.aggregate(s=Sum("amount"))["s"] or 0

    # ✅ profit estimate (rice selling - buy cost)
    profit_estimate = rice_total - float(buy_cost_total)

    return render(request, "core/sale_detail.html", {
        "sale": sale,
        "items": items,

        # Rice invoice (selling)
        "total_bags": total_bags,
        "total_kg": round(total_kg, 2),
        "selling_rate_per_kg": round(selling_rate_per_kg, 2),
        "rice_total": round(rice_total, 2),
        "paid_extra": round(float(paid_extra), 2),
        "rice_received_total": round(rice_received_total, 2),
        "rice_due": round(rice_due, 2),

        # Transport
        "transport_due": round(transport_due, 2),

        # Internal (buying)
        "buy_cost_total": round(float(buy_cost_total), 2),
        "profit_estimate": round(float(profit_estimate), 2),

        # payments table
        "payments": payments,
    })


@login_required
def add_sale_payment(request, sale_id):

    company = request.user.userprofile.company

    sale = get_object_or_404(
        Sale,
        id=sale_id,
        company=company
    )

    if request.method == "POST":

        Payment.objects.create(
            company=company,
            related_type="sale",
            sale=sale,
            amount=request.POST.get("amount"),
            payment_mode=request.POST.get("payment_mode"),
            payment_date=request.POST.get("payment_date"),
            notes=request.POST.get("notes", "")
        )

        messages.success(
            request,
            "✅ Payment saved successfully!"
        )

        return redirect(
            "sale_detail",
            sale_id=sale.id
        )

    return render(
        request,
        "core/add_sale_payment.html",
        {"sale": sale}
    )
def generate_sale_invoice_no(company=None):
    """
    Next sale invoice number.

    Kept as a thin wrapper so older imports keep working; the real logic lives
    in core/services/invoice_number.py and is per company.
    """
    from core.services.invoice_number import next_sale_invoice_no

    if company is None:
        raise ValueError("generate_sale_invoice_no() needs a company.")

    return next_sale_invoice_no(company)



@login_required
def sale_print(request, sale_id):
    company = request.user.userprofile.company
    sale = get_object_or_404(Sale, id=sale_id, company=company)

    rice_total = float(sale.taxable_amount) + float(sale.gst_amount)

    return render(request, "core/sale_print.html", {
        "sale": sale,
        "rice_total": rice_total,
    })


@login_required
def broker_list(request):
    company = request.user.userprofile.company

    q = request.GET.get("q", "").strip()

    brokers = Broker.objects.filter(
        company=company
    ).order_by("-created_at")

    if q:
        brokers = brokers.filter(
            broker_name__icontains=q
        )

    return render(request, "core/broker_list.html", {
        "brokers": brokers
    })

@login_required
def add_broker(request):

    company = request.user.userprofile.company

    if request.method == "POST":

        Broker.objects.create(
            company=company,
            broker_name=request.POST.get("broker_name"),
            mobile=request.POST.get("mobile", ""),
            gst_number=request.POST.get("gst_number", ""),
            opening_balance=request.POST.get("opening_balance") or 0,
            address=request.POST.get("address", "")
        )

        messages.success(
            request,
            "✅ Broker saved successfully!"
        )

        return redirect("broker_list")

    return render(
        request,
        "core/add_broker.html"
    )
@login_required
def broker_report_detail(request, broker_id):
    company = request.user.userprofile.company

    broker = get_object_or_404(
        Broker,
        id=broker_id,
        company=company
    )

    sales = Sale.objects.filter(
        broker=broker
    ).order_by("-sale_date", "-id")

    total_sales = sales.aggregate(
        s=Sum("total_amount")
    )["s"] or 0

    total_advance = sales.aggregate(
        s=Sum("advance_received")
    )["s"] or 0

    total_due = float(total_sales) - float(total_advance)

    return render(request, "core/broker_report_detail.html", {
        "broker": broker,
        "sales": sales,
        "total_sales": total_sales,
        "total_advance": total_advance,
        "total_due": total_due
    })


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
            messages.error(request, "Invalid username or password.")
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