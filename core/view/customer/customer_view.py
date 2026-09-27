from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import (
    get_object_or_404,
    redirect,
    render
)

from core.models import Customer
from core.forms import CustomerForm
from core.permissions import manager_required

# How the customer form is grouped on screen.
FORM_SECTIONS = [
    ("Customer", "customer_name,mobile,email"),
    ("Tax", "gst_number"),
    ("Address", "billing_address,shipping_address,city,state,country,pincode"),
    ("Balance", "opening_balance"),
]


@login_required
def customer_list(request):

    company = request.user.userprofile.company

    q = request.GET.get("q", "").strip()

    customers = Customer.objects.filter(
        company=company,
        is_active=True
    ).order_by("-created_at")

    if q:
        customers = customers.filter(
            Q(customer_name__icontains=q) |
            Q(mobile__icontains=q) |
            Q(gst_number__icontains=q)
        )

    return render(
        request,
        "core/customer_list.html",
        {
            "customers": customers,
            "q": q,
        }
    )


@login_required
def add_customer(request):

    company = request.user.userprofile.company

    if request.method == "POST":

        form = CustomerForm(request.POST)

        if form.is_valid():

            customer = form.save(commit=False)

            customer.company = company

            customer.save()

            messages.success(
                request,
                "✅ Customer saved successfully!"
            )

            return redirect("customer_list")

    else:

        form = CustomerForm()

    return render(
        request,
        "core/customer_form.html",
        {
            "form": form,
            "mode": "add",
            "sections": FORM_SECTIONS,
        }
    )


@login_required
def edit_customer(request, customer_id):

    company = request.user.userprofile.company

    customer = get_object_or_404(
        Customer,
        id=customer_id,
        company=company
    )

    if request.method == "POST":

        form = CustomerForm(
            request.POST,
            instance=customer
        )

        if form.is_valid():

            form.save()

            messages.success(
                request,
                "✅ Customer updated successfully!"
            )

            return redirect("customer_list")

    else:

        form = CustomerForm(
            instance=customer
        )

    return render(
        request,
        "core/customer_form.html",
        {
            "form": form,
            "customer": customer,
            "mode": "edit",
            "sections": FORM_SECTIONS,
        }
    )


@login_required
@manager_required
def delete_customer(request, customer_id):

    company = request.user.userprofile.company

    customer = get_object_or_404(
        Customer,
        id=customer_id,
        company=company
    )

    if request.method == "POST":

        customer.is_active = False
        customer.save()

        messages.success(
            request,
            "🗑 Customer deactivated successfully!"
        )

        return redirect("customer_list")

    return render(
        request,
        "core/delete_customer.html",
        {
            "customer": customer
        }
    )