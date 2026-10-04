"""
Deactivating and deleting a supplier.

The rule: a mill that has purchases, payments or sale items can NEVER be
deleted, because deleting it would cascade and destroy that history along with
the stock figures that depend on it. It is deactivated instead - hidden from
dropdowns, but every record stays.

A mill with no records at all (added by mistake) can be deleted properly.
"""

from django.utils.translation import gettext as _

from core.models import Mill
from core.permissions import manager_required
from core.tenancy import tenant_object_or_404

from ..base_imports import *


@login_required
@manager_required
def delete_mill(request, mill_id):
    """Confirmation screen + the deactivate / delete action."""
    mill = tenant_object_or_404(Mill, request, mill_id)

    purchase_count = mill.purchase_set.count()
    payment_count = mill.payment_set.count()
    sale_item_count = mill.saleitem_set.count()
    can_delete = mill.can_be_deleted()

    if request.method == "POST":
        action = request.POST.get("action", "deactivate")

        if action == "delete":
            if not can_delete:
                messages.error(
                    request,
                    _(
                        "“%(mill)s” cannot be deleted because it has "
                        "%(purchases)s purchase(s) and %(payments)s payment(s). "
                        "Deactivate it instead - the history stays safe."
                    ) % {"mill": mill.mill_name, "purchases": purchase_count, "payments": payment_count},
                )
                return redirect("delete_mill", mill_id=mill.id)

            name = mill.mill_name
            mill.delete()
            messages.success(request, _("Supplier “%(mill)s” deleted.") % {"mill": name})
            return redirect("mill_list")

        mill.is_active = False
        mill.save(update_fields=["is_active", "updated_at"])
        messages.success(
            request,
            _(
                "“%(mill)s” deactivated. It is hidden from new entries; "
                "its history is unchanged."
            ) % {"mill": mill.mill_name},
        )
        return redirect("mill_list")

    return render(request, "core/delete_mill.html", {
        "mill": mill,
        "purchase_count": purchase_count,
        "payment_count": payment_count,
        "sale_item_count": sale_item_count,
        "can_delete": can_delete,
    })


@login_required
@manager_required
def restore_mill(request, mill_id):
    """Bring a deactivated supplier back."""
    mill = tenant_object_or_404(Mill, request, mill_id)

    if request.method == "POST":
        mill.is_active = True
        mill.save(update_fields=["is_active", "updated_at"])
        messages.success(request, _("“%(mill)s” is active again.") % {"mill": mill.mill_name})

    return redirect("mill_list")
