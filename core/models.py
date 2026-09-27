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
    gst_number = models.CharField(max_length=20, blank=True)
    opening_balance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = TenantManager()

    def __str__(self):
        return self.mill_name
    
class Purchase(models.Model):
    company = models.ForeignKey(
    Company,
    on_delete=models.CASCADE,
    related_name="purchases"
    )
    mill = models.ForeignKey(Mill, on_delete=models.CASCADE)
    invoice_no = models.CharField(max_length=50)
    purchase_date = models.DateField()
    total_amount = models.DecimalField(max_digits=12, decimal_places=2)

    objects = TenantManager()

class PurchaseItem(models.Model):
    # This model has no company column of its own; it inherits the tenant of
    # its parent purchase. `company_path` tells TenantManager how to reach it.
    company_path = "purchase__company"

    purchase = models.ForeignKey(Purchase, on_delete=models.CASCADE)
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    bag_weight = models.IntegerField()   # 20 / 30
    bag_count = models.IntegerField()
    purchase_price = models.DecimalField(max_digits=10, decimal_places=2)

    objects = TenantManager()

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
