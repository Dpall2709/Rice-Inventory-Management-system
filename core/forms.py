from django import forms
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password

from .models import Company, Customer



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