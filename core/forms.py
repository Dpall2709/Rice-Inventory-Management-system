import re
from decimal import Decimal

from django import forms
from django.contrib.auth.models import User
from django.utils import timezone
from django.utils.formats import date_format
from django.contrib.auth.password_validation import validate_password
from django.utils.translation import gettext_lazy as _

from .models import Broker, Company, Customer, Mill, Product, Purchase, PurchaseItem, Sale, SaleItem



# ==========================================
# Future Public Registration (Keep It)
# ==========================================
class CompanyRegistrationForm(forms.Form):

    company_name = forms.CharField(
        max_length=200,
        widget=forms.TextInput(attrs={
            "class": "form-control",
            "placeholder": _("Company Name")
        })
    )

    owner_name = forms.CharField(
        max_length=200,
        widget=forms.TextInput(attrs={
            "class": "form-control",
            "placeholder": _("Owner Name")
        })
    )

    email = forms.EmailField(
        widget=forms.EmailInput(attrs={
            "class": "form-control",
            "placeholder": _("Email Address")
        })
    )

    mobile = forms.CharField(
        max_length=20,
        widget=forms.TextInput(attrs={
            "class": "form-control",
            "placeholder": _("Mobile Number")
        })
    )

    username = forms.CharField(
        max_length=150,
        widget=forms.TextInput(attrs={
            "class": "form-control",
            "placeholder": _("Username")
        })
    )

    password1 = forms.CharField(
        widget=forms.PasswordInput(attrs={
            "class": "form-control",
            "placeholder": _("Password")
        }),
        validators=[validate_password]
    )

    password2 = forms.CharField(
        widget=forms.PasswordInput(attrs={
            "class": "form-control",
            "placeholder": _("Confirm Password")
        })
    )

    def clean_company_name(self):
        company_name = self.cleaned_data["company_name"]

        if Company.objects.filter(company_name__iexact=company_name).exists():
            raise forms.ValidationError(_("Company already exists."))

        return company_name

    def clean_username(self):
        username = self.cleaned_data["username"]

        if User.objects.filter(username=username).exists():
            raise forms.ValidationError(_("Username already taken."))

        return username

    def clean_email(self):
        email = self.cleaned_data["email"]

        if User.objects.filter(email=email).exists():
            raise forms.ValidationError(_("Email already registered."))

        return email

    def clean(self):
        cleaned_data = super().clean()

        password1 = cleaned_data.get("password1")
        password2 = cleaned_data.get("password2")

        if password1 and password2:
            if password1 != password2:
                raise forms.ValidationError(_("Passwords do not match."))

        return cleaned_data


# ==========================================
# Company Management Form (Admin)
# ==========================================
class CompanyForm(forms.ModelForm):

    class Meta:

        model = Company

        fields = [
            "company_name",
            "owner_name",
            "email",
            "mobile",
            "gst_number",
            "address",
            "city",
            "state",
            "country",
            "pincode",
            "subscription_start",
            "subscription_end",
            "logo",
            "is_active",
        ]

        widgets = {

            "company_name": forms.TextInput(attrs={
                "class": "form-control"
            }),

            "owner_name": forms.TextInput(attrs={
                "class": "form-control"
            }),

            "email": forms.EmailInput(attrs={
                "class": "form-control"
            }),

            "mobile": forms.TextInput(attrs={
                "class": "form-control"
            }),

            "gst_number": forms.TextInput(attrs={
                "class": "form-control"
            }),

            "address": forms.Textarea(attrs={
                "class": "form-control",
                "rows": 3
            }),

            "city": forms.TextInput(attrs={
                "class": "form-control"
            }),

            "state": forms.TextInput(attrs={
                "class": "form-control"
            }),

            "country": forms.TextInput(attrs={
                "class": "form-control"
            }),

            "pincode": forms.TextInput(attrs={
                "class": "form-control"
            }),

            "subscription_start": forms.DateInput(attrs={
                "class": "form-control",
                "type": "date"
            }),

            "subscription_end": forms.DateInput(attrs={
                "class": "form-control",
                "type": "date"
            }),

            "logo": forms.ClearableFileInput(attrs={
                "class": "form-control"
            }),

            "is_active": forms.CheckboxInput(attrs={
                "class": "form-check-input"
            }),

        }

    def clean_company_name(self):

        company_name = self.cleaned_data["company_name"]

        qs = Company.objects.filter(company_name__iexact=company_name)

        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)

        if qs.exists():
            raise forms.ValidationError(_("Company name already exists."))

        return company_name


class CustomerForm(forms.ModelForm):

    class Meta:
        model = Customer

        fields = [
            "customer_name",
            "mobile",
            "email",
            "gst_number",
            "billing_address",
            "shipping_address",
            "city",
            "state",
            "country",
            "pincode",
            "opening_balance",
            "default_cash_discount_percent",
        ]

        widgets = {
            "customer_name": forms.TextInput(
                attrs={
                    "class": "form-control"
                }
            ),

            "mobile": forms.TextInput(
                attrs={
                    "class": "form-control"
                }
            ),

            "email": forms.EmailInput(
                attrs={
                    "class": "form-control"
                }
            ),

            "gst_number": forms.TextInput(
                attrs={
                    "class": "form-control"
                }
            ),

            "billing_address": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 3
                }
            ),
            "shipping_address": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 3
                }
            ),
            "city": forms.TextInput(
                attrs={
                    "class": "form-control"
                }
            ),

            "state": forms.TextInput(
                attrs={
                    "class": "form-control"
                }
            ),

            "country": forms.TextInput(
                attrs={
                    "class": "form-control"
                }
            ),

            "pincode": forms.TextInput(
                attrs={
                    "class": "form-control"
                }
            ),

            "opening_balance": forms.NumberInput(
                attrs={
                    "class": "form-control",
                    "step": "0.01"
                }
            ),
        }
        labels = {
            "customer_name": _("Customer name"),
            "mobile": _("Mobile"),
            "email": _("Email"),
            "gst_number": _("GST number"),
            "billing_address": _("Billing address"),
            "shipping_address": _("Shipping address"),
            "city": _("City"),
            "state": _("State"),
            "country": _("Country"),
            "pincode": _("Pincode"),
            "opening_balance": _("Opening balance (₹)"),
            "default_cash_discount_percent": _("Usual cash discount (CD) %"),
        }
        help_texts = {
            "opening_balance": _("Amount this customer already owed you before using this software."),
            "default_cash_discount_percent": _("Filled into every new sale for this customer; you can change it per sale."),
            "shipping_address": _("Leave empty if it is the same as the billing address."),
            "state": _("Used to choose CGST + SGST (same state) or IGST (other state) on invoices."),
        }

    def clean_customer_name(self):
        return (self.cleaned_data.get("customer_name") or "").strip()

    def clean_mobile(self):
        raw = (self.cleaned_data.get("mobile") or "").strip()
        return MillForm.clean_mobile(self) if raw else ""

    def clean_gst_number(self):
        return MillForm.clean_gst_number(self)


# ==========================================
# Mill / Supplier
# ==========================================
class MillForm(forms.ModelForm):
    """
    Add and edit a supplier.

    Replaces the old hand-read `request.POST.get(...)` code, which accepted
    letters as a phone number and crashed with a 500 when the opening balance
    was not a number.
    """

    class Meta:
        model = Mill
        fields = [
            "mill_name",
            "owner_name",
            "mobile",
            "gst_number",
            "address",
            "city",
            "state",
            "opening_balance",
            "notes",
        ]
        widgets = {
            "mill_name": forms.TextInput(attrs={
                "class": "input", "placeholder": _("e.g. Satya Rice Mill"), "autofocus": True,
            }),
            "owner_name": forms.TextInput(attrs={"class": "input", "placeholder": _("Owner's name")}),
            "mobile": forms.TextInput(attrs={
                "class": "input", "placeholder": _("10-digit mobile"), "inputmode": "numeric",
            }),
            "gst_number": forms.TextInput(attrs={
                "class": "input", "placeholder": "10ABCDE1234F1Z5", "style": "text-transform:uppercase",
            }),
            "address": forms.Textarea(attrs={"class": "textarea", "rows": 2, "placeholder": _("Street, area")}),
            "city": forms.TextInput(attrs={"class": "input", "placeholder": _("City")}),
            "state": forms.TextInput(attrs={"class": "input", "placeholder": _("State")}),
            "opening_balance": forms.NumberInput(attrs={
                "class": "input", "step": "0.01", "placeholder": "0.00",
            }),
            "notes": forms.Textarea(attrs={
                "class": "textarea", "rows": 2, "placeholder": _("Anything you want to remember about this supplier"),
            }),
        }
        labels = {
            "mill_name": _("Mill / Supplier name"),
            "mobile": _("Mobile number"),
            "gst_number": _("GST number"),
            "opening_balance": _("Opening balance (₹)"),
        }
        help_texts = {
            "opening_balance": _("Amount you already owed this mill before using this software."),
            "gst_number": _("Optional. 15 characters."),
        }

    def __init__(self, *args, company=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.company = company or getattr(self.instance, "company", None)
        self.fields["mill_name"].required = True
        self.fields["mobile"].required = True

    def clean_mill_name(self):
        name = (self.cleaned_data["mill_name"] or "").strip()

        duplicates = Mill.objects.filter(company=self.company, mill_name__iexact=name)
        if self.instance.pk:
            duplicates = duplicates.exclude(pk=self.instance.pk)

        if duplicates.exists():
            raise forms.ValidationError(_("You already have a supplier with this name."))

        return name

    def clean_mobile(self):
        raw = (self.cleaned_data.get("mobile") or "").strip()
        digits = "".join(ch for ch in raw if ch.isdigit())

        # Accept 0XXXXXXXXXX and +91XXXXXXXXXX, store the plain 10 digits.
        if len(digits) == 11 and digits.startswith("0"):
            digits = digits[1:]
        elif len(digits) == 12 and digits.startswith("91"):
            digits = digits[2:]

        if len(digits) != 10:
            raise forms.ValidationError(_("Enter a 10-digit mobile number."))

        if digits[0] not in "6789":
            raise forms.ValidationError(_("An Indian mobile number starts with 6, 7, 8 or 9."))

        return digits

    def clean_gst_number(self):
        gst = (self.cleaned_data.get("gst_number") or "").strip().upper()
        if not gst:
            return ""

        if not re.fullmatch(r"[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][0-9A-Z][Z][0-9A-Z]", gst):
            raise forms.ValidationError(
                _("That does not look like a GST number. Format: 22AAAAA0000A1Z5")
            )

        return gst

    def clean_opening_balance(self):
        balance = self.cleaned_data.get("opening_balance") or 0
        if balance < 0:
            raise forms.ValidationError(_("Opening balance cannot be negative."))
        return balance


# ==========================================
# Purchase (bill received from a mill)
# ==========================================
class PurchaseForm(forms.ModelForm):
    """
    The header of a purchase bill: which mill, their bill number, the date,
    how tax is charged, and the bill-level charges.

    It also carries two fields that are not on the model - what you paid at the
    moment of entry - so one screen records both the bill and the payment.
    """

    amount_paid_now = forms.DecimalField(
        required=False,
        min_value=0,
        decimal_places=2,
        label=_("Paid now (₹)"),
        widget=forms.NumberInput(attrs={
            "class": "input", "step": "0.01", "placeholder": "0.00",
        }),
        help_text=_("Leave empty if you have not paid anything yet."),
    )

    # ---- transport and labour: one box each, plus who paid it ----
    # Unticked (the usual case) the money is YOUR cost and the mill's bill stays
    # pure rice. Ticked, the mill charged it on its bill, so you owe it to them.
    transport_amount = forms.DecimalField(
        required=False, min_value=0, decimal_places=2, label=_("Transport / freight (₹)"),
        widget=forms.NumberInput(attrs={"class": "input", "step": "0.01", "placeholder": "0.00", "data-charge-amount": "transport"}),
    )
    transport_by_mill = forms.BooleanField(
        required=False, label=_("Mill charged this on the bill"),
        widget=forms.CheckboxInput(attrs={"data-charge-bymill": "transport"}),
    )

    labour_amount = forms.DecimalField(
        required=False, min_value=0, decimal_places=2, label=_("Labour / hamali (₹)"),
        widget=forms.NumberInput(attrs={"class": "input", "step": "0.01", "placeholder": "0.00", "data-charge-amount": "labour"}),
    )
    labour_by_mill = forms.BooleanField(
        required=False, label=_("Mill charged this on the bill"),
        widget=forms.CheckboxInput(attrs={"data-charge-bymill": "labour"}),
    )

    expense_other = forms.DecimalField(
        required=False, min_value=0, decimal_places=2, label=_("Other expense (₹)"),
        widget=forms.NumberInput(attrs={"class": "input", "step": "0.01", "placeholder": "0.00", "data-expense": "other"}),
    )
    expense_other_note = forms.CharField(
        required=False, max_length=150, label=_("What was it for?"),
        widget=forms.TextInput(attrs={"class": "input", "placeholder": _("e.g. brokerage, packing")}),
    )

    margin_percent = forms.DecimalField(
        required=False, min_value=0, max_value=100, decimal_places=2,
        label=_("Your margin (%)"),
        widget=forms.NumberInput(attrs={"class": "input", "step": "0.5", "data-margin": "1"}),
        help_text=_("Used to suggest a selling price from your real cost."),
    )

    payment_mode = forms.ChoiceField(
        required=False,
        label=_("Paid by"),
        choices=[("", "—"), ("Cash", _("Cash")), ("UPI", _("UPI")), ("Bank", _("Bank transfer")), ("Cheque", _("Cheque"))],
        widget=forms.Select(attrs={"class": "select"}),
    )

    class Meta:
        model = Purchase
        fields = [
            "mill",
            "invoice_no",
            "purchase_date",
            "tax_type",
            "discount_amount",
            "notes",
        ]
        widgets = {
            "mill": forms.Select(attrs={"class": "select", "autofocus": True}),
            "invoice_no": forms.TextInput(attrs={
                "class": "input", "placeholder": _("Number printed on the mill's bill"),
            }),
            "purchase_date": forms.DateInput(attrs={"class": "input", "type": "date"}),
            "tax_type": forms.Select(attrs={"class": "select", "data-tax-type": "1"}),
            "discount_amount": forms.NumberInput(attrs={"class": "input", "step": "0.01", "placeholder": "0.00", "data-charge": "discount"}),
            "notes": forms.Textarea(attrs={"class": "textarea", "rows": 2, "placeholder": _("Anything to remember about this bill")}),
        }
        labels = {
            "mill": _("Mill / Supplier"),
            "invoice_no": _("Supplier's bill number"),
            "purchase_date": _("Bill date"),
            "tax_type": _("GST on this bill"),
            "discount_amount": _("Discount (₹)"),
        }
        help_texts = {
            "invoice_no": _("Type the number printed on the mill's bill. No number on the bill? Leave it empty - this supplier's next number is given automatically."),
            "tax_type": _("Choose 'No GST' for a kacha bill."),
        }

    def __init__(self, *args, company=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.company = company

        # Only this company's active mills may be chosen.
        self.fields["mill"].queryset = Mill.objects.filter(
            company=company, is_active=True
        ).order_by("mill_name")
        self.fields["mill"].empty_label = _("Select the mill you bought from")
        self.fields["invoice_no"].required = False

        self.fields["discount_amount"].required = False

        if company is not None and not self.is_bound:
            self.fields["margin_percent"].initial = company.default_margin_percent

    def clean_purchase_date(self):
        purchase_date = self.cleaned_data["purchase_date"]

        if purchase_date > timezone.localdate():
            raise forms.ValidationError(_("The bill date cannot be in the future."))

        return purchase_date

    def clean_invoice_no(self):
        # Empty is allowed: the bill then gets the supplier's next automatic
        # number (BILL-001, BILL-002, ... per supplier) when it is saved.
        return (self.cleaned_data.get("invoice_no") or "").strip()

    def clean(self):
        cleaned = super().clean()

        mill = cleaned.get("mill")
        invoice_no = cleaned.get("invoice_no")

        # Entering the same mill bill twice doubles your stock and your dues,
        # which is one of the easiest mistakes to make.
        if mill and invoice_no:
            duplicates = Purchase.objects.filter(
                company=self.company, mill=mill, invoice_no__iexact=invoice_no
            )
            if self.instance.pk:
                duplicates = duplicates.exclude(pk=self.instance.pk)

            existing = duplicates.first()
            if existing:
                raise forms.ValidationError(
                    _("%(mill)s already has bill “%(bill)s” dated %(date)s. "
                      "Check before saving it again.") % {
                        "mill": mill.mill_name,
                        "bill": invoice_no,
                        "date": date_format(existing.purchase_date, "d M Y"),
                    }
                )

        paid = cleaned.get("amount_paid_now") or 0
        if paid and not cleaned.get("payment_mode"):
            self.add_error("payment_mode", _("Choose how you paid."))

        return cleaned


class PurchaseItemForm(forms.ModelForm):
    """One rice line on the bill."""

    class Meta:
        model = PurchaseItem
        fields = ["product", "bag_weight", "bag_count", "purchase_price", "gst_percent"]
        widgets = {
            "product": forms.Select(attrs={"class": "select", "data-product": "1"}),
            "bag_weight": forms.NumberInput(attrs={"class": "input", "min": "1", "step": "1", "inputmode": "numeric", "data-cell": "bag_weight"}),
            "bag_count": forms.NumberInput(attrs={"class": "input", "min": "0", "step": "1", "inputmode": "numeric", "data-cell": "bag_count"}),
            "purchase_price": forms.NumberInput(attrs={"class": "input", "min": "0", "step": "0.01", "inputmode": "decimal", "data-cell": "rate"}),
            "gst_percent": forms.NumberInput(attrs={"class": "input", "min": "0", "max": "28", "step": "0.01", "data-cell": "gst"}),
        }

    def __init__(self, *args, company=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.company = company

        self.fields["product"].queryset = Product.objects.filter(
            company=company, is_active=True
        ).order_by("rice_name")
        self.fields["product"].empty_label = _("Select rice")

        # Most rice here comes in 50 kg bags, so start there and let the user change it.
        if not self.instance.pk:
            self.fields["bag_weight"].initial = 50

        for name in self.fields:
            self.fields[name].required = False

    def clean(self):
        cleaned = super().clean()

        if cleaned.get("DELETE"):
            return cleaned

        product = cleaned.get("product")
        bags = cleaned.get("bag_count") or 0
        weight = cleaned.get("bag_weight") or 0
        rate = cleaned.get("purchase_price") or 0

        # A completely empty row is simply ignored.
        if not product and not bags and not rate:
            return cleaned

        if not product:
            self.add_error("product", _("Choose which rice this line is for."))
        if bags <= 0:
            self.add_error("bag_count", _("Enter how many bags."))
        if weight <= 0:
            self.add_error("bag_weight", _("Enter the weight of one bag."))
        if rate <= 0:
            self.add_error("purchase_price", _("Enter the rate per kg."))

        return cleaned


class BasePurchaseItemFormSet(forms.BaseInlineFormSet):
    """Makes sure a bill has at least one real line."""

    def clean(self):
        super().clean()

        if any(self.errors):
            return

        filled = 0
        for form in self.forms:
            if self.can_delete and self._should_delete_form(form):
                continue
            data = form.cleaned_data
            if data.get("product") and (data.get("bag_count") or 0) > 0:
                filled += 1

        if filled == 0:
            raise forms.ValidationError(_("Add at least one rice line to this bill."))


PurchaseItemFormSet = forms.inlineformset_factory(
    Purchase,
    PurchaseItem,
    form=PurchaseItemForm,
    formset=BasePurchaseItemFormSet,
    extra=1,
    can_delete=True,
)


# ==========================================
# Broker
# ==========================================
class BrokerForm(forms.ModelForm):
    """Add and edit a broker, with his usual commission."""

    class Meta:
        model = Broker
        fields = [
            "broker_name",
            "mobile",
            "city",
            "address",
            "gst_number",
            "commission_type",
            "commission_rate",
            "default_cash_discount_percent",
            "opening_balance",
            "notes",
        ]
        widgets = {
            "broker_name": forms.TextInput(attrs={"class": "input", "autofocus": True}),
            "mobile": forms.TextInput(attrs={"class": "input", "inputmode": "numeric", "placeholder": _("10-digit mobile")}),
            "city": forms.TextInput(attrs={"class": "input"}),
            "address": forms.Textarea(attrs={"class": "textarea", "rows": 2}),
            "gst_number": forms.TextInput(attrs={"class": "input", "style": "text-transform:uppercase"}),
            "commission_type": forms.Select(attrs={"class": "select"}),
            "commission_rate": forms.NumberInput(attrs={"class": "input", "step": "0.01", "min": "0"}),
            "default_cash_discount_percent": forms.NumberInput(attrs={"class": "input", "step": "0.01", "min": "0", "max": "100"}),
            "opening_balance": forms.NumberInput(attrs={"class": "input", "step": "0.01", "min": "0"}),
            "notes": forms.Textarea(attrs={"class": "textarea", "rows": 2}),
        }
        labels = {
            "broker_name": _("Broker name"),
            "mobile": _("Mobile number"),
            "city": _("City"),
            "address": _("Address"),
            "gst_number": _("GST number"),
            "commission_type": _("Commission is charged"),
            "commission_rate": _("Commission rate"),
            "default_cash_discount_percent": _("Cash discount (CD) % on his sales"),
            "opening_balance": _("Opening balance (₹)"),
            "notes": _("Notes"),
        }
        help_texts = {
            "commission_rate": _("His usual rate, e.g. 0.10 per kg. You can change it on each sale."),
            "default_cash_discount_percent": _("Filled into each sale he brings, e.g. 1.5."),
            "opening_balance": _("Commission you already owed him before using this software."),
        }

    def __init__(self, *args, company=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.company = company or getattr(self.instance, "company", None)
        self.fields["mobile"].required = False

    def clean_broker_name(self):
        name = (self.cleaned_data["broker_name"] or "").strip()
        duplicates = Broker.objects.filter(company=self.company, broker_name__iexact=name)
        if self.instance.pk:
            duplicates = duplicates.exclude(pk=self.instance.pk)
        if duplicates.exists():
            raise forms.ValidationError(_("You already have a broker with this name."))
        return name

    def clean_mobile(self):
        raw = (self.cleaned_data.get("mobile") or "").strip()
        if not raw:
            return ""
        return MillForm.clean_mobile(self)

    def clean_gst_number(self):
        return MillForm.clean_gst_number(self)

    def clean_opening_balance(self):
        balance = self.cleaned_data.get("opening_balance") or 0
        if balance < 0:
            raise forms.ValidationError(_("Opening balance cannot be negative."))
        return balance

    def clean_commission_rate(self):
        rate = self.cleaned_data.get("commission_rate") or 0
        if rate < 0:
            raise forms.ValidationError(_("Commission cannot be negative."))
        return rate


# ==========================================
# Sale (invoice to a customer)
# ==========================================
PAYMENT_MODE_CHOICES = [
    ("", "—"),
    ("Cash", _("Cash")),
    ("UPI", _("UPI")),
    ("Bank", _("Bank transfer")),
    ("Cheque", _("Cheque")),
]


class SaleForm(forms.ModelForm):
    """
    The header of a sale invoice: who is buying, through which broker, the
    truck, transport, and money received on the spot.
    """

    class Meta:
        model = Sale
        fields = [
            "customer",
            "sale_date",
            "due_date",
            "tax_type",
            "broker",
            "collect_from",
            "broker_commission_type",
            "broker_commission_rate",
            "vehicle_number",
            "driver_name",
            "driver_mobile",
            "transporter_name",
            "freight_borne_by",
            "transport_rate_per_ton",
            "transport_paid_by_dealer",
            "transport_paid_by_customer",
            "loading_weight_kg",
            "loading_charge",
            "broker_paid_by",
            "cash_discount_percent",
            "advance_received",
            "advance_mode",
            "notes",
        ]
        widgets = {
            "customer": forms.Select(attrs={"class": "select", "data-customer": "1", "autofocus": True}),
            "sale_date": forms.DateInput(attrs={"class": "input", "type": "date"}, format="%Y-%m-%d"),
            "due_date": forms.DateInput(attrs={"class": "input", "type": "date"}, format="%Y-%m-%d"),
            "tax_type": forms.Select(attrs={"class": "select", "data-tax-type": "1"}),
            "broker": forms.Select(attrs={"class": "select", "data-broker": "1"}),
            "broker_commission_type": forms.Select(attrs={"class": "select", "data-commission-type": "1"}),
            "broker_commission_rate": forms.NumberInput(attrs={"class": "input", "step": "0.01", "min": "0", "data-commission-rate": "1"}),
            "vehicle_number": forms.TextInput(attrs={"class": "input", "placeholder": "BR 01 AB 1234", "style": "text-transform:uppercase"}),
            "driver_name": forms.TextInput(attrs={"class": "input"}),
            "driver_mobile": forms.TextInput(attrs={"class": "input", "inputmode": "numeric"}),
            "transporter_name": forms.TextInput(attrs={"class": "input"}),
            "transport_rate_per_ton": forms.NumberInput(attrs={"class": "input", "step": "0.01", "min": "0", "data-transport": "rate"}),
            "transport_paid_by_dealer": forms.NumberInput(attrs={"class": "input", "step": "0.01", "min": "0", "data-transport": "dealer"}),
            "transport_paid_by_customer": forms.NumberInput(attrs={"class": "input", "step": "0.01", "min": "0", "data-transport": "customer"}),
            "freight_borne_by": forms.Select(attrs={"class": "select", "data-freight-by": "1"}),
            "loading_charge": forms.NumberInput(attrs={"class": "input", "step": "0.01", "min": "0", "data-loading": "1"}),
            "loading_weight_kg": forms.NumberInput(attrs={"class": "input", "step": "0.01", "min": "0", "data-loading-weight": "1"}),
            "collect_from": forms.Select(attrs={"class": "select", "data-collect-from": "1"}),
            "broker_paid_by": forms.Select(attrs={"class": "select", "data-broker-paid-by": "1"}),
            "cash_discount_percent": forms.NumberInput(attrs={"class": "input", "step": "0.01", "min": "0", "max": "100", "data-cd": "1"}),
            "advance_received": forms.NumberInput(attrs={"class": "input", "step": "0.01", "min": "0", "data-advance": "1"}),
            "advance_mode": forms.Select(attrs={"class": "select"}, choices=PAYMENT_MODE_CHOICES),
            "notes": forms.Textarea(attrs={"class": "textarea", "rows": 2, "placeholder": _("Anything to remember about this sale")}),
        }
        labels = {
            "customer": _("Customer"),
            "sale_date": _("Invoice date"),
            "due_date": _("Payment due by"),
            "tax_type": _("GST on this invoice"),
            "broker": _("Broker"),
            "broker_commission_type": _("Commission"),
            "broker_commission_rate": _("Commission rate"),
            "vehicle_number": _("Vehicle number"),
            "driver_name": _("Driver name"),
            "driver_mobile": _("Driver mobile"),
            "transporter_name": _("Transporter"),
            "transport_rate_per_ton": _("Freight rate per ton (₹)"),
            "transport_paid_by_dealer": _("Freight advance paid by you (₹)"),
            "transport_paid_by_customer": _("Freight balance the party pays the driver (₹)"),
            "freight_borne_by": _("Who carries the freight"),
            "loading_charge": _("Loading / hamali at the mill (₹)"),
            "loading_weight_kg": _("Weighbridge weight at loading (kg)"),
            "collect_from": _("Who pays us"),
            "broker_paid_by": _("Who pays the broker"),
            "cash_discount_percent": _("Cash discount (CD) %"),
            "advance_received": _("Received now (₹)"),
            "advance_mode": _("Received by"),
            "notes": _("Notes"),
        }
        help_texts = {
            "due_date": _("Optional. Unpaid invoices past this date are shown as overdue."),
            "tax_type": _("Filled from the customer's state. Choose 'No GST' for a bill of supply."),
            "broker": _("Optional. The invoice still goes to the customer. His usual CD and brokerage fill in below - change them for this truck if the deal is different."),
            "broker_commission_rate": _("For this truck. Can be changed again at unloading."),
            "advance_received": _("Money the customer paid at the time of sale. Later payments are added from the invoice page."),
            "loading_charge": _("Your cost for loading this truck - counted in profit, not billed. Filled as weight × your loading rate."),
            "loading_weight_kg": _("Leave empty if it equals bags × bag weight."),
            "collect_from": _("Through a broker, he usually collects from the party, keeps his brokerage, cuts the CD and pays you the rest."),
            "cash_discount_percent": _("The discount the party cuts when paying, e.g. 1.5. Filled from the customer."),
        }

    def __init__(self, *args, company=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.company = company

        customers = Customer.objects.filter(company=company, is_active=True)
        brokers = Broker.objects.filter(company=company, is_active=True)
        # On edit, keep a since-deactivated customer or broker selectable.
        if self.instance.pk:
            if self.instance.customer_id:
                customers = customers | Customer.objects.filter(pk=self.instance.customer_id)
            if self.instance.broker_id:
                brokers = brokers | Broker.objects.filter(pk=self.instance.broker_id)

        self.fields["customer"].queryset = customers.order_by("customer_name")
        self.fields["customer"].empty_label = _("Select the customer")
        self.fields["customer"].required = True

        self.fields["broker"].queryset = brokers.order_by("broker_name")
        self.fields["broker"].empty_label = _("Direct sale (no broker)")

        self.fields["broker_commission_type"].choices = Broker.COMMISSION_TYPES
        self.fields["broker_commission_type"].required = False
        self.fields["advance_mode"].required = False

        for name in ("transport_rate_per_ton", "transport_paid_by_dealer",
                     "transport_paid_by_customer", "advance_received", "broker_commission_rate",
                     "loading_charge", "cash_discount_percent", "freight_borne_by", "broker_paid_by",
                     "collect_from", "loading_weight_kg"):
            self.fields[name].required = False

    def clean_freight_borne_by(self):
        return self.cleaned_data.get("freight_borne_by") or Sale.FREIGHT_US

    def clean_broker_paid_by(self):
        return self.cleaned_data.get("broker_paid_by") or Sale.BROKER_PAID_BY_US

    def clean_sale_date(self):
        sale_date = self.cleaned_data["sale_date"]
        if sale_date > timezone.localdate():
            raise forms.ValidationError(_("The invoice date cannot be in the future."))
        return sale_date

    def clean_vehicle_number(self):
        return (self.cleaned_data.get("vehicle_number") or "").strip().upper()

    def clean_driver_mobile(self):
        raw = (self.cleaned_data.get("driver_mobile") or "").strip()
        digits = "".join(ch for ch in raw if ch.isdigit())
        if raw and len(digits) < 10:
            raise forms.ValidationError(_("Enter a 10-digit mobile number."))
        return digits[-10:] if digits else ""

    def clean(self):
        cleaned = super().clean()

        for name in ("transport_rate_per_ton", "transport_paid_by_dealer",
                     "transport_paid_by_customer", "advance_received", "broker_commission_rate",
                     "loading_charge", "cash_discount_percent"):
            value = cleaned.get(name)
            if value is None:
                cleaned[name] = 0
            elif value < 0:
                self.add_error(name, _("Cannot be negative."))

        if (cleaned.get("advance_received") or 0) > 0 and not cleaned.get("advance_mode"):
            self.add_error("advance_mode", _("Choose how the money was received."))

        sale_date = cleaned.get("sale_date")
        due_date = cleaned.get("due_date")
        if sale_date and due_date and due_date < sale_date:
            self.add_error("due_date", _("The due date cannot be before the invoice date."))

        if (cleaned.get("cash_discount_percent") or 0) > 100:
            self.add_error("cash_discount_percent", _("Cannot be more than 100%."))

        # Only a broker can collect; a direct sale is always paid by the customer.
        if not cleaned.get("broker"):
            cleaned["collect_from"] = Sale.COLLECT_FROM_CUSTOMER
        elif not cleaned.get("collect_from"):
            cleaned["collect_from"] = Sale.COLLECT_FROM_BROKER

        weight = cleaned.get("loading_weight_kg")
        if weight is not None and weight <= 0:
            cleaned["loading_weight_kg"] = None

        if cleaned.get("broker") and not cleaned.get("broker_commission_type"):
            cleaned["broker_commission_type"] = cleaned["broker"].commission_type

        return cleaned


class SaleItemForm(forms.ModelForm):
    """One rice line on the customer's invoice."""

    class Meta:
        model = SaleItem
        fields = ["product", "bag_weight", "bag_count", "rate_per_kg", "gst_percent", "purchase_item"]
        widgets = {
            "product": forms.Select(attrs={"class": "select", "data-product": "1"}),
            "bag_weight": forms.NumberInput(attrs={"class": "input", "min": "1", "step": "1", "inputmode": "numeric", "data-cell": "bag_weight"}),
            "bag_count": forms.NumberInput(attrs={"class": "input", "min": "0", "step": "1", "inputmode": "numeric", "data-cell": "bag_count"}),
            "rate_per_kg": forms.NumberInput(attrs={"class": "input", "min": "0", "step": "0.01", "inputmode": "decimal", "data-cell": "rate"}),
            "gst_percent": forms.NumberInput(attrs={"class": "input", "min": "0", "max": "28", "step": "0.01", "data-cell": "gst"}),
            "purchase_item": forms.Select(attrs={"class": "select", "data-lot": "1"}),
        }

    def __init__(self, *args, company=None, lots=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.company = company

        self.fields["product"].queryset = Product.objects.filter(
            company=company, is_active=True
        ).order_by("rice_name") | Product.objects.filter(
            pk=getattr(self.instance, "product_id", None) or 0
        )
        self.fields["product"].empty_label = _("Select rice")

        self.fields["purchase_item"].queryset = (
            PurchaseItem.objects.for_company(company).select_related("purchase", "purchase__mill")
        )
        self.fields["purchase_item"].empty_label = _("Oldest stock first (auto)")
        self.fields["purchase_item"].label_from_instance = lambda lot: (
            f"{lot.purchase.invoice_no} · {lot.purchase.mill.mill_name} · "
            f"{lot.bag_weight} kg · ₹{lot.purchase_price}/kg"
        )

        if not self.instance.pk:
            self.fields["bag_weight"].initial = 50

        for name in self.fields:
            self.fields[name].required = False

    def clean(self):
        cleaned = super().clean()

        if cleaned.get("DELETE"):
            return cleaned

        product = cleaned.get("product")
        bags = cleaned.get("bag_count") or 0
        weight = cleaned.get("bag_weight") or 0
        rate = cleaned.get("rate_per_kg") or 0

        if not product and not bags and not rate:
            return cleaned

        if not product:
            self.add_error("product", _("Choose which rice this line is for."))
        if bags <= 0:
            self.add_error("bag_count", _("Enter how many bags."))
        if weight <= 0:
            self.add_error("bag_weight", _("Enter the weight of one bag."))
        if rate <= 0:
            self.add_error("rate_per_kg", _("Enter the selling rate per kg."))
        if (cleaned.get("gst_percent") or 0) < 0:
            self.add_error("gst_percent", _("Cannot be negative."))

        return cleaned


class BaseSaleItemFormSet(forms.BaseInlineFormSet):
    """An invoice needs at least one real line."""

    def clean(self):
        super().clean()

        if any(self.errors):
            return

        filled = 0
        for form in self.forms:
            if self.can_delete and self._should_delete_form(form):
                continue
            data = form.cleaned_data
            if data.get("product") and (data.get("bag_count") or 0) > 0:
                filled += 1

        if filled == 0:
            raise forms.ValidationError(_("Add at least one rice line to this invoice."))

    def filled_items(self):
        """Unsaved SaleItem objects for every real, non-deleted line."""
        items = []
        for form in self.forms:
            if self.can_delete and self._should_delete_form(form):
                continue
            data = form.cleaned_data
            if not data.get("product") or not (data.get("bag_count") or 0):
                continue
            items.append(SaleItem(
                product=data["product"],
                bag_weight=data.get("bag_weight") or 0,
                bag_count=data.get("bag_count") or 0,
                rate_per_kg=data.get("rate_per_kg") or 0,
                gst_percent=data.get("gst_percent") or 0,
                purchase_item=data.get("purchase_item"),
            ))
        return items


SaleItemFormSet = forms.inlineformset_factory(
    Sale,
    SaleItem,
    form=SaleItemForm,
    formset=BaseSaleItemFormSet,
    fields=["product", "bag_weight", "bag_count", "rate_per_kg", "gst_percent", "purchase_item"],
    extra=1,
    can_delete=True,
)


class SettlementForm(forms.ModelForm):
    """
    After the truck is unloaded: the weight the party received, their cash
    discount, freight they paid the driver, and any other cut. This turns the
    invoice into what the party really owes.
    """

    class Meta:
        model = Sale
        fields = [
            "unload_date",
            "received_weight_kg",
            "cash_discount_percent",
            "broker_commission_type",
            "broker_commission_rate",
            "broker_paid_by",
            "transport_paid_by_customer",
            "other_deductions",
            "other_deductions_note",
        ]
        widgets = {
            "broker_commission_type": forms.Select(attrs={"class": "select"}),
            "broker_commission_rate": forms.NumberInput(attrs={"class": "input", "step": "0.01", "min": "0"}),
            "unload_date": forms.DateInput(attrs={"class": "input", "type": "date"}, format="%Y-%m-%d"),
            "received_weight_kg": forms.NumberInput(attrs={"class": "input", "step": "0.01", "min": "0", "data-received": "1"}),
            "cash_discount_percent": forms.NumberInput(attrs={"class": "input", "step": "0.01", "min": "0", "max": "100", "data-cd": "1"}),
            "broker_paid_by": forms.Select(attrs={"class": "select"}),
            "transport_paid_by_customer": forms.NumberInput(attrs={"class": "input", "step": "0.01", "min": "0"}),
            "other_deductions": forms.NumberInput(attrs={"class": "input", "step": "0.01", "min": "0"}),
            "other_deductions_note": forms.TextInput(attrs={"class": "input", "placeholder": _("e.g. moisture, quality claim")}),
        }
        labels = {
            "unload_date": _("Unloaded on"),
            "received_weight_kg": _("Weight the party received (kg)"),
            "cash_discount_percent": _("Cash discount (CD) %"),
            "broker_commission_type": _("Brokerage charged"),
            "broker_commission_rate": _("Brokerage rate"),
            "broker_paid_by": _("Who pays the broker"),
            "transport_paid_by_customer": _("Freight the party paid the driver (₹)"),
            "other_deductions": _("Other deductions (₹)"),
            "other_deductions_note": _("Reason"),
        }
        help_texts = {
            "received_weight_kg": _("From the party's weighbridge slip. The shortage in transit is your loss."),
            "transport_paid_by_customer": _("The balance fare the party paid on unloading and will cut from your payment."),
            "cash_discount_percent": _("As agreed for this truck - it can differ from the usual rate."),
            "broker_commission_rate": _("As charged on this truck, e.g. 0.10 per kg."),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["unload_date"].required = True
        self.fields["received_weight_kg"].required = True
        self.fields["broker_commission_type"].choices = Broker.COMMISSION_TYPES
        for name in ("cash_discount_percent", "transport_paid_by_customer", "other_deductions",
                     "broker_commission_type", "broker_commission_rate", "broker_paid_by"):
            self.fields[name].required = False
        if not self.instance.broker_id:
            for name in ("broker_commission_type", "broker_commission_rate", "broker_paid_by"):
                self.fields.pop(name)

    def clean(self):
        cleaned = super().clean()
        # A brokerage field that was not sent at all keeps the sale's value.
        for name in ("broker_commission_type", "broker_commission_rate", "broker_paid_by"):
            if name in self.fields and name not in self.data:
                cleaned[name] = getattr(self.instance, name)

        for name in ("cash_discount_percent", "transport_paid_by_customer", "other_deductions", "broker_commission_rate"):
            if name not in self.fields:
                continue
            value = cleaned.get(name)
            if value is None:
                cleaned[name] = 0
            elif value < 0:
                self.add_error(name, _("Cannot be negative."))

        if (cleaned.get("cash_discount_percent") or 0) > 100:
            self.add_error("cash_discount_percent", _("Cannot be more than 100%."))
        if "broker_commission_type" in self.fields and not cleaned.get("broker_commission_type"):
            cleaned["broker_commission_type"] = self.instance.broker_commission_type or Broker.PER_KG
        if "broker_paid_by" in self.fields and not cleaned.get("broker_paid_by"):
            cleaned["broker_paid_by"] = self.instance.broker_paid_by

        unload = cleaned.get("unload_date")
        if unload:
            if unload > timezone.localdate():
                self.add_error("unload_date", _("The unloading date cannot be in the future."))
            elif self.instance.sale_date and unload < self.instance.sale_date:
                self.add_error("unload_date", _("The truck cannot be unloaded before it was sent."))

        received = cleaned.get("received_weight_kg")
        dispatched = self.instance.total_quantity_kg or 0
        if received is not None:
            if received <= 0:
                self.add_error("received_weight_kg", _("Enter the weight the party received."))
            elif dispatched and received > dispatched * Decimal("1.05"):
                self.add_error(
                    "received_weight_kg",
                    _("That is more than 5%% over the %(kg)s kg sent - check the slip.") % {"kg": dispatched},
                )
        return cleaned


class ReceiptForm(forms.Form):
    """Money received from a customer, or commission paid to a broker."""

    amount = forms.DecimalField(
        min_value=Decimal("0.01"), decimal_places=2, label=_("Amount (₹)"),
        widget=forms.NumberInput(attrs={"class": "input", "step": "0.01", "autofocus": True}),
    )
    payment_mode = forms.ChoiceField(
        choices=PAYMENT_MODE_CHOICES[1:], label=_("Mode"),
        widget=forms.Select(attrs={"class": "select"}),
    )
    payment_date = forms.DateField(
        label=_("Date"),
        widget=forms.DateInput(attrs={"class": "input", "type": "date"}, format="%Y-%m-%d"),
    )
    notes = forms.CharField(
        required=False, max_length=500, label=_("Notes"),
        widget=forms.TextInput(attrs={"class": "input", "placeholder": _("Cheque no., UTR, who paid…")}),
    )

    def clean_payment_date(self):
        value = self.cleaned_data["payment_date"]
        if value > timezone.localdate():
            raise forms.ValidationError(_("A payment cannot be dated in the future."))
        return value
