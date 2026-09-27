"""
Add and edit a supplier - both use the same form and the same template.
"""

from core.forms import MillForm
from core.models import Mill
from core.permissions import manager_required
from core.tenancy import company_of, tenant_object_or_404

from ..base_imports import *


@login_required
def add_mill(request):
    company = company_of(request)

    if request.method == "POST":
        form = MillForm(request.POST, company=company)

        if form.is_valid():
            mill = form.save(commit=False)
            mill.company = company
            mill.save()

            messages.success(request, f"Supplier “{mill.mill_name}” saved.")

            # "Save and add another" keeps the user in the form.
            if request.POST.get("save_and_new"):
                return redirect("add_mill")

            return redirect("mill_report_detail", mill_id=mill.id)
    else:
        form = MillForm(company=company)

    return render(request, "core/mill_form.html", {
        "form": form,
        "mode": "add",
    })


@login_required
@manager_required
def edit_mill(request, mill_id):
    company = company_of(request)
    mill = tenant_object_or_404(Mill, request, mill_id)

    if request.method == "POST":
        form = MillForm(request.POST, instance=mill, company=company)

        if form.is_valid():
            form.save()
            messages.success(request, f"Supplier “{mill.mill_name}” updated.")
            return redirect("mill_report_detail", mill_id=mill.id)
    else:
        form = MillForm(instance=mill, company=company)

    return render(request, "core/mill_form.html", {
        "form": form,
        "mill": mill,
        "mode": "edit",
    })
