from ..base_imports import *


@login_required
def mill_list(request):
    q = request.GET.get("q", "").strip()

    company = request.user.userprofile.company

    mills = (
        Mill.objects
        .filter(company=company)
        .order_by("-created_at")
    )

    if q:
        mills = mills.filter(
            Q(mill_name__icontains=q) |
            Q(owner_name__icontains=q) |
            Q(mobile__icontains=q)
        )

    return render(request, "core/mill_list.html", {"mills": mills})