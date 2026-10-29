from decimal import Decimal, ROUND_HALF_UP

from django.db import models
from django.contrib.auth.models import User
from django.utils.translation import gettext_lazy as _

from .tenancy import TenantManager



# Create your models here.


class Company(models.Model):
    company_name = models.CharField(max_length=200)
    owner_name = models.CharField(max_length=200)

    email = models.EmailField(blank=True)
    mobile = models.CharField(max_length=20)

    # Company Details
    gst_number = models.CharField(max_length=20, blank=True)
    address = models.TextField(blank=True)
    city = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=100, blank=True)
    country = models.CharField(max_length=100, default="India")
    pincode = models.CharField(max_length=10, blank=True)

    pan_number = models.CharField(max_length=20, blank=True)

    # Optional Logo
    logo = models.ImageField(
        upload_to="company_logo/",
        blank=True,
        null=True
    )

    # ---------------------------------------------------------------
    # Invoice identity. These used to live as constants in settings.py,
    # which meant every tenant printed the same name on their bills.
    # ---------------------------------------------------------------
    invoice_prefix = models.CharField(
        max_length=10,
        default="SAL",
        help_text="Shown at the start of every sale invoice number, e.g. SAL-20260927-0001",
    )

    bank_account_name = models.CharField(max_length=150, blank=True)
    bank_account_no = models.CharField(max_length=30, blank=True)
    bank_name = models.CharField(max_length=100, blank=True)
    bank_ifsc = models.CharField(max_length=20, blank=True)
    bank_branch = models.CharField(max_length=100, blank=True)
    upi_id = models.CharField(max_length=100, blank=True)

    invoice_terms = models.TextField(
        blank=True,
        help_text="Terms and conditions printed at the bottom of the invoice.",
    )

    # Loading / hamali you pay per kg when a truck is loaded, e.g. 0.10.
    # Filled into each sale as weight x rate; can be changed per truck.
    default_loading_rate_per_kg = models.DecimalField(
        max_digits=8,
        decimal_places=3,
        default=0,
        help_text="Loading charge per kg, used to fill the loading charge on a sale.",
    )

    default_margin_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=8,
        help_text="Used to suggest a selling price from the landed cost.",
    )

    # What the business trades in. Only used to seed sensible units and
    # categories for a new company - nothing in the app is tied to it, so a
    # rice trader and a biscuit distributor run the same code.
    INDUSTRY_CHOICES = [
        ("general", _("General trading")),
        ("rice", _("Rice / grain trading")),
        ("agri", _("Agricultural commodities")),
        ("fmcg", _("FMCG distribution")),
        ("biscuit", _("Biscuit / confectionery distribution")),
        ("grocery", _("Grocery wholesale")),
        ("packaging", _("Packaging materials")),
        ("building", _("Building materials")),
    ]
    industry = models.CharField(max_length=20, choices=INDUSTRY_CHOICES, default="general")

    # The freight arrangement a new sale starts with (see Sale.FREIGHT_CHOICES).
    default_freight_mode = models.CharField(max_length=10, default="us")

    # Subscription (kept in step with the billing app's Subscription row)
    subscription_start = models.DateField()
    subscription_end = models.DateField()

    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.company_name

class Customer(models.Model):
    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name="customers"
    )

    customer_name = models.CharField(max_length=150)

    mobile = models.CharField(
        max_length=20,
        blank=True
    )

    email = models.EmailField(
        blank=True
    )

    gst_number = models.CharField(
        max_length=20,
        blank=True
    )

    billing_address = models.TextField(
        blank=True
    )

    shipping_address = models.TextField(
            blank=True
        )

    city = models.CharField(
        max_length=100,
        blank=True
    )

    state = models.CharField(
        max_length=100,
        blank=True
    )

    country = models.CharField(
        max_length=100,
        default="India"
    )

    pincode = models.CharField(
        max_length=10,
        blank=True
    )

    opening_balance = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0
    )

    # Cash discount (CD) this party usually takes off the bill when paying,
    # e.g. 1.5%. Filled into each new sale, where it can be changed.
    default_cash_discount_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0
    )

    is_active = models.BooleanField(
        default=True
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    updated_at = models.DateTimeField(
        auto_now=True
    )

    objects = TenantManager()

    def __str__(self):
        return self.customer_name

    @property
    def whatsapp_number(self):
        """Digits only, with the country code, for a wa.me link."""
        digits = "".join(ch for ch in (self.mobile or "") if ch.isdigit())
        if len(digits) == 10:
            return "91" + digits
        return digits

    @property
    def full_billing_address(self):
        parts = [self.billing_address, self.city, self.state, self.pincode]
        return ", ".join(p.strip() for p in parts if p and p.strip())

    @property
    def full_shipping_address(self):
        if (self.shipping_address or "").strip():
            return self.shipping_address.strip()
        return self.full_billing_address

class Unit(models.Model):
    """
    A unit the business counts or prices goods in: Bag, Box, Carton, Kg,
    Litre, or anything else the owner defines. Each company keeps its own list.
    """

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="units")
    name = models.CharField(max_length=40)
    symbol = models.CharField(max_length=12, help_text="Short form printed on bills, e.g. kg, pcs, ctn.")
    # Kg and litres can be split (12.345 kg); boxes and pieces usually cannot.
    allow_decimal = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)

    objects = TenantManager()

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["company", "name"], name="unique_unit_name_per_company"),
        ]

    def __str__(self):
        return self.symbol or self.name


class ProductCategory(models.Model):
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="product_categories")
    name = models.CharField(max_length=80)
    is_active = models.BooleanField(default=True)

    objects = TenantManager()

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "product categories"
        constraints = [
            models.UniqueConstraint(fields=["company", "name"], name="unique_category_name_per_company"),
        ]

    def __str__(self):
        return self.name


class Product(models.Model):
    """
    Anything the business buys and sells.

    Quantities are kept in two units, which is how goods really move:

        pack unit  - what you count: bags, boxes, cartons, pieces
        rate unit  - what the price is per: kg, litre, piece, box
        pack size  - rate units in one pack (50 kg per bag, 24 pcs per carton)

        line value = packs x pack size x rate

    When both units are the same (sold per box, priced per box) the pack size
    is simply 1.
    """

    company = models.ForeignKey(
    Company,
    on_delete=models.CASCADE,
    related_name="products"
    )
    name = models.CharField(max_length=100)
    sku = models.CharField(max_length=40, blank=True)
    category = models.ForeignKey(
        ProductCategory, on_delete=models.SET_NULL, null=True, blank=True, related_name="products"
    )
    unit = models.ForeignKey(
        Unit, on_delete=models.PROTECT, null=True, blank=True, related_name="+",
        help_text="What you count: bag, box, carton, piece...",
    )
    rate_unit = models.ForeignKey(
        Unit, on_delete=models.PROTECT, null=True, blank=True, related_name="+",
        help_text="What the rate is per: kg, litre, piece...",
    )
    default_pack_size = models.DecimalField(
        max_digits=12, decimal_places=3, default=1,
        help_text="Rate units in one pack, e.g. 50 (kg per bag) or 24 (pieces per carton).",
    )
    hsn_code = models.CharField(max_length=20, blank=True)
    gst_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    objects = TenantManager()

    def __str__(self):
        return self.name

    @property
    def unit_label(self):
        """Short name of the pack unit, e.g. "bag" - "nos" (numbers) when none is set."""
        return str(self.unit) if self.unit_id else "nos"

    @property
    def rate_unit_label(self):
        return str(self.rate_unit) if self.rate_unit_id else self.unit_label

class Mill(models.Model):
    company = models.ForeignKey(
    Company,
    on_delete=models.CASCADE,
    related_name="mills"
    )
    mill_name = models.CharField(max_length=150)
    owner_name = models.CharField(max_length=100, blank=True)
    mobile = models.CharField(max_length=15)
    address = models.TextField(blank=True)
    city = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=100, blank=True)
    gst_number = models.CharField(max_length=20, blank=True)
    opening_balance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    notes = models.TextField(blank=True)

    # A mill is never deleted once it has purchases - it is deactivated, so the
    # purchase history and the stock that came from it stay intact. Inactive
    # mills disappear from the dropdowns but keep all their records.
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True, null=True)

    objects = TenantManager()

    class Meta:
        ordering = ["mill_name"]
        # "Mill" is the original rice-trade name; on screen it is a supplier.
        verbose_name = "supplier"

    def __str__(self):
        return self.mill_name

    @property
    def whatsapp_number(self):
        """Digits only, with the country code, for a wa.me link."""
        digits = "".join(ch for ch in (self.mobile or "") if ch.isdigit())
        if len(digits) == 10:
            return "91" + digits
        return digits

    def can_be_deleted(self):
        """True only when nothing depends on this mill."""
        return not (
            self.purchase_set.exists()
            or self.payment_set.exists()
            or self.saleitem_set.exists()
            or self.salelot_set.exists()
        )
    
class Purchase(models.Model):
    """
    One bill received from a mill.

    Money on a purchase is built up like this:

        goods value (sum of the item lines)
          - discount
          = taxable amount
          + CGST + SGST   (same state)   or   IGST (other state)   or nothing
          + freight + labour
          + round off
          = total amount you owe the mill
    """

    NO_TAX = "none"
    CGST_SGST = "cgst_sgst"
    IGST = "igst"

    TAX_TYPES = [
        (NO_TAX, _("No GST (kacha bill)")),
        (CGST_SGST, _("CGST + SGST (same state)")),
        (IGST, _("IGST (other state)")),
    ]

    company = models.ForeignKey(
    Company,
    on_delete=models.CASCADE,
    related_name="purchases"
    )
    mill = models.ForeignKey(Mill, on_delete=models.CASCADE)

    # The number printed on the MILL'S bill - typed in by the user.
    invoice_no = models.CharField(max_length=50)

    # Our own reference, generated per company: PUR-20260927-0001. Useful when a
    # supplier's bill has no number, or the same number is used twice.
    purchase_ref = models.CharField(max_length=30, blank=True)

    purchase_date = models.DateField()

    tax_type = models.CharField(max_length=20, choices=TAX_TYPES, default=CGST_SGST)

    # Money breakup
    goods_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    discount_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    taxable_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    cgst_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    sgst_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    igst_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    # Charges the MILL put on its own bill - you owe these to the mill.
    # Money you spend yourself (your own truck, your own labour) is kept
    # separately in PurchaseExpense, because it is not owed to the mill.
    freight_charge = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    labour_charge = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    round_off = models.DecimalField(max_digits=6, decimal_places=2, default=0)

    total_amount = models.DecimalField(max_digits=12, decimal_places=2)

    # Manual GST: the supplier's or customer's bill sometimes differs from the
    # calculated tax by a few paise. When filled, these replace the calculated
    # CGST / SGST / IGST and the total is worked out again. Empty = automatic.
    # Every change is also written to TaxAdjustment with the reason.
    manual_cgst = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    manual_sgst = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    manual_igst = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    gst_adjust_reason = models.CharField(max_length=200, blank=True)

    @property
    def gst_is_manual(self):
        return any(v is not None for v in (self.manual_cgst, self.manual_sgst, self.manual_igst))

    notes = models.TextField(blank=True)

    # The supplier's bill as scanned or photographed, kept as proof.
    bill_file = models.FileField(upload_to="purchase_bills/%Y/%m/", blank=True)
    # "manual", or how the entry was filled: "qr", "ai" or "qr+ai".
    entry_source = models.CharField(max_length=10, default="manual", blank=True)
    # GST e-invoice reference number, when the bill's QR code was scanned.
    irn = models.CharField(max_length=80, blank=True)

    created_at = models.DateTimeField(auto_now_add=True, null=True)
    updated_at = models.DateTimeField(auto_now=True, null=True)

    objects = TenantManager()

    class Meta:
        ordering = ["-purchase_date", "-id"]

    def __str__(self):
        return f"{self.invoice_no} - {self.mill.mill_name}"

    @property
    def gst_amount(self):
        return self.cgst_amount + self.sgst_amount + self.igst_amount

    @property
    def paid_amount(self):
        from django.db.models import Sum

        return (
            Payment.objects
            .filter(purchase=self, related_type="purchase")
            .aggregate(total=Sum("amount"))["total"] or 0
        )

    @property
    def due_amount(self):
        due = self.total_amount - self.paid_amount
        return due if due > 0 else 0

    @property
    def total_bags(self):
        from django.db.models import Sum

        return self.purchaseitem_set.aggregate(s=Sum("bag_count"))["s"] or 0

    @property
    def total_kg(self):
        from django.db.models import Sum

        return self.purchaseitem_set.aggregate(s=Sum("total_kg"))["s"] or 0

    @property
    def own_expense_total(self):
        """What you spent yourself on this bill (not owed to the mill)."""
        from django.db.models import Sum

        return self.expenses.aggregate(s=Sum("amount"))["s"] or 0

    @property
    def mill_charge_total(self):
        """Freight and labour the mill charged on its own bill."""
        return self.freight_charge + self.labour_charge

class PurchaseItem(models.Model):
    # This model has no company column of its own; it inherits the tenant of
    # its parent purchase. `company_path` tells TenantManager how to reach it.
    company_path = "purchase__company"

    purchase = models.ForeignKey(Purchase, on_delete=models.CASCADE)
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    # Pack size (rate units per pack, e.g. 50 kg per bag) and number of packs.
    # The names are from the rice days; they hold any unit now.
    bag_weight = models.DecimalField(max_digits=12, decimal_places=3)
    bag_count = models.DecimalField(max_digits=12, decimal_places=3)
    purchase_price = models.DecimalField(max_digits=12, decimal_places=3)   # rate per rate unit

    # GST copied from the product when the bill is entered, so a later change to
    # the product's rate never rewrites an old bill.
    gst_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)

    # Computed once and stored, so reports never have to recalculate them.
    total_kg = models.DecimalField(max_digits=14, decimal_places=3, default=0)   # total in rate units
    taxable_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    gst_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    line_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    objects = TenantManager()

    def __str__(self):
        return f"{self.product.name} x {self.bag_count:g} {self.product.unit_label}"

    def compute(self, discount_share=0):
        """
        Fill in the calculated fields from bags, weight and rate.

        `discount_share` is this line's part of a bill-level discount, so GST is
        charged on the value after discount - which is how a GST bill works.
        """
        from decimal import Decimal

        self.total_kg = Decimal(self.bag_count or 0) * Decimal(self.bag_weight or 0)
        goods = self.total_kg * Decimal(self.purchase_price or 0)

        two = Decimal("0.01")
        taxable = goods - Decimal(discount_share or 0)
        if taxable < 0:
            taxable = Decimal("0")

        # Full precision until the very end, then rounded once to paise.
        self.taxable_amount = taxable.quantize(two, rounding=ROUND_HALF_UP)
        self.gst_amount = (taxable * Decimal(self.gst_percent or 0) / Decimal("100")).quantize(two, rounding=ROUND_HALF_UP)
        self.line_total = self.taxable_amount + self.gst_amount

        return self

class Broker(models.Model):
    """
    A middleman who brings buyers. The invoice still goes to the customer; the
    broker only earns a commission on the sales he brings, which you owe him.
    """

    PER_BAG = "per_bag"
    PER_KG = "per_kg"
    PER_QUINTAL = "per_quintal"
    PERCENT = "percent"

    COMMISSION_TYPES = [
        (PER_KG, _("₹ per rate unit (kg, litre, piece...)")),
        (PER_BAG, _("₹ per pack (bag, box, carton...)")),
        (PER_QUINTAL, _("₹ per 100 rate units (quintal)")),
        (PERCENT, _("% of sale value (before GST)")),
    ]

    company = models.ForeignKey(
    Company,
    on_delete=models.CASCADE,
    related_name="brokers"
    )
    broker_name = models.CharField(max_length=150)
    mobile = models.CharField(max_length=15, blank=True)
    address = models.TextField(blank=True)
    city = models.CharField(max_length=100, blank=True)
    gst_number = models.CharField(max_length=20, blank=True)

    # The usual deal with this broker. Copied onto each sale, where it can be
    # changed for that one truck without touching the broker's default.
    commission_type = models.CharField(max_length=20, choices=COMMISSION_TYPES, default=PER_KG)
    commission_rate = models.DecimalField(max_digits=12, decimal_places=3, default=0)

    # Cash discount (CD) the broker takes off sales he brings, e.g. 1.5%.
    default_cash_discount_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)

    # Commission you already owed this broker before using this software.
    opening_balance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    notes = models.TextField(blank=True)

    # Like mills, a broker with history is deactivated, never deleted.
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True, null=True)

    objects = TenantManager()

    class Meta:
        ordering = ["broker_name"]

    def __str__(self):
        return self.broker_name

    @property
    def whatsapp_number(self):
        digits = "".join(ch for ch in (self.mobile or "") if ch.isdigit())
        if len(digits) == 10:
            return "91" + digits
        return digits

    def can_be_deleted(self):
        return not (self.sale_set.exists() or self.payments.exists())


class Sale(models.Model):
    """
    One sale invoice - usually one truck.

    Money on a sale is built up the same way as a purchase:

        sum of the invoice lines (bags x bag weight x rate)
          = taxable amount
          + CGST + SGST (same state) or IGST (other state) or nothing
          + round off
          = invoice total the customer owes you (rice only)

    Transport is kept separate: it is shown on the invoice for information but
    is settled between the customer and the truck, not added to your bill.
    """

    NO_TAX = "none"
    CGST_SGST = "cgst_sgst"
    IGST = "igst"

    TAX_TYPES = [
        (NO_TAX, _("No GST (bill of supply)")),
        (CGST_SGST, _("CGST + SGST (same state)")),
        (IGST, _("IGST (other state)")),
    ]

    company = models.ForeignKey(
    Company,
    on_delete=models.CASCADE,
    related_name="sales"
    )
    invoice_no = models.CharField(max_length=30, blank=True)

    # The buyer. Old sales typed the name by hand and have no link; the
    # migration linked them by name where it could.
    customer = models.ForeignKey(
        Customer,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="sales",
    )

    # A copy of the buyer's details as they were on the day of the sale, so a
    # later change to the customer never rewrites an invoice already given.
    customer_name = models.CharField(max_length=150)
    customer_gst = models.CharField(max_length=20, blank=True, null=True)
    billing_address = models.TextField(blank=True)
    shipping_address = models.TextField(blank=True)
    place_of_supply = models.CharField(max_length=100, blank=True)

    broker = models.ForeignKey("Broker", on_delete=models.SET_NULL, null=True, blank=True)

    # Who pays you for this truck. A direct sale is paid by the customer; on a
    # broker sale the broker collects from the party, keeps his brokerage,
    # takes off the CD and pays you the rest - so the broker owes you.
    COLLECT_FROM_CUSTOMER = "customer"
    COLLECT_FROM_BROKER = "broker"
    COLLECT_FROM_CHOICES = [
        (COLLECT_FROM_CUSTOMER, _("Customer pays us")),
        (COLLECT_FROM_BROKER, _("Broker pays us (after CD and brokerage)")),
    ]
    collect_from = models.CharField(max_length=10, choices=COLLECT_FROM_CHOICES, default=COLLECT_FROM_CUSTOMER)

    # The broker's commission on this sale - owed BY you TO the broker.
    broker_commission_type = models.CharField(
        max_length=20, choices=Broker.COMMISSION_TYPES, blank=True, default=""
    )
    broker_commission_rate = models.DecimalField(max_digits=12, decimal_places=3, default=0)
    broker_commission = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    sale_date = models.DateField()
    due_date = models.DateField(null=True, blank=True)

    vehicle_number = models.CharField(max_length=20, blank=True)
    driver_name = models.CharField(max_length=100, blank=True)
    driver_mobile = models.CharField(max_length=15, blank=True)
    transporter_name = models.CharField(max_length=100, blank=True)

    # Who carries the freight. The stored values are kept from the first
    # version ("us", "customer", "separate") so old sales read the same.
    #
    #   us        A  seller pays it all (FOR delivery) - a business expense
    #   customer  B  buyer pays it all - it is added to the invoice
    #   shared    C  split - the buyer's share is added to the invoice
    #   bill      D  buyer pays, billed on a separate transport invoice
    #   included  E  already inside the sale rate - nothing shown on the bill
    #   separate     settled between the buyer and the truck, not in your books
    #
    # Whoever physically paid the driver, the books come out right:
    #   buyer owes for freight = buyer's share - what the buyer paid the driver
    #   your freight cost      = total freight - buyer's share
    FREIGHT_US = "us"
    FREIGHT_CUSTOMER = "customer"
    FREIGHT_SHARED = "shared"
    FREIGHT_BILL = "bill"
    FREIGHT_INCLUDED = "included"
    FREIGHT_SEPARATE = "separate"
    FREIGHT_CHOICES = [
        (FREIGHT_US, _("A - Seller pays freight (FOR delivery)")),
        (FREIGHT_CUSTOMER, _("B - Buyer pays freight (added to invoice)")),
        (FREIGHT_SHARED, _("C - Shared (buyer's share added to invoice)")),
        (FREIGHT_BILL, _("D - Separate transport invoice to buyer")),
        (FREIGHT_INCLUDED, _("E - Freight included in the sale rate")),
        (FREIGHT_SEPARATE, _("Buyer settles directly with the transporter")),
    ]
    # Freight that appears on the goods invoice itself.
    FREIGHT_ON_INVOICE = (FREIGHT_CUSTOMER, FREIGHT_SHARED)
    freight_borne_by = models.CharField(max_length=10, choices=FREIGHT_CHOICES, default=FREIGHT_US)

    # Total freight for the trip, typed in. When empty it is worked out from
    # the rate per ton, or from what was paid to the driver.
    freight_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    # Scenario C: the buyer's part of the freight, in rupees.
    freight_customer_share = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    # Freight added to the goods invoice total (B and C). Computed on save.
    freight_on_invoice = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    # Scenario D: the number of the separate transport invoice.
    transport_invoice_no = models.CharField(max_length=30, blank=True)

    # Loading / hamali paid at the mill for this truck - your cost.
    loading_charge = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    # The truck's weight from the weighbridge at loading, when it differs
    # from bags x bag weight. Empty = bags x bag weight.
    loading_weight_kg = models.DecimalField(max_digits=14, decimal_places=3, null=True, blank=True)

    # ✅ Transport is separate
    transport_rate_per_ton = models.DecimalField(max_digits=12, decimal_places=3, default=0)
    transport_charge = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    transport_paid_by_dealer = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    transport_paid_by_customer = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    tax_type = models.CharField(max_length=20, choices=TAX_TYPES, default=CGST_SGST)

    # ✅ Rice selling totals only (NOT include transport)
    total_bags = models.DecimalField(max_digits=14, decimal_places=3, default=0)   # packs
    total_quantity_kg = models.DecimalField(max_digits=14, decimal_places=3)       # rate units
    taxable_amount = models.DecimalField(max_digits=12, decimal_places=2)
    # Kept for old single-rate sales; each line now carries its own GST %.
    gst_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    cgst_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    sgst_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    igst_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    gst_amount = models.DecimalField(max_digits=12, decimal_places=2)
    round_off = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2)  # goods + freight_on_invoice

    # Manual GST: the supplier's or customer's bill sometimes differs from the
    # calculated tax by a few paise. When filled, these replace the calculated
    # CGST / SGST / IGST and the total is worked out again. Empty = automatic.
    # Every change is also written to TaxAdjustment with the reason.
    manual_cgst = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    manual_sgst = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    manual_igst = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    gst_adjust_reason = models.CharField(max_length=200, blank=True)

    @property
    def gst_is_manual(self):
        return any(v is not None for v in (self.manual_cgst, self.manual_sgst, self.manual_igst))

    # ---- settlement, after the truck is unloaded at the party ----
    # The party pays on the weight they received, takes their cash discount
    # (CD) and, when they pay the broker themselves, cuts the brokerage.
    unload_date = models.DateField(null=True, blank=True)
    received_weight_kg = models.DecimalField(max_digits=14, decimal_places=3, null=True, blank=True)
    cash_discount_percent = models.DecimalField(max_digits=6, decimal_places=3, default=0)
    cash_discount_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    BROKER_PAID_BY_US = "us"
    BROKER_PAID_BY_CUSTOMER = "customer"
    BROKER_PAID_BY_CHOICES = [
        (BROKER_PAID_BY_US, _("We pay the broker")),
        (BROKER_PAID_BY_CUSTOMER, _("Party pays the broker (cut from their payment)")),
    ]
    broker_paid_by = models.CharField(max_length=10, choices=BROKER_PAID_BY_CHOICES, default=BROKER_PAID_BY_US)

    other_deductions = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    other_deductions_note = models.CharField(max_length=150, blank=True)

    # What the party actually owes you after all of the above - the figure the
    # customer ledger uses. Equal to total_amount until the truck is settled.
    net_receivable = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    # Money received while making the sale. Later money is a Payment row.
    advance_received = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    advance_mode = models.CharField(max_length=50, blank=True)
    # total_amount - advance_received, as it was at the moment of saving. The
    # real outstanding (after later payments) comes from the customer ledger.
    balance_amount = models.DecimalField(max_digits=12, decimal_places=2)  # ✅ rice due only

    notes = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True, null=True)

    objects = TenantManager()

    class Meta:
        ordering = ["-sale_date", "-id"]
        # Each company runs its own invoice series, so the same number may
        # legitimately exist in two different companies.
        constraints = [
            models.UniqueConstraint(
                fields=["company", "invoice_no"],
                name="unique_sale_invoice_no_per_company",
            )
        ]

    def __str__(self):
        return f"{self.invoice_no} - {self.customer_name}"

    @property
    def goods_total(self):
        """The invoice total without the freight added to it."""
        return (self.total_amount or Decimal("0")) - (self.freight_on_invoice or Decimal("0"))

    @property
    def has_transport_invoice(self):
        return self.freight_borne_by == self.FREIGHT_BILL and (self.transport_charge or 0) > 0

    @property
    def transport_due(self):
        due = self.transport_charge - (self.transport_paid_by_dealer + self.transport_paid_by_customer)
        return due if due > 0 else Decimal("0")

    @property
    def total_ton(self):
        return (self.total_quantity_kg or Decimal("0")) / Decimal("1000")

    @property
    def is_tax_invoice(self):
        return self.tax_type != self.NO_TAX and (self.gst_amount or 0) > 0

    @property
    def is_unloaded(self):
        return bool(self.unload_date)

    @property
    def weight_loss_kg(self):
        if self.received_weight_kg is None:
            return None
        return (self.total_quantity_kg or Decimal("0")) - self.received_weight_kg


class SaleItem(models.Model):
    """
    One line on the customer's invoice: which rice, how many bags, at what
    SELLING rate. These lines are what the customer sees and what takes stock
    out (stock = bags bought - bags sold).
    """

    company_path = "sale__company"

    sale = models.ForeignKey(Sale, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(Product, on_delete=models.PROTECT)

    # Old sales stored one mill per line. New sales record where the bags came
    # from in SaleLot instead, because one line can come out of several lots.
    mill = models.ForeignKey(Mill, on_delete=models.PROTECT, null=True, blank=True)

    # The purchase lot the user picked for this line. Empty = take the oldest
    # stock first (FIFO), which may span several lots.
    purchase_item = models.ForeignKey(
        PurchaseItem, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    # Pack size and number of packs (see Product for the two units).
    bag_weight = models.DecimalField(max_digits=12, decimal_places=3)
    bag_count = models.DecimalField(max_digits=12, decimal_places=3)

    # SELLING rate per rate unit (kg, piece, litre...), before GST.
    rate_per_kg = models.DecimalField(max_digits=12, decimal_places=3, default=0)
    gst_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)

    total_weight = models.DecimalField(max_digits=14, decimal_places=3, default=0)

    # Selling value before GST (bags x bag weight x rate).
    amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    gst_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    line_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    objects = TenantManager()

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.sale.invoice_no} - {self.product.name} x {self.bag_count:g}"

    def compute(self):
        self.total_weight = Decimal(self.bag_count or 0) * Decimal(self.bag_weight or 0)
        self.amount = (self.total_weight * Decimal(self.rate_per_kg or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        self.gst_amount = (self.amount * Decimal(self.gst_percent or 0) / Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        self.line_total = self.amount + self.gst_amount
        return self


class SaleLot(models.Model):
    """
    Where the bags of a sale line physically came from - the owner's private
    record. The customer never sees it.

    It ties every bag sold to the purchase lot it was bought in, which gives:
      - stock per lot (bought in that lot - sold out of it)
      - the real cost of this sale, so the profit is honest
    """

    company_path = "sale__company"

    sale = models.ForeignKey(Sale, on_delete=models.CASCADE, related_name="lots")
    sale_item = models.ForeignKey(SaleItem, on_delete=models.CASCADE, related_name="lots")
    purchase_item = models.ForeignKey(PurchaseItem, on_delete=models.PROTECT, related_name="sale_lots")
    mill = models.ForeignKey(Mill, on_delete=models.PROTECT)

    bag_count = models.DecimalField(max_digits=12, decimal_places=3)
    total_kg = models.DecimalField(max_digits=14, decimal_places=3, default=0)

    # Rate on the mill's bill, and the landed cost per kg (bill rate + transport,
    # labour and other expenses of that purchase, GST excluded).
    buy_rate_per_kg = models.DecimalField(max_digits=12, decimal_places=3, default=0)
    cost_per_kg = models.DecimalField(max_digits=14, decimal_places=4, default=0)
    cost_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    objects = TenantManager()

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.sale.invoice_no}: {self.bag_count:g} from lot {self.purchase_item_id}"


class Payment(models.Model):
    company = models.ForeignKey(
    Company,
    on_delete=models.CASCADE,
    related_name="payments"
    )
    PAYMENT_TYPE = [
        ("sale", _("Received from customer")),
        ("purchase", _("Paid to supplier")),
        ("broker", _("Commission paid to broker")),
    ]

    related_type = models.CharField(max_length=10, choices=PAYMENT_TYPE)
    mill = models.ForeignKey(Mill, on_delete=models.CASCADE, null=True, blank=True)
    purchase = models.ForeignKey(Purchase, on_delete=models.CASCADE, null=True, blank=True)
    sale = models.ForeignKey(Sale, on_delete=models.CASCADE, null=True, blank=True)

    # Money received from a customer without naming an invoice ("on account")
    # has a customer but no sale; it is applied to the oldest unpaid invoices.
    customer = models.ForeignKey(
        Customer, on_delete=models.CASCADE, null=True, blank=True, related_name="payments"
    )
    broker = models.ForeignKey(
        Broker, on_delete=models.CASCADE, null=True, blank=True, related_name="payments"
    )

    amount = models.DecimalField(max_digits=12, decimal_places=2)
    payment_mode = models.CharField(max_length=50)  # Cash, Bank, UPI
    payment_date = models.DateField()
    notes = models.TextField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)

    objects = TenantManager()

    def __str__(self):
        return f"{self.related_type} payment - {self.amount}"


class UserProfile(models.Model):

    ROLE_CHOICES = (
        ("owner", _("Owner")),
        ("manager", _("Manager")),
        ("staff", _("Staff")),
    )

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE
    )

    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE
    )

    role = models.CharField(
        max_length=20,
        choices=ROLE_CHOICES,
        default="staff"
    )

    phone = models.CharField(
        max_length=20,
        blank=True
    )

    designation = models.CharField(
        max_length=100,
        blank=True
    )

    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)

    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.user.username

class InvoiceSequence(models.Model):
    """
    One row per company per number series, used to hand out sale invoice
    numbers safely when two users save at the same moment.

    The old code did `Sale.objects.filter(...).order_by("-id").first()` across
    ALL companies, which mixed tenants together and could hand the same number
    to two people at once.
    """

    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name="invoice_sequences",
    )

    # e.g. "SAL-20260927" - prefix plus the day the series belongs to
    key = models.CharField(max_length=40)

    last_number = models.PositiveIntegerField(default=0)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["company", "key"],
                name="unique_invoice_sequence_per_company_key",
            )
        ]

    def __str__(self):
        return f"{self.company_id}:{self.key} = {self.last_number}"


class PurchaseExpense(models.Model):
    """
    Money YOU spend to bring a purchase home - not owed to the mill.

    Transport you arranged, labour you paid, loading, brokerage. These never
    touch the mill's balance, but they are part of what the rice really cost
    you, so they belong in the cost per kg.
    """

    company_path = "purchase__company"

    TRANSPORT = "transport"
    LABOUR = "labour"
    LOADING = "loading"
    UNLOADING = "unloading"
    BROKERAGE = "brokerage"
    PACKING = "packing"
    OTHER = "other"

    CATEGORIES = [
        (TRANSPORT, _("Transport / freight")),
        (LABOUR, _("Labour / hamali")),
        (LOADING, _("Loading")),
        (UNLOADING, _("Unloading")),
        (BROKERAGE, _("Brokerage / commission")),
        (PACKING, _("Packing / bags")),
        (OTHER, _("Other")),
    ]

    purchase = models.ForeignKey(
        Purchase,
        on_delete=models.CASCADE,
        related_name="expenses",
    )

    category = models.CharField(max_length=20, choices=CATEGORIES, default=TRANSPORT)

    amount = models.DecimalField(max_digits=12, decimal_places=2)

    paid_to = models.CharField(
        max_length=150,
        blank=True,
        help_text="Truck owner, labour contractor, broker...",
    )

    payment_mode = models.CharField(max_length=50, blank=True)

    expense_date = models.DateField(null=True, blank=True)

    notes = models.CharField(max_length=200, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    objects = TenantManager()

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.get_category_display()} - {self.amount}"


class TaxAdjustment(models.Model):
    """
    Audit trail of every manual GST change: what the app calculated, what the
    user typed instead, who did it, and why.
    """

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="tax_adjustments")
    sale = models.ForeignKey(Sale, on_delete=models.CASCADE, null=True, blank=True, related_name="tax_adjustments")
    purchase = models.ForeignKey(Purchase, on_delete=models.CASCADE, null=True, blank=True, related_name="tax_adjustments")
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)

    calculated_cgst = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    calculated_sgst = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    calculated_igst = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    entered_cgst = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    entered_sgst = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    entered_igst = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    reason = models.CharField(max_length=200, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    objects = TenantManager()

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        target = self.sale or self.purchase
        return f"GST adjusted on {target}: {self.reason}"

    @property
    def difference(self):
        calculated = self.calculated_cgst + self.calculated_sgst + self.calculated_igst
        entered = sum(
            (v if v is not None else c)
            for v, c in (
                (self.entered_cgst, self.calculated_cgst),
                (self.entered_sgst, self.calculated_sgst),
                (self.entered_igst, self.calculated_igst),
            )
        )
        return entered - calculated
