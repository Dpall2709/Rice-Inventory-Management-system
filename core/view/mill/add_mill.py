from ..base_imports import *
from django.shortcuts import render


@login_required
def add_mill(request):
    company = request.user.userprofile.company
    if request.method == "POST":
        Mill.objects.create(
             company=company,
            mill_name=request.POST.get("mill_name"),
            owner_name=request.POST.get("owner_name", ""),
            mobile=request.POST.get("mobile"),
            address=request.POST.get("address", ""),
            gst_number=request.POST.get("gst_number", ""),
            opening_balance=request.POST.get("opening_balance") or 0,
        )
        messages.success(request, "✅ Mill saved successfully!")
        return redirect("mill_list")

    return render(request, "core/add_mill.html")