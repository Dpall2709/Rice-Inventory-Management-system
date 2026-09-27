"""
Purchase money maths, in one place.

    goods value (all item lines)
      - discount
      = taxable amount
      + CGST + SGST, or IGST, or no tax at all
      + freight + labour
      + round off
      = total you owe the mill

GST is charged on the value AFTER discount, which is how a GST bill works.
Freight and labour are added after tax here: on most rice bills they are
reimbursements rather than taxable supply. If a mill charges GST on freight
too, enter it as an item line instead.
"""

from decimal import Decimal, ROUND_HALF_UP

TWO_PLACES = Decimal("0.01")


def _money(value):
    return Decimal(value or 0).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def compute_totals(items, tax_type, discount=0, freight=0, labour=0):
    """
    Work out every total for one purchase.

    `items` is a list of PurchaseItem objects (saved or not). Each one gets its
    computed fields filled in as a side effect, so the caller can just save them.

    Returns a dictionary of the bill-level figures.
    """
    discount = Decimal(discount or 0)
    freight = Decimal(freight or 0)
    labour = Decimal(labour or 0)

    # 1. Goods value, before any discount.
    goods = Decimal("0")
    for item in items:
        kg = Decimal(item.bag_count or 0) * Decimal(item.bag_weight or 0)
        goods += kg * Decimal(item.purchase_price or 0)

    if discount > goods:
        discount = goods

    # 2. Spread the bill-level discount across the lines in proportion to their
    #    value, so each line's GST is charged on its discounted value.
    cgst = sgst = igst = Decimal("0")
    taxable_total = Decimal("0")
    gst_total = Decimal("0")

    for item in items:
        kg = Decimal(item.bag_count or 0) * Decimal(item.bag_weight or 0)
        line_goods = kg * Decimal(item.purchase_price or 0)

        share = (line_goods / goods * discount) if goods else Decimal("0")

        if tax_type == "none":
            item.gst_percent = Decimal("0")

        item.compute(discount_share=share)

        taxable_total += item.taxable_amount
        gst_total += item.gst_amount

    # 3. Split the tax the way this bill says.
    if tax_type == "cgst_sgst":
        cgst = gst_total / 2
        sgst = gst_total - cgst          # avoids losing a paisa on odd amounts
    elif tax_type == "igst":
        igst = gst_total

    # 4. Add the charges and round the grand total to whole rupees.
    before_round = taxable_total + cgst + sgst + igst + freight + labour
    rounded = before_round.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    round_off = rounded - before_round

    return {
        "goods_amount": _money(goods),
        "discount_amount": _money(discount),
        "taxable_amount": _money(taxable_total),
        "cgst_amount": _money(cgst),
        "sgst_amount": _money(sgst),
        "igst_amount": _money(igst),
        "freight_charge": _money(freight),
        "labour_charge": _money(labour),
        "round_off": _money(round_off),
        "total_amount": _money(rounded),
    }


def apply_totals(purchase, items, tax_type, discount=0, freight=0, labour=0):
    """Compute the totals and write them onto the purchase object."""
    totals = compute_totals(items, tax_type, discount, freight, labour)

    purchase.tax_type = tax_type
    for field, value in totals.items():
        setattr(purchase, field, value)

    return totals


def suggested_tax_type(company, mill):
    """
    A sensible default for the tax dropdown.

    Same state as your company -> CGST + SGST. Different state -> IGST. When
    either state is blank we cannot tell, so we suggest CGST + SGST.
    """
    company_state = (getattr(company, "state", "") or "").strip().lower()
    mill_state = (getattr(mill, "state", "") or "").strip().lower()

    if company_state and mill_state and company_state != mill_state:
        return "igst"

    return "cgst_sgst"
