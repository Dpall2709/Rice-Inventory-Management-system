import re

from django import forms
from django.contrib.auth.models import User
from django.utils import timezone
from django.contrib.auth.password_validation import validate_password

from .models import Company, Customer, Mill, Product, Purchase, PurchaseItem



# ==========================================
# Future Public Registration (Keep It)
# ==========================================
class CompanyRegistrationForm(forms.Form):

    company_name = forms.CharField(
        max_length=200,
        widget=forms.TextInput(attrs={
            "class": "form-control",
            "placeholder": "Company Name"
        })
    )

    owner_name = forms.CharField(
        max_length=200,
        widget=forms.TextInput(attrs={
            "class": "form-control",
            "placeholder": "Owner Name"
        })
    )

    email = forms.EmailField(
        widget=forms.EmailInput(attrs={
            "class": "form-control",
            "placeholder": "Email Address"
        })
    )

    mobile = forms.CharField(
        max_length=20,
        widget=forms.TextInput(attrs={
            "class": "form-control",
            "placeholder": "Mobile Number"
        })
    )

    username = forms.CharField(
        max_length=150,
        widget=forms.TextInput(attrs={
            "class": "form-control",
            "placeholder": "Username"
        })
    )

    password1 = forms.CharField(
        widget=forms.PasswordInput(attrs={
            "class": "form-control",
            "placeholder": "Password"
        }),
        validators=[validate_password]
    )

    password2 = forms.CharField(
        widget=forms.PasswordInput(attrs={
            "class": "form-control",
            "placeholder": "Confirm Password"
        })
    )

    def clean_company_name(self):
        company_name = self.cleaned_data["company_name"]

        if Company.objects.filter(company_name__iexact=company_name).exists():
            raise forms.ValidationError("Company already exists.")

        return company_name

    def clean_username(self):
        username = self.cleaned_data["username"]

        if User.objects.filter(username=username).exists():
            raise forms.ValidationError("Username already taken.")

        return username

    def clean_email(self):
        email = self.cleaned_data["email"]

        if User.objects.filter(email=email).exists():
            raise forms.ValidationError("Email already registered.")

        return email

    def clean(self):
        cleaned_data = super().clean()

        password1 = cleaned_data.get("password1")
        password2 = cleaned_data.get("password2")

        if password1 and password2:
            if password1 != password2:
                raise forms.ValidationError("Passwords do not match.")

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
            raise forms.ValidationError("Company name already exists.")

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
                "class": "input", "placeholder": "e.g. Satya Rice Mill", "autofocus": True,
            }),
            "owner_name": forms.TextInput(attrs={"class": "input", "placeholder": "Owner's name"}),
            "mobile": forms.TextInput(attrs={
                "class": "input", "placeholder": "10-digit mobile", "inputmode": "numeric",
            }),
            "gst_number": forms.TextInput(attrs={
                "class": "input", "placeholder": "10ABCDE1234F1Z5", "style": "text-transform:uppercase",
            }),
            "address": forms.Textarea(attrs={"class": "textarea", "rows": 2, "placeholder": "Street, area"}),
            "city": forms.TextInput(attrs={"class": "input", "placeholder": "City"}),
            "state": forms.TextInput(attrs={"class": "input", "placeholder": "State"}),
            "opening_balance": forms.NumberInput(attrs={
                "class": "input", "step": "0.01", "placeholder": "0.00",
            }),
            "notes": forms.Textarea(attrs={
                "class": "textarea", "rows": 2, "placeholder": "Anything you want to remember about this supplier",
            }),
        }
        labels = {
            "mill_name": "Mill / Supplier name",
            "mobile": "Mobile number",
            "gst_number": "GST number",
            "opening_balance": "Opening balance (₹)",
        }
        help_texts = {
            "opening_balance": "Amount you already owed this mill before using this software.",
            "gst_number": "Optional. 15 characters.",
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
            raise forms.ValidationError("You already have a supplier with this name.")

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
            raise forms.ValidationError("Enter a 10-digit mobile number.")

        if digits[0] not in "6789":
            raise forms.ValidationError("An Indian mobile number starts with 6, 7, 8 or 9.")

        return digits

    def clean_gst_number(self):
        gst = (self.cleaned_data.get("gst_number") or "").strip().upper()
        if not gst:
            return ""

        if not re.fullmatch(r"[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][0-9A-Z][Z][0-9A-Z]", gst):
            raise forms.ValidationError(
                "That does not look like a GST number. Format: 22AAAAA0000A1Z5"
            )

        return gst

    def clean_opening_balance(self):
        balance = self.cleaned_data.get("opening_balance") or 0
        if balance < 0:
            raise forms.ValidationError("Opening balance cannot be negative.")
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
        label="Paid now (₹)",
        widget=forms.NumberInput(attrs={
            "class": "input", "step": "0.01", "placeholder": "0.00",
        }),
        help_text="Leave empty if you have not paid anything yet.",
    )

    # ---- transport and labour: one box each, plus who paid it ----
    # Unticked (the usual case) the money is YOUR cost and the mill's bill stays
    # pure rice. Ticked, the mill charged it on its bill, so you owe it to them.
    transport_amount = forms.DecimalField(
        required=False, min_value=0, decimal_places=2, label="Transport / freight (₹)",
        widget=forms.NumberInput(attrs={"class": "input", "step": "0.01", "placeholder": "0.00", "data-charge-amount": "transport"}),
    )
    transport_by_mill = forms.BooleanField(
        required=False, label="Mill charged this on the bill",
        widget=forms.CheckboxInput(attrs={"data-charge-bymill": "transport"}),
    )

    labour_amount = forms.DecimalField(
        required=False, min_value=0, decimal_places=2, label="Labour / hamali (₹)",
        widget=forms.NumberInput(attrs={"class": "input", "step": "0.01", "placeholder": "0.00", "data-charge-amount": "labour"}),
    )
    labour_by_mill = forms.BooleanField(
        required=False, label="Mill charged this on the bill",
        widget=forms.CheckboxInput(attrs={"data-charge-bymill": "labour"}),
    )

    expense_other = forms.DecimalField(
        required=False, min_value=0, decimal_places=2, label="Other expense (₹)",
        widget=forms.NumberInput(attrs={"class": "input", "step": "0.01", "placeholder": "0.00", "data-expense": "other"}),
    )
    expense_other_note = forms.CharField(
        required=False, max_length=150, label="What was it for?",
        widget=forms.TextInput(attrs={"class": "input", "placeholder": "e.g. brokerage, packing"}),
    )

    margin_percent = forms.DecimalField(
        required=False, min_value=0, max_value=100, decimal_places=2,
        label="Your margin (%)",
        widget=forms.NumberInput(attrs={"class": "input", "step": "0.5", "data-margin": "1"}),
        help_text="Used to suggest a selling price from your real cost.",
    )

    payment_mode = forms.ChoiceField(
        required=False,
        label="Paid by",
        choices=[("", "—"), ("Cash", "Cash"), ("UPI", "UPI"), ("Bank", "Bank transfer"), ("Cheque", "Cheque")],
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
                "class": "input", "placeholder": "Number printed on the mill's bill",
            }),
            "purchase_date": forms.DateInput(attrs={"class": "input", "type": "date"}),
            "tax_type": forms.Select(attrs={"class": "select", "data-tax-type": "1"}),
            "discount_amount": forms.NumberInput(attrs={"class": "input", "step": "0.01", "placeholder": "0.00", "data-charge": "discount"}),
            "notes": forms.Textarea(attrs={"class": "textarea", "rows": 2, "placeholder": "Anything to remember about this bill"}),
        }
        labels = {
            "mill": "Mill / Supplier",
            "invoice_no": "Supplier's bill number",
            "purchase_date": "Bill date",
            "tax_type": "GST on this bill",
            "discount_amount": "Discount (₹)",
        }
        help_texts = {
            "invoice_no": "The number on the bill the mill gave you - not generated by us.",
            "tax_type": "Choose 'No GST' for a kacha bill.",
        }

    def __init__(self, *args, company=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.company = company

        # Only this company's active mills may be chosen.
        self.fields["mill"].queryset = Mill.objects.filter(
            company=company, is_active=True
        ).order_by("mill_name")
        self.fields["mill"].empty_label = "Select the mill you bought from"

        self.fields["discount_amount"].required = False

        if company is not None and not self.is_bound:
            self.fields["margin_percent"].initial = company.default_margin_percent

    def clean_purchase_date(self):
        purchase_date = self.cleaned_data["purchase_date"]

        if purchase_date > timezone.localdate():
            raise forms.ValidationError("The bill date cannot be in the future.")

        return purchase_date

    def clean_invoice_no(self):
        invoice_no = (self.cleaned_data.get("invoice_no") or "").strip()

        if not invoice_no:
            raise forms.ValidationError("Enter the number printed on the supplier's bill.")

        return invoice_no

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
                    f"{mill.mill_name} already has bill “{invoice_no}” "
                    f"dated {existing.purchase_date:%d %b %Y}. "
                    "Check before saving it again."
                )

        paid = cleaned.get("amount_paid_now") or 0
        if paid and not cleaned.get("payment_mode"):
            self.add_error("payment_mode", "Choose how you paid.")

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
        self.fields["product"].empty_label = "Select rice"

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
            self.add_error("product", "Choose which rice this line is for.")
        if bags <= 0:
            self.add_error("bag_count", "Enter how many bags.")
        if weight <= 0:
            self.add_error("bag_weight", "Enter the weight of one bag.")
        if rate <= 0:
            self.add_error("purchase_price", "Enter the rate per kg.")

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
            raise forms.ValidationError("Add at least one rice line to this bill.")


PurchaseItemFormSet = forms.inlineformset_factory(
    Purchase,
    PurchaseItem,
    form=PurchaseItemForm,
    formset=BasePurchaseItemFormSet,
    extra=1,
    can_delete=True,
)
