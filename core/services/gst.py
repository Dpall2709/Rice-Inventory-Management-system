"""
GST split and manual GST adjustment, shared by sales and purchases.

The app always works out the tax itself. A user can then type the CGST, SGST
or IGST printed on the actual bill when it differs by a few paise (rounding
done line-by-line versus on the total, for example). The typed figure wins,
the bill total is worked out again, and a TaxAdjustment row keeps the audit
trail: what was calculated, what was entered, by whom, and why.
"""

from decimal import Decimal, ROUND_HALF_UP

TWO = Decimal("0.01")


def money(value):
    return Decimal(value or 0).quantize(TWO, rounding=ROUND_HALF_UP)


def split_gst(gst_total, tax_type):
    """(cgst, sgst, igst) for a tax total, rounded to paise."""
    gst_total = Decimal(gst_total or 0)
    if tax_type == "cgst_sgst":
        cgst = money(gst_total / 2)
        return cgst, money(gst_total) - cgst, Decimal("0.00")   # never lose a paisa
    if tax_type == "igst":
        return Decimal("0.00"), Decimal("0.00"), money(gst_total)
    return Decimal("0.00"), Decimal("0.00"), Decimal("0.00")


def manual_values(obj):
    """The manual (cgst, sgst, igst) on a sale or purchase - None where automatic."""
    if obj is None:
        return (None, None, None)
    return (
        getattr(obj, "manual_cgst", None),
        getattr(obj, "manual_sgst", None),
        getattr(obj, "manual_igst", None),
    )


def apply_manual(calculated, manual, tax_type):
    """
    The tax to use: each manual figure replaces its calculated one, but only
    for the heads this bill actually has (no IGST on a same-state bill).
    """
    cgst, sgst, igst = calculated
    m_cgst, m_sgst, m_igst = manual
    if tax_type == "cgst_sgst":
        if m_cgst is not None:
            cgst = money(m_cgst)
        if m_sgst is not None:
            sgst = money(m_sgst)
    elif tax_type == "igst" and m_igst is not None:
        igst = money(m_igst)
    return cgst, sgst, igst


def clear_unused_manual(obj):
    """Drop manual figures that do not belong to the bill's tax type."""
    if obj.tax_type != "cgst_sgst":
        obj.manual_cgst = obj.manual_sgst = None
    if obj.tax_type != "igst":
        obj.manual_igst = None
    if not obj.gst_is_manual:
        obj.gst_adjust_reason = ""


def saved_manual_values(obj):
    """manual_values() as stored in the database - call before saving an edit."""
    if not obj.pk:
        return (None, None, None)
    row = (
        type(obj).objects.filter(pk=obj.pk)
        .values_list("manual_cgst", "manual_sgst", "manual_igst")
        .first()
    )
    return row or (None, None, None)


def record_adjustment(obj, before, calculated, user=None):
    """
    Write a TaxAdjustment row when the manual GST on `obj` changed in this save.

    `before` is manual_values(obj) as it was before the save; `calculated` is
    the (cgst, sgst, igst) the app worked out.
    """
    from core.models import Purchase, TaxAdjustment

    after = manual_values(obj)
    norm = lambda values: tuple(None if v is None else money(v) for v in values)
    if norm(before) == norm(after):
        return None

    is_purchase = isinstance(obj, Purchase)
    return TaxAdjustment.objects.create(
        company=obj.company,
        purchase=obj if is_purchase else None,
        sale=None if is_purchase else obj,
        user=user if getattr(user, "is_authenticated", False) else None,
        calculated_cgst=calculated[0],
        calculated_sgst=calculated[1],
        calculated_igst=calculated[2],
        entered_cgst=after[0],
        entered_sgst=after[1],
        entered_igst=after[2],
        reason=obj.gst_adjust_reason or ("Reset to automatic" if not any(v is not None for v in after) else ""),
    )
