"""
REST API for the mobile app - /api/v1/...

Every view works on the logged-in user's company only (see permissions.py)
and reuses the same services as the website, so a sale saved from the phone
is calculated, stock-checked and numbered exactly like one saved on the web.
"""

from decimal import Decimal

from django.db.models import Q
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from core.models import (
    Customer, Mill, Payment, Product, ProductCategory, Purchase, Sale, Unit,
)

from . import serializers as s
from .permissions import DEFAULT, WRITE_ROLES


def _money(value):
    return str(Decimal(value or 0).quantize(Decimal("0.01")))


class CompanyScoped:
    """Querysets limited to the request's company; new rows get it too."""

    permission_classes = DEFAULT
    model = None

    def base_queryset(self):
        return self.model.objects.for_company(self.request.company)

    def get_queryset(self):
        return self.base_queryset()

    def perform_create(self, serializer):
        serializer.save(company=self.request.company)


class SearchMixin:
    search_fields = ()

    def filter_search(self, queryset):
        q = (self.request.query_params.get("q") or "").strip()
        if q and self.search_fields:
            query = Q()
            for field in self.search_fields:
                query |= Q(**{f"{field}__icontains": q})
            queryset = queryset.filter(query)
        active = self.request.query_params.get("active")
        if active in ("1", "true") and hasattr(self.model, "is_active"):
            queryset = queryset.filter(is_active=True)
        return queryset


class DeactivateInsteadOfDelete:
    """Masters with history are switched off, never removed (same as the web)."""

    def perform_destroy(self, instance):
        instance.is_active = False
        instance.save(update_fields=["is_active"])


# --------------------------------------------------------------------------
# Who am I
# --------------------------------------------------------------------------

@api_view(["GET"])
@permission_classes(DEFAULT)
def me(request):
    company = request.company
    profile = request.user_profile
    from billing.services import subscription_for

    subscription = subscription_for(company)
    return Response({
        "user": {
            "id": request.user.id,
            "username": request.user.username,
            "name": request.user.get_full_name() or request.user.username,
            "email": request.user.email,
            "role": profile.role,
            "can_edit": request.user.is_superuser or profile.role in WRITE_ROLES,
        },
        "company": {
            "id": company.id,
            "name": company.company_name,
            "gst_number": company.gst_number,
            "state": company.state,
            "industry": company.industry,
            "default_freight_mode": company.default_freight_mode,
            "invoice_prefix": company.invoice_prefix,
        },
        "subscription": {
            "is_expired": subscription.is_expired,
            "status": subscription.status,
            "ends_on": subscription.end_date,
        },
        "choices": {
            "freight_modes": [{"value": v, "label": str(l)} for v, l in Sale.FREIGHT_CHOICES],
            "tax_types": [{"value": v, "label": str(l)} for v, l in Sale.TAX_TYPES],
            "payment_modes": ["Cash", "UPI", "Bank", "Cheque"],
        },
    })


# --------------------------------------------------------------------------
# Masters
# --------------------------------------------------------------------------

class UnitViewSet(CompanyScoped, DeactivateInsteadOfDelete, viewsets.ModelViewSet):
    model = Unit
    serializer_class = s.UnitSerializer

    def get_queryset(self):
        return self.base_queryset().order_by("name")


class CategoryViewSet(CompanyScoped, DeactivateInsteadOfDelete, viewsets.ModelViewSet):
    model = ProductCategory
    serializer_class = s.CategorySerializer

    def get_queryset(self):
        return self.base_queryset().order_by("name")


class ProductViewSet(CompanyScoped, SearchMixin, DeactivateInsteadOfDelete, viewsets.ModelViewSet):
    model = Product
    serializer_class = s.ProductSerializer
    search_fields = ("name", "sku", "hsn_code")

    def get_queryset(self):
        queryset = self.base_queryset().select_related("category", "unit", "rate_unit").order_by("name")
        category = self.request.query_params.get("category")
        if category and category.isdigit():
            queryset = queryset.filter(category_id=int(category))
        return self.filter_search(queryset)

    @action(detail=False, methods=["get"])
    def stock(self, request):
        """Quantity in stock per product and pack size."""
        from core.services.sale_service import product_stock
        from core.utils import qty_str

        stock = product_stock(request.company)
        products = {p.id: p for p in self.base_queryset().select_related("unit", "rate_unit")}
        rows = []
        for (product_id, pack_size), quantity in sorted(stock.items(), key=lambda kv: (kv[0][0], kv[0][1])):
            product = products.get(product_id)
            if product is None or quantity == 0:
                continue
            rows.append({
                "product": product_id,
                "product_name": product.name,
                "pack_size": qty_str(pack_size),
                "quantity": qty_str(quantity),
                "unit": product.unit_label,
                "rate_unit": product.rate_unit_label,
                "total_units": qty_str(Decimal(quantity) * Decimal(pack_size)),
            })
        return Response(rows)


class CustomerViewSet(CompanyScoped, SearchMixin, DeactivateInsteadOfDelete, viewsets.ModelViewSet):
    model = Customer
    serializer_class = s.CustomerSerializer
    search_fields = ("customer_name", "mobile", "gst_number", "city")

    def get_queryset(self):
        return self.filter_search(self.base_queryset().order_by("customer_name"))

    @action(detail=True, methods=["get"])
    def statement(self, request, pk=None):
        from core.services.customer_ledger import customer_statement

        customer = self.get_object()
        data = customer_statement(request.company, customer)
        return Response({
            "customer": s.CustomerSerializer(customer, context=self.get_serializer_context()).data,
            "opening_due": _money(data["opening_due"]),
            "total_sold": _money(data["total_sold"]),
            "total_received": _money(data["total_received"]),
            "total_due": _money(data["total_due"]),
            "advance": _money(data["advance"]),
            "invoices": [
                {
                    "sale": row["sale"].id,
                    "invoice_no": row["sale"].invoice_no,
                    "date": row["sale"].sale_date,
                    "due_date": row["sale"].due_date,
                    "total": _money(row["total"]),
                    "paid": _money(row["paid"]),
                    "due": _money(row["due"]),
                    "status": row["status"],
                    "overdue": row["overdue"],
                }
                for row in data["rows"]
            ],
        })


class SupplierViewSet(CompanyScoped, SearchMixin, DeactivateInsteadOfDelete, viewsets.ModelViewSet):
    model = Mill
    serializer_class = s.SupplierSerializer
    search_fields = ("mill_name", "mobile", "gst_number", "city")

    def get_queryset(self):
        return self.filter_search(self.base_queryset().order_by("mill_name"))

    @action(detail=True, methods=["get"])
    def statement(self, request, pk=None):
        from core.services.ledger import mill_statement

        supplier = self.get_object()
        data = mill_statement(request.company, supplier)
        return Response({
            "supplier": s.SupplierSerializer(supplier, context=self.get_serializer_context()).data,
            "opening_due": _money(data["opening_due"]),
            "total_purchased": _money(data["total_purchased"]),
            "total_paid": _money(data["total_paid"]),
            "total_due": _money(data["total_due"]),
            "bills": [
                {
                    "purchase": row["purchase"].id,
                    "invoice_no": row["purchase"].invoice_no,
                    "date": row["purchase"].purchase_date,
                    "total": _money(row["total"]),
                    "paid": _money(row["paid"]),
                    "due": _money(row["due"]),
                    "status": row["status"],
                }
                for row in data["rows"]
            ],
        })


# --------------------------------------------------------------------------
# Transactions
# --------------------------------------------------------------------------

class DateRangeMixin:
    date_field = None

    def filter_dates(self, queryset):
        params = self.request.query_params
        if params.get("from"):
            queryset = queryset.filter(**{f"{self.date_field}__gte": params["from"]})
        if params.get("to"):
            queryset = queryset.filter(**{f"{self.date_field}__lte": params["to"]})
        return queryset


class PurchaseViewSet(CompanyScoped, DateRangeMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin,
                      mixins.CreateModelMixin, viewsets.GenericViewSet):
    """List, view and enter purchase bills. Editing stays on the website."""

    model = Purchase
    serializer_class = s.PurchaseSerializer
    date_field = "purchase_date"

    def get_queryset(self):
        queryset = (
            self.base_queryset()
            .select_related("mill")
            .prefetch_related("purchaseitem_set__product__unit", "purchaseitem_set__product__rate_unit")
            .order_by("-purchase_date", "-id")
        )
        supplier = self.request.query_params.get("supplier")
        if supplier and supplier.isdigit():
            queryset = queryset.filter(mill_id=int(supplier))
        q = (self.request.query_params.get("q") or "").strip()
        if q:
            queryset = queryset.filter(Q(invoice_no__icontains=q) | Q(mill__mill_name__icontains=q)
                                       | Q(purchase_ref__icontains=q))
        return self.filter_dates(queryset)

    def perform_create(self, serializer):
        serializer.save()


class SaleViewSet(CompanyScoped, DateRangeMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin,
                  mixins.CreateModelMixin, viewsets.GenericViewSet):
    """List, view and make sale invoices; download the invoice PDF."""

    model = Sale
    serializer_class = s.SaleSerializer
    date_field = "sale_date"

    def get_queryset(self):
        queryset = (
            self.base_queryset()
            .select_related("customer", "broker")
            .prefetch_related("items__product__unit", "items__product__rate_unit")
            .order_by("-sale_date", "-id")
        )
        customer = self.request.query_params.get("customer")
        if customer and customer.isdigit():
            queryset = queryset.filter(customer_id=int(customer))
        q = (self.request.query_params.get("q") or "").strip()
        if q:
            queryset = queryset.filter(Q(invoice_no__icontains=q) | Q(customer_name__icontains=q)
                                       | Q(vehicle_number__icontains=q))
        return self.filter_dates(queryset)

    def perform_create(self, serializer):
        serializer.save()

    @action(detail=True, methods=["get"], url_path="invoice-pdf")
    def invoice_pdf(self, request, pk=None):
        from core.function.sale_invoice_pdf import build_invoice_pdf

        sale = self.get_object()
        response = HttpResponse(build_invoice_pdf(request.company, sale), content_type="application/pdf")
        response["Content-Disposition"] = f'inline; filename="Invoice_{sale.invoice_no}.pdf"'
        return response

    @action(detail=True, methods=["get"], url_path="transport-invoice-pdf")
    def transport_invoice_pdf(self, request, pk=None):
        from core.function.sale_invoice_pdf import build_transport_invoice_pdf

        sale = self.get_object()
        if not sale.has_transport_invoice:
            return Response({"detail": "This sale has no separate transport invoice."}, status=404)
        response = HttpResponse(build_transport_invoice_pdf(request.company, sale), content_type="application/pdf")
        response["Content-Disposition"] = f'inline; filename="Transport_{sale.transport_invoice_no}.pdf"'
        return response

    @action(detail=False, methods=["get"])
    def lots(self, request):
        """Stock lots that can be picked for a sale line, oldest first."""
        from core.services.sale_service import stock_lots
        from core.utils import qty_str

        product = request.query_params.get("product")
        rows = []
        for lot in stock_lots(request.company):
            if product and str(lot.product_id) != product:
                continue
            rows.append({
                "id": lot.id,
                "product": lot.product_id,
                "product_name": lot.product.name,
                "supplier": lot.purchase.mill.mill_name,
                "bill": lot.purchase.invoice_no,
                "date": lot.purchase.purchase_date,
                "pack_size": qty_str(lot.bag_weight),
                "rate": qty_str(lot.purchase_price),
                "left": qty_str(lot.bags_left),
                "unit": lot.product.unit_label,
            })
        return Response(rows)


class PaymentViewSet(CompanyScoped, mixins.ListModelMixin, mixins.RetrieveModelMixin,
                     mixins.CreateModelMixin, mixins.DestroyModelMixin, viewsets.GenericViewSet):
    model = Payment
    serializer_class = s.PaymentSerializer

    def get_queryset(self):
        queryset = (
            self.base_queryset()
            .select_related("customer", "mill", "sale", "purchase")
            .order_by("-payment_date", "-id")
        )
        params = self.request.query_params
        if params.get("type") in ("sale", "purchase", "broker"):
            queryset = queryset.filter(related_type=params["type"])
        for name, field in (("customer", "customer_id"), ("supplier", "mill_id"), ("sale", "sale_id"),
                            ("purchase", "purchase_id")):
            if (params.get(name) or "").isdigit():
                queryset = queryset.filter(**{field: int(params[name])})
        return queryset

    def perform_create(self, serializer):
        serializer.save()

    def perform_destroy(self, instance):
        if not (self.request.user.is_superuser or self.request.user_profile.role in WRITE_ROLES):
            raise PermissionDenied("Only a manager or the owner can delete a payment.")
        instance.delete()


# --------------------------------------------------------------------------
# Dashboard and reports
# --------------------------------------------------------------------------

def _period(request):
    """(start, end) for ?period=today|month|last_month|fy (default: this month)."""
    from core.services.dashboard import period_range

    period = period_range(request.query_params.get("period") or "month")
    return period["start"], period["end"]


def _plain(value):
    if isinstance(value, Decimal):
        return str(value)
    return value


@api_view(["GET"])
@permission_classes(DEFAULT)
def dashboard(request):
    from core.services.dashboard import mill_dues, period_kpis, receivables

    company = request.company
    start, end = _period(request)
    kpis = period_kpis(company, start, end)
    recv = receivables(company)
    dues = mill_dues(company)

    return Response({
        "period": {"from": start, "to": end},
        "kpis": {key: _plain(value) for key, value in kpis.items() if not isinstance(value, (list, dict))},
        "receivable_total": _money(recv["total_due"]),
        "payable_total": _money(dues["total"]),
        "top_dues": [
            {"customer": row["customer"].id, "name": row["customer"].customer_name, "due": _money(row["due"])}
            for row in sorted(recv["by_customer"].values(), key=lambda r: r["due"], reverse=True)[:5]
            if row["due"] > 0
        ],
        "recent_sales": s.SaleSerializer(
            Sale.objects.for_company(company).select_related("customer")
            .prefetch_related("items__product").order_by("-sale_date", "-id")[:5],
            many=True, context={"request": request},
        ).data,
        "today": timezone.localdate(),
    })


@api_view(["GET"])
@permission_classes(DEFAULT)
def receivables_report(request):
    from core.services.dashboard import receivables

    recv = receivables(request.company)
    return Response({
        "total_due": _money(recv["total_due"]),
        "customers": [
            {"customer": row["customer"].id, "name": row["customer"].customer_name, "due": _money(row["due"])}
            for row in sorted(recv["by_customer"].values(), key=lambda r: r["due"], reverse=True)
            if row["due"] > 0
        ],
        "ageing": [
            {"key": b["key"], "label": str(b["label"]), "amount": _money(b["amount"]), "count": b["count"]}
            for b in recv["buckets"]
        ],
    })


@api_view(["GET"])
@permission_classes(DEFAULT)
def payables_report(request):
    from core.services.dashboard import mill_dues

    dues = mill_dues(request.company)
    return Response({
        "total_due": _money(dues["total"]),
        "suppliers": [
            {"supplier": row["mill"].id, "name": row["mill"].mill_name, "due": _money(row["due"])}
            for row in dues["rows"]
        ],
    })


@api_view(["GET"])
@permission_classes(DEFAULT)
def summary_report(request):
    """Sales, purchases, profit and GST for a period (?period=this_month|last_month|this_year...)."""
    from core.services.dashboard import period_kpis

    start, end = _period(request)
    kpis = period_kpis(request.company, start, end)
    return Response({
        "period": {"from": start, "to": end},
        **{key: _plain(value) for key, value in kpis.items() if not isinstance(value, (list, dict))},
    })
