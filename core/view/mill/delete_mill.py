from ..base_imports import *

@login_required
def delete_mill(request, mill_id):
    company = request.user.userprofile.company

    mill = get_object_or_404(
        Mill,
        id=mill_id,
        company=company
    )

    if request.method == "POST":
        mill.delete()
        messages.success(request, "Mill deleted successfully 🗑️")
        return redirect("mill_list")

    return render(request, "core/delete_mill.html", {"mill": mill})