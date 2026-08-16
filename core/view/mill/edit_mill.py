from ..base_imports import *

@login_required
def edit_mill(request, mill_id):
    company = request.user.userprofile.company

    mill = get_object_or_404(
        Mill,
        id=mill_id,
        company=company
    )

    if request.method == "POST":
        mill.mill_name = request.POST.get("mill_name")
        mill.owner_name = request.POST.get("owner_name", "")
        mill.mobile = request.POST.get("mobile")
        mill.address = request.POST.get("address", "")
        mill.gst_number = request.POST.get("gst_number", "")
        mill.opening_balance = request.POST.get("opening_balance") or 0
        mill.save()

        messages.success(request, "Mill updated successfully ✅")
        return redirect("mill_list")

    return render(request, "core/edit_mill.html", {"mill": mill})