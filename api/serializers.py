"""
JSON shapes for the mobile app.

Field names here are the generic ones (quantity, pack_size, rate, supplier)
even where the database still uses the original rice-trade names
(bag_count, bag_weight, rate_per_kg, mill). The mobile app never sees those.

Money is sent as strings ("1234.50") so no paisa is lost to floating point;
quantities and rates carry up to 3 decimals.
"""

from decimal import Decimal

from django.db import transaction
from rest_framework import serializers

from core.models import (
    Customer, Mill, Payment, Product, ProductCategory, Purchase, PurchaseItem,
    Sale, SaleItem, Unit,
)

MONEY = {"max_digits": 12, "decimal_places": 2}
QTY = {"max_digits": 12, "decimal_places": 3}


def _company(serializer):
    return serializer.context["request"].company


def _own(serializer, model, value, label):
    """Refuse ids that belong to another company."""
    if value is not None and value.company_id != _company(serializer).id:
        raise serializers.ValidationError(f"Unknown {label}.")
    return value


# --------------------------------------------------------------------------
# Masters
# --------------------------------------------------------------------------

class UnitSerializer(serializers.ModelSerializer):
    class Meta:
        model = Unit
        fields = ["id", "name", "symbol", "allow_decimal", "is_active"]

    def validate_name(self, value):
        value = value.strip()
        clash = Unit.objects.filter(company=_company(self), name__iexact=value)
        if self.instance:
            clash = clash.exclude(pk=self.instance.pk)
        if clash.exists():
            raise serializers.ValidationError("This unit already exists.")
        return value


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductCategory
        fields = ["id", "name", "is_active"]

    def validate_name(self, value):
        value = value.strip()
        clash = ProductCategory.objects.filter(company=_company(self), name__iexact=value)
        if self.instance:
            clash = clash.exclude(pk=self.instance.pk)
        if clash.exists():
            raise serializers.ValidationError("This category already exists.")
        return value


class ProductSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source="category.name", read_only=True, default=None)
    unit_label = serializers.CharField(read_only=True)
    rate_unit_label = serializers.CharField(read_only=True)

    class Meta:
        model = Product
        fields = [
            "id", "name", "sku", "category", "category_name", "unit", "unit_label",
            "rate_unit", "rate_unit_label", "default_pack_size", "hsn_code", "gst_percent",
            "description", "is_active",
        ]

    def validate_category(self, value):
        return _own(self, ProductCategory, value, "category")

    def validate_unit(self, value):
        return _own(self, Unit, value, "unit")

    def validate_rate_unit(self, value):
        return _own(self, Unit, value, "unit")

    def validate_name(self, value):
        value = value.strip()
        clash = Product.objects.filter(company=_company(self), name__iexact=value)
        if self.instance:
            clash = clash.exclude(pk=self.instance.pk)
        if clash.exists():
            raise serializers.ValidationError("A product with this name already exists.")
        return value

    def validate(self, attrs):
        if attrs.get("unit") and not attrs.get("rate_unit") and not getattr(self.instance, "rate_unit_id", None):
            attrs["rate_unit"] = attrs["unit"]
        if (attrs.get("default_pack_size") is not None) and attrs["default_pack_size"] <= 0:
            raise serializers.ValidationError({"default_pack_size": "Must be more than zero."})
        return attrs


class CustomerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Customer
        fields = [
            "id", "customer_name", "mobile", "email", "gst_number", "billing_address",
            "shipping_address", "city", "state", "country", "pincode", "opening_balance",
            "default_cash_discount_percent", "is_active",
        ]

    def validate_gst_number(self, value):
        return (value or "").strip().upper()


class SupplierSerializer(serializers.ModelSerializer):
    name = serializers.CharField(source="mill_name", max_length=150)

    class Meta:
        model = Mill
        fields = [
            "id", "name", "owner_name", "mobile", "address", "city", "state",
            "gst_number", "opening_balance", "notes", "is_active",
        ]

    def validate_gst_number(self, value):
        return (value or "").strip().upper()

    def validate_name(self, value):
        value = value.strip()
        clash = Mill.objects.filter(company=_company(self), mill_name__iexact=value)
        if self.instance:
            clash = clash.exclude(pk=self.instance.pk)
        if clash.exists():
            raise serializers.ValidationError("A supplier with this name already exists.")
        return value


# --------------------------------------------------------------------------
# Shared: manual GST
# --------------------------------------------------------------------------

class ManualGSTFields(serializers.Serializer):
    manual_cgst = serializers.DecimalField(**MONEY, required=False, allow_null=True, min_value=Decimal("0"))
    manual_sgst = serializers.DecimalField(**MONEY, required=False, allow_null=True, min_value=Decimal("0"))
    manual_igst = serializers.DecimalField(**MONEY, required=False, allow_null=True, min_value=Decimal("0"))
    gst_adjust_reason = serializers.CharField(required=False, allow_blank=True, max_length=200)

    def check_manual_gst(self, attrs):
        typed = [attrs.get(name) for name in ("manual_cgst", "manual_sgst", "manual_igst")]
        if any(v is not None for v in typed) and not (attrs.get("gst_adjust_reason") or "").strip():
            raise serializers.ValidationError(
                {"gst_adjust_reason": "Say why the GST was changed - it is kept in the audit trail."}
            )
        return attrs


# --------------------------------------------------------------------------
# Purchases
# --------------------------------------------------------------------------

class PurchaseItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)
    unit = serializers.CharField(source="product.unit_label", read_only=True)
    rate_unit = serializers.CharField(source="product.rate_unit_label", read_only=True)
    pack_size = serializers.DecimalField(source="bag_weight", **QTY)
    quantity = serializers.DecimalField(source="bag_count", **QTY)
    rate = serializers.DecimalField(source="purchase_price", **QTY)
    total_units = serializers.DecimalField(source="total_kg", max_digits=14, decimal_places=3, read_only=True)

    class Meta:
        model = PurchaseItem
        fields = [
            "id", "product", "product_name", "unit", "rate_unit", "pack_size", "quantity", "rate",
            "gst_percent", "total_units", "taxable_amount", "gst_amount", "line_total",
        ]
        read_only_fields = ["taxable_amount", "gst_amount", "line_total"]
        extra_kwargs = {"gst_percent": {"required": False}}


class PurchaseSerializer(ManualGSTFields, serializers.ModelSerializer):
    supplier = serializers.PrimaryKeyRelatedField(source="mill", queryset=Mill.objects.all())
    supplier_name = serializers.CharField(source="mill.mill_name", read_only=True)
    items = PurchaseItemSerializer(many=True, source="purchaseitem_set")
    paid_amount = serializers.DecimalField(**MONEY, read_only=True)
    due_amount = serializers.DecimalField(**MONEY, read_only=True)
    amount_paid_now = serializers.DecimalField(**MONEY, write_only=True, required=False, min_value=Decimal("0"))
    payment_mode = serializers.CharField(write_only=True, required=False, allow_blank=True)

    class Meta:
        model = Purchase
        fields = [
            "id", "purchase_ref", "invoice_no", "supplier", "supplier_name", "purchase_date", "tax_type",
            "goods_amount", "discount_amount", "taxable_amount", "cgst_amount", "sgst_amount", "igst_amount",
            "freight_charge", "labour_charge", "round_off", "total_amount", "paid_amount", "due_amount",
            "manual_cgst", "manual_sgst", "manual_igst", "gst_adjust_reason", "notes", "items",
            "amount_paid_now", "payment_mode", "created_at",
        ]
        read_only_fields = [
            "purchase_ref", "goods_amount", "taxable_amount", "cgst_amount", "sgst_amount", "igst_amount",
            "round_off", "total_amount", "created_at",
        ]
        extra_kwargs = {"invoice_no": {"required": False, "allow_blank": True}}

    def validate_supplier(self, value):
        return _own(self, Mill, value, "supplier")

    def validate_items(self, items):
        company = _company(self)
        real = [i for i in items if i.get("bag_count")]
        if not real:
            raise serializers.ValidationError("Add at least one product line.")
        for item in real:
            if item["product"].company_id != company.id:
                raise serializers.ValidationError("Unknown product.")
            if item["bag_weight"] <= 0 or item["bag_count"] <= 0 or item["purchase_price"] <= 0:
                raise serializers.ValidationError("Pack size, quantity and rate must be more than zero.")
        return real

    def validate(self, attrs):
        if attrs.get("amount_paid_now") and not attrs.get("payment_mode"):
            raise serializers.ValidationError({"payment_mode": "Choose how you paid."})
        return self.check_manual_gst(attrs)

    def create(self, data):
        from core.services.gst import record_adjustment
        from core.services.invoice_number import next_purchase_ref, next_supplier_bill_no
        from core.services.purchase_service import apply_totals, calculated_gst

        company = _company(self)
        lines = data.pop("purchaseitem_set")
        paid_now = data.pop("amount_paid_now", None) or 0
        mode = data.pop("payment_mode", "") or "Cash"

        with transaction.atomic():
            purchase = Purchase(company=company, total_amount=0, **data)
            purchase.purchase_ref = next_purchase_ref(company, purchase.purchase_date)
            if not purchase.invoice_no:
                purchase.invoice_no = next_supplier_bill_no(purchase.mill)
            purchase.save()

            items = []
            for line in lines:
                if "gst_percent" not in line:
                    line["gst_percent"] = line["product"].gst_percent
                items.append(PurchaseItem(purchase=purchase, **line))

            apply_totals(
                purchase, items, tax_type=purchase.tax_type,
                discount=purchase.discount_amount or 0,
                freight=purchase.freight_charge or 0, labour=purchase.labour_charge or 0,
            )
            for item in items:
                item.save()
            purchase.save()

            record_adjustment(
                purchase, (None, None, None),
                calculated_gst(items, purchase.tax_type, purchase.discount_amount or 0),
                self.context["request"].user,
            )

            if paid_now > 0:
                Payment.objects.create(
                    company=company, related_type="purchase", mill=purchase.mill, purchase=purchase,
                    amount=paid_now, payment_mode=mode, payment_date=purchase.purchase_date,
                    notes="Paid while entering the bill (mobile app).",
                )
        return purchase


# --------------------------------------------------------------------------
# Sales
# --------------------------------------------------------------------------

class SaleItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)
    unit = serializers.CharField(source="product.unit_label", read_only=True)
    rate_unit = serializers.CharField(source="product.rate_unit_label", read_only=True)
    pack_size = serializers.DecimalField(source="bag_weight", **QTY)
    quantity = serializers.DecimalField(source="bag_count", **QTY)
    rate = serializers.DecimalField(source="rate_per_kg", **QTY)
    total_units = serializers.DecimalField(source="total_weight", max_digits=14, decimal_places=3, read_only=True)
    lot = serializers.PrimaryKeyRelatedField(
        source="purchase_item", queryset=PurchaseItem.objects.all(), required=False, allow_null=True,
    )

    class Meta:
        model = SaleItem
        fields = [
            "id", "product", "product_name", "unit", "rate_unit", "pack_size", "quantity", "rate",
            "gst_percent", "total_units", "amount", "gst_amount", "line_total", "lot",
        ]
        read_only_fields = ["amount", "gst_amount", "line_total"]
        extra_kwargs = {"gst_percent": {"required": False}}


class SaleSerializer(ManualGSTFields, serializers.ModelSerializer):
    customer = serializers.PrimaryKeyRelatedField(queryset=Customer.objects.all())
    items = SaleItemSerializer(many=True)
    freight_mode = serializers.ChoiceField(source="freight_borne_by", choices=Sale.FREIGHT_CHOICES, required=False)
    freight_mode_label = serializers.CharField(source="get_freight_borne_by_display", read_only=True)
    total_quantity = serializers.DecimalField(source="total_bags", max_digits=14, decimal_places=3, read_only=True)
    total_units = serializers.DecimalField(source="total_quantity_kg", max_digits=14, decimal_places=3, read_only=True)
    payment_status = serializers.SerializerMethodField()

    class Meta:
        model = Sale
        fields = [
            "id", "invoice_no", "customer", "customer_name", "customer_gst", "billing_address",
            "shipping_address", "place_of_supply", "sale_date", "due_date", "tax_type",
            "freight_mode", "freight_mode_label", "freight_amount", "freight_customer_share",
            "transport_rate_per_ton", "transport_paid_by_dealer", "transport_paid_by_customer",
            "transport_charge", "freight_on_invoice", "transport_invoice_no",
            "vehicle_number", "driver_name", "driver_mobile", "transporter_name", "loading_charge",
            "total_quantity", "total_units", "taxable_amount", "cgst_amount", "sgst_amount",
            "igst_amount", "gst_amount", "round_off", "total_amount", "cash_discount_percent",
            "cash_discount_amount", "net_receivable", "advance_received", "advance_mode",
            "balance_amount", "payment_status", "manual_cgst", "manual_sgst", "manual_igst",
            "gst_adjust_reason", "notes", "items", "created_at",
        ]
        read_only_fields = [
            "invoice_no", "customer_name", "customer_gst", "billing_address", "shipping_address",
            "place_of_supply", "transport_charge", "freight_on_invoice", "transport_invoice_no",
            "taxable_amount", "cgst_amount", "sgst_amount", "igst_amount", "gst_amount", "round_off",
            "total_amount", "cash_discount_amount", "net_receivable", "balance_amount", "created_at",
        ]

    def get_payment_status(self, sale):
        from core.services.customer_ledger import sale_payment_status

        status = sale_payment_status(_company(self), sale)
        return {key: str(value) if isinstance(value, Decimal) else value for key, value in status.items()
                if isinstance(value, (str, int, float, Decimal, bool)) or value is None}

    def validate_customer(self, value):
        return _own(self, Customer, value, "customer")

    def validate_items(self, items):
        company = _company(self)
        real = [i for i in items if i.get("bag_count")]
        if not real:
            raise serializers.ValidationError("Add at least one product line.")
        for item in real:
            if item["product"].company_id != company.id:
                raise serializers.ValidationError("Unknown product.")
            lot = item.get("purchase_item")
            if lot is not None and lot.purchase.company_id != company.id:
                raise serializers.ValidationError("Unknown stock lot.")
            if item["bag_weight"] <= 0 or item["bag_count"] <= 0 or item["rate_per_kg"] <= 0:
                raise serializers.ValidationError("Pack size, quantity and rate must be more than zero.")
        return real

    def validate(self, attrs):
        if (attrs.get("advance_received") or 0) > 0 and not attrs.get("advance_mode"):
            raise serializers.ValidationError({"advance_mode": "Choose how the money was received."})
        if attrs.get("freight_borne_by", Sale.FREIGHT_US) != Sale.FREIGHT_SHARED:
            attrs["freight_customer_share"] = Decimal("0")
        return self.check_manual_gst(attrs)

    def create(self, data):
        from core.services.gst import record_adjustment
        from core.services.invoice_number import next_sale_invoice_no
        from core.services.sale_service import StockError, calculated_gst, save_sale

        company = _company(self)
        lines = data.pop("items")
        customer = data["customer"]
        data.setdefault("freight_borne_by", company.default_freight_mode or Sale.FREIGHT_US)

        sale = Sale(company=company, **data)
        sale.customer_name = customer.customer_name
        sale.customer_gst = (customer.gst_number or "").upper()
        sale.billing_address = customer.full_billing_address
        sale.shipping_address = customer.full_shipping_address
        sale.place_of_supply = customer.state or ""

        items = []
        for line in lines:
            if "gst_percent" not in line:
                line["gst_percent"] = line["product"].gst_percent
            items.append(SaleItem(**line))

        try:
            with transaction.atomic():
                sale.invoice_no = next_sale_invoice_no(company)
                save_sale(sale, items, company)
        except StockError as error:
            raise serializers.ValidationError({"items": error.messages})

        record_adjustment(sale, (None, None, None), calculated_gst(items, sale.tax_type),
                          self.context["request"].user)
        return sale


# --------------------------------------------------------------------------
# Payments
# --------------------------------------------------------------------------

class PaymentSerializer(serializers.ModelSerializer):
    supplier = serializers.PrimaryKeyRelatedField(
        source="mill", queryset=Mill.objects.all(), required=False, allow_null=True,
    )
    supplier_name = serializers.CharField(source="mill.mill_name", read_only=True, default=None)
    customer_name = serializers.CharField(source="customer.customer_name", read_only=True, default=None)
    sale_invoice_no = serializers.CharField(source="sale.invoice_no", read_only=True, default=None)
    purchase_invoice_no = serializers.CharField(source="purchase.invoice_no", read_only=True, default=None)

    class Meta:
        model = Payment
        fields = [
            "id", "related_type", "customer", "customer_name", "sale", "sale_invoice_no",
            "supplier", "supplier_name", "purchase", "purchase_invoice_no",
            "amount", "payment_mode", "payment_date", "notes", "created_at",
        ]
        read_only_fields = ["created_at"]

    def validate(self, attrs):
        company = _company(self)
        kind = attrs.get("related_type")
        for field, label in (("customer", "customer"), ("sale", "invoice"), ("mill", "supplier"), ("purchase", "bill")):
            value = attrs.get(field)
            if value is not None and value.company_id != company.id:
                raise serializers.ValidationError({field: f"Unknown {label}."})
        if attrs.get("amount") is None or attrs["amount"] <= 0:
            raise serializers.ValidationError({"amount": "Enter an amount above zero."})

        if kind == "sale":
            sale = attrs.get("sale")
            if sale is not None:
                # Same rule as the website: a broker truck's money is the broker's.
                from core.services.customer_ledger import collected_by_broker

                if collected_by_broker(sale):
                    attrs["customer"] = None
                    attrs["broker"] = sale.broker
                else:
                    attrs["customer"] = sale.customer
            elif attrs.get("customer") is None:
                raise serializers.ValidationError({"customer": "Choose the customer or the invoice."})
        elif kind == "purchase":
            purchase = attrs.get("purchase")
            if purchase is not None:
                attrs["mill"] = purchase.mill
            elif attrs.get("mill") is None:
                raise serializers.ValidationError({"supplier": "Choose the supplier or the bill."})
        else:
            raise serializers.ValidationError({"related_type": "Use 'sale' (money in) or 'purchase' (money out)."})
        return attrs

    def create(self, data):
        return Payment.objects.create(company=_company(self), **data)
