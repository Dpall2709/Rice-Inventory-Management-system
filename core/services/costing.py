"""
What the rice really cost you, and what you need to sell it for.

The price on the mill's bill is not your cost. By the time a bag reaches your
godown you have also paid for a truck, for labour, sometimes brokerage. Selling
on the bill rate alone is how a trader works all season and still loses money.

    landed cost = taxable goods value
                + freight/labour the mill charged
                + every expense you paid yourself
    cost per kg = landed cost / total kg

GST is deliberately left out of the cost when the bill has GST: a registered
buyer claims it back as input credit, so counting it as cost would overstate
the price you need. On a kacha bill there is no GST to leave out.
"""

from decimal import Decimal, ROUND_HALF_UP

TWO = Decimal("0.01")


def _round(value):
    return Decimal(value or 0).quantize(TWO, rounding=ROUND_HALF_UP)


def purchase_costing(purchase, margin_percent=None):
    """
    The full cost picture for one purchase bill.

    Returns plain numbers ready for a template - no formatting, no side effects.
    """
    goods = Decimal(purchase.taxable_amount or 0)
    mill_charges = Decimal(purchase.freight_charge or 0) + Decimal(purchase.labour_charge or 0)
    own_expenses = Decimal(purchase.own_expense_total or 0)

    landed_cost = goods + mill_charges + own_expenses

    total_kg = Decimal(purchase.total_kg or 0)
    total_bags = Decimal(purchase.total_bags or 0)

    bill_rate_per_kg = (goods / total_kg) if total_kg else Decimal("0")
    cost_per_kg = (landed_cost / total_kg) if total_kg else Decimal("0")
    extra_per_kg = cost_per_kg - bill_rate_per_kg

    if margin_percent is None:
        margin_percent = getattr(purchase.company, "default_margin_percent", 0) or 0
    margin_percent = Decimal(margin_percent)

    suggested_per_kg = cost_per_kg * (Decimal("1") + margin_percent / Decimal("100"))

    average_bag_weight = (total_kg / total_bags) if total_bags else Decimal("0")

    return {
        "goods": _round(goods),
        "mill_charges": _round(mill_charges),
        "own_expenses": _round(own_expenses),
        "landed_cost": _round(landed_cost),

        "total_kg": _round(total_kg),
        "total_bags": int(total_bags),

        "bill_rate_per_kg": _round(bill_rate_per_kg),
        "cost_per_kg": _round(cost_per_kg),
        "extra_per_kg": _round(extra_per_kg),

        "margin_percent": _round(margin_percent),
        "suggested_per_kg": _round(suggested_per_kg),
        "suggested_per_bag": _round(suggested_per_kg * average_bag_weight),
        "profit_per_kg": _round(suggested_per_kg - cost_per_kg),
        "profit_on_this_bill": _round((suggested_per_kg - cost_per_kg) * total_kg),

        "average_bag_weight": _round(average_bag_weight),
        "gst_excluded": purchase.gst_amount or 0,
    }


def line_costing(purchase, margin_percent=None):
    """
    The same figures per rice type on the bill.

    Shared costs (mill charges and your own expenses) are spread across the
    lines by their value, so a costlier rice carries a bigger share of the
    truck fare - the same way the money was actually spent.
    """
    goods = Decimal(purchase.taxable_amount or 0)
    shared = (
        Decimal(purchase.freight_charge or 0)
        + Decimal(purchase.labour_charge or 0)
        + Decimal(purchase.own_expense_total or 0)
    )

    if margin_percent is None:
        margin_percent = getattr(purchase.company, "default_margin_percent", 0) or 0
    margin_percent = Decimal(margin_percent)

    rows = []

    for item in purchase.purchaseitem_set.select_related("product"):
        line_goods = Decimal(item.taxable_amount or 0)
        line_kg = Decimal(item.total_kg or 0)

        share = (line_goods / goods * shared) if goods else Decimal("0")
        line_cost = line_goods + share

        cost_per_kg = (line_cost / line_kg) if line_kg else Decimal("0")
        suggested = cost_per_kg * (Decimal("1") + margin_percent / Decimal("100"))

        rows.append({
            "item": item,
            "product": item.product,
            "bags": item.bag_count,
            "kg": _round(line_kg),
            "bill_rate_per_kg": _round(item.purchase_price),
            "share_of_expenses": _round(share),
            "landed_cost": _round(line_cost),
            "cost_per_kg": _round(cost_per_kg),
            "suggested_per_kg": _round(suggested),
            "suggested_per_bag": _round(suggested * Decimal(item.bag_weight or 0)),
            "profit_per_bag": _round((suggested - cost_per_kg) * Decimal(item.bag_weight or 0)),
        })

    return rows


def product_costing(company, product, margin_percent=None):
    """
    A weighted average cost per kg for one rice across every purchase.

    This is the number to look at before quoting a price: it answers "what does
    a kg of this rice cost me today, counting everything I paid".
    """
    from core.models import Purchase

    purchases = (
        Purchase.objects
        .for_company(company)
        .filter(purchaseitem__product=product)
        .distinct()
        .prefetch_related("purchaseitem_set", "expenses")
    )

    total_kg = Decimal("0")
    total_cost = Decimal("0")

    for purchase in purchases:
        for row in line_costing(purchase, margin_percent):
            if row["product"].id != product.id:
                continue
            total_kg += Decimal(row["kg"])
            total_cost += Decimal(row["landed_cost"])

    if margin_percent is None:
        margin_percent = getattr(company, "default_margin_percent", 0) or 0
    margin_percent = Decimal(margin_percent)

    cost_per_kg = (total_cost / total_kg) if total_kg else Decimal("0")

    return {
        "total_kg_bought": _round(total_kg),
        "total_cost": _round(total_cost),
        "cost_per_kg": _round(cost_per_kg),
        "margin_percent": _round(margin_percent),
        "suggested_per_kg": _round(cost_per_kg * (Decimal("1") + margin_percent / Decimal("100"))),
    }
