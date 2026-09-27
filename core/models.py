from django.db import models
from django.contrib.auth.models import User

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

    default_margin_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=8,
        help_text="Used to suggest a selling price from the landed cost.",
    )

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

class Product(models.Model):
    company = models.ForeignKey(
    Company,
    on_delete=models.CASCADE,
    related_name="products"
    )
    rice_name = models.CharField(max_length=100)
    hsn_code = models.CharField(max_length=20)
    gst_percent = models.IntegerField()
    is_active = models.BooleanField(default=True)

    objects = TenantManager()

    def __str__(self):
        return self.rice_name
    
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
        (NO_TAX, "No GST (kacha bill)"),
        (CGST_SGST, "CGST + SGST (same state)"),
        (IGST, "IGST (other state)"),
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

    notes = models.TextField(blank=True)

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
    bag_weight = models.IntegerField()   # 20 / 30 / 50
    bag_count = models.IntegerField()
    purchase_price = models.DecimalField(max_digits=10, decimal_places=2)   # rate per kg

    # GST copied from the product when the bill is entered, so a later change to
    # the product's rate never rewrites an old bill.
    gst_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)

    # Computed once and stored, so reports never have to recalculate them.
    total_kg = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    taxable_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    gst_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    line_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    objects = TenantManager()

    def __str__(self):
        return f"{self.product.rice_name} x {self.bag_count} bags"

    def compute(self, discount_share=0):
        """
        Fill in the calculated fields from bags, weight and rate.

        `discount_share` is this line's part of a bill-level discount, so GST is
        charged on the value after discount - which is how a GST bill works.
        """
        from decimal import Decimal

        self.total_kg = Decimal(self.bag_count or 0) * Decimal(self.bag_weight or 0)
        goods = self.total_kg * Decimal(self.purchase_price or 0)

        self.taxable_amount = goods - Decimal(discount_share or 0)
        if self.taxable_amount < 0:
            self.taxable_amount = Decimal("0")

        self.gst_amount = self.taxable_amount * Decimal(self.gst_percent or 0) / Decimal("100")
        self.line_total = self.taxable_amount + self.gst_amount

        return self

class Broker(models.Model):
    company = models.ForeignKey(
    Company,
    on_delete=models.CASCADE,
    related_name="brokers"
    )
    broker_name = models.CharField(max_length=150)
    mobile = models.CharField(max_length=15, blank=True)
    address = models.TextField(blank=True)
    gst_number = models.CharField(max_length=20, blank=True)

    opening_balance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = TenantManager()

    def __str__(self):
        return self.broker_name

class Sale(models.Model):
    company = models.ForeignKey(
    Company,
    on_delete=models.CASCADE,
    related_name="sales"
    )
    invoice_no = models.CharField(max_length=30, blank=True)

    customer_name = models.CharField(max_length=100)
    customer_gst = models.CharField(max_length=15, blank=True, null=True)

    broker = models.ForeignKey("Broker", on_delete=models.SET_NULL, null=True, blank=True)

    sale_date = models.DateField()

    vehicle_number = models.CharField(max_length=20)
    driver_name = models.CharField(max_length=100)
    transporter_name = models.CharField(max_length=100)

    # ✅ Transport is separate
    transport_rate_per_ton = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    transport_charge = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    transport_paid_by_dealer = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    transport_paid_by_customer = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    # ✅ Rice selling totals only (NOT include transport)
    total_quantity_kg = models.DecimalField(max_digits=10, decimal_places=2)
    taxable_amount = models.DecimalField(max_digits=12, decimal_places=2)
    gst_percent = models.DecimalField(max_digits=5, decimal_places=2)
    gst_amount = models.DecimalField(max_digits=12, decimal_places=2)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2)  # ✅ rice_total only

    advance_received = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    balance_amount = models.DecimalField(max_digits=12, decimal_places=2)  # ✅ rice due only

    created_at = models.DateTimeField(auto_now_add=True)

    objects = TenantManager()

    class Meta:
        # Each company runs its own invoice series, so the same number may
        # legitimately exist in two different companies.
        constraints = [
            models.UniqueConstraint(
                fields=["company", "invoice_no"],
                name="unique_sale_invoice_no_per_company",
            )
        ]


# class SaleItem(models.Model):
#     sale = models.ForeignKey(Sale, on_delete=models.CASCADE, related_name="items")

#     # ✅ VERY IMPORTANT: link to purchase stock item
#     purchase_item = models.ForeignKey("PurchaseItem", on_delete=models.SET_NULL, null=True, blank=True)

#     product = models.ForeignKey("Product", on_delete=models.CASCADE)
#     mill = models.ForeignKey("Mill", on_delete=models.CASCADE)

#     bag_weight = models.IntegerField()
#     bag_count = models.IntegerField()

#     # ✅ selling (optional to store)
#     sell_rate_per_kg = models.DecimalField(max_digits=10, decimal_places=2, default=0)

#     total_weight = models.DecimalField(max_digits=10, decimal_places=2)
#     sell_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)

#     # ✅ buying (for internal view)
#     buy_rate_per_kg = models.DecimalField(max_digits=10, decimal_places=2, default=0)
#     buy_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)

class SaleItem(models.Model):
    company_path = "sale__company"

    sale = models.ForeignKey(Sale, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    mill = models.ForeignKey(Mill, on_delete=models.CASCADE)

    bag_weight = models.IntegerField()
    bag_count = models.IntegerField()

    # ✅ BUY rate (from purchase stock)
    rate_per_kg = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    total_weight = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    # ✅ BUY amount (bags * bag_weight * rate_per_kg)
    amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    objects = TenantManager()

    def __str__(self):
        return f"{self.sale.invoice_no} - {self.mill.mill_name} - {self.product.rice_name}"


class Payment(models.Model):
    company = models.ForeignKey(
    Company,
    on_delete=models.CASCADE,
    related_name="payments"
    )
    PAYMENT_TYPE = [
        ("sale", "Customer Sale Payment"),
        ("purchase", "Payment to Mill"),
    ]

    related_type = models.CharField(max_length=10, choices=PAYMENT_TYPE)
    mill = models.ForeignKey(Mill, on_delete=models.CASCADE, null=True, blank=True)
    purchase = models.ForeignKey(Purchase, on_delete=models.CASCADE, null=True, blank=True)
    sale = models.ForeignKey(Sale, on_delete=models.CASCADE, null=True, blank=True)
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
        ("owner", "Owner"),
        ("manager", "Manager"),
        ("staff", "Staff"),
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
        (TRANSPORT, "Transport / freight"),
        (LABOUR, "Labour / hamali"),
        (LOADING, "Loading"),
        (UNLOADING, "Unloading"),
        (BROKERAGE, "Brokerage / commission"),
        (PACKING, "Packing / bags"),
        (OTHER, "Other"),
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
