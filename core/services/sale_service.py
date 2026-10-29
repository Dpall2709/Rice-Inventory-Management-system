"""
Sale money maths and stock, in one place.

    invoice lines       packs x pack size x selling rate   = taxable amount
                        + GST per line (each product can carry its own rate)
    tax split           CGST + SGST (same state) / IGST (other state) / none
                        (or the figures typed in by hand - see services/gst.py)
    + freight           only when the buyer pays it on this invoice (B, C)
    round off           grand total rounded to whole rupees
    = invoice total     what the customer owes you

How freight is carried is chosen per sale - see Sale.FREIGHT_CHOICES and
freight_figures() below.

Stock is tracked per purchase lot (one PurchaseItem = one lot):

    lot stock = bags bought in that lot - bags sold out of it (SaleLot)

Every bag sold is tied to the lot it came out of. If the user does not pick a
lot, the oldest stock of that rice and bag size goes first (FIFO), which is
how a godown is actually emptied.
"""

from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP

from django.db import transaction
from django.db.models import Sum
from django.utils.translation import gettext as _

from core.models import Broker, PurchaseItem, Sale, SaleItem, SaleLot
from core.utils import qty_str

TWO = Decimal("0.01")


def money(value):
    return Decimal(value or 0).quantize(TWO, rounding=ROUND_HALF_UP)


def quantity(value):
    """Quantities and weights keep 3 decimals (12.345 kg)."""
    return Decimal(value or 0).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)


class StockError(Exception):
    """Raised when a sale asks for more bags than are in stock."""

    def __init__(self, messages):
        super().__init__("; ".join(messages))
        self.messages = messages


# --------------------------------------------------------------------------
# Tax and totals
# --------------------------------------------------------------------------

def suggested_tax_type(company, customer):
    """
    Same state as your company -> CGST + SGST. Different state -> IGST. When
    either state is blank we cannot tell, so we suggest CGST + SGST.
    """
    company_state = (getattr(company, "state", "") or "").strip().lower()
    customer_state = (getattr(customer, "state", "") or "").strip().lower()

    if company_state and customer_state and company_state != customer_state:
        return Sale.IGST

    return Sale.CGST_SGST


def compute_totals(items, tax_type, freight=0, manual=(None, None, None)):
    """
    Work out every total for one sale. Each SaleItem gets its computed fields
    filled in as a side effect, so the caller can just save them.

    `freight` is freight added to this invoice (scenarios B and C). `manual`
    is the hand-typed (cgst, sgst, igst), None where automatic.
    """
    from core.services.gst import apply_manual, split_gst

    taxable = Decimal("0")
    gst_total = Decimal("0")
    bags = Decimal("0")
    kg = Decimal("0")

    for item in items:
        if tax_type == Sale.NO_TAX:
            item.gst_percent = Decimal("0")
        item.compute()

        taxable += item.amount
        gst_total += item.gst_amount
        bags += Decimal(item.bag_count or 0)
        kg += item.total_weight

    cgst, sgst, igst = apply_manual(split_gst(gst_total, tax_type), manual, tax_type)

    freight = money(freight)
    before_round = taxable + cgst + sgst + igst + freight
    rounded = before_round.quantize(Decimal("1"), rounding=ROUND_HALF_UP)

    # One rate across the bill is shown on old screens; mixed rates show 0.
    rates = {Decimal(item.gst_percent or 0) for item in items}
    single_rate = rates.pop() if len(rates) == 1 else Decimal("0")

    return {
        "total_bags": bags,
        "total_quantity_kg": quantity(kg),
        "taxable_amount": money(taxable),
        "gst_percent": single_rate,
        "cgst_amount": money(cgst),
        "sgst_amount": money(sgst),
        "igst_amount": money(igst),
        "gst_amount": money(cgst + sgst + igst),
        "freight_on_invoice": freight,
        "round_off": money(rounded - before_round),
        "total_amount": money(rounded),
    }


def calculated_gst(items, tax_type):
    """The (cgst, sgst, igst) the app works out, ignoring any manual figures."""
    totals = compute_totals(items, tax_type)
    return totals["cgst_amount"], totals["sgst_amount"], totals["igst_amount"]


def invoice_lines(sale):
    """
    The lines as the customer should see them. A truck filled from two or
    three mills is entered as several lines of the same product (one per
    lot); on the invoice they are one line - same product, pack size, rate
    and GST - with the quantities and amounts added up.
    """
    from types import SimpleNamespace

    merged = {}
    order = []
    for item in sale.items.select_related("product").order_by("id"):
        key = (item.product_id, item.bag_weight, Decimal(item.rate_per_kg), Decimal(item.gst_percent))
        if key not in merged:
            merged[key] = SimpleNamespace(
                product=item.product, bag_weight=item.bag_weight, rate_per_kg=item.rate_per_kg,
                gst_percent=item.gst_percent, bag_count=Decimal("0"), total_weight=Decimal("0"),
                amount=Decimal("0"), gst_amount=Decimal("0"), line_total=Decimal("0"),
            )
            order.append(key)
        line = merged[key]
        line.bag_count += Decimal(item.bag_count or 0)
        line.total_weight += Decimal(item.total_weight or 0)
        line.amount += Decimal(item.amount or 0)
        line.gst_amount += Decimal(item.gst_amount or 0)
        line.line_total += Decimal(item.line_total or 0)
    return [merged[key] for key in order]


def amount_in_words(amount):
    """
    "Rupees Eight Lakh, Seventy-Five Thousand Only" - the Indian system
    (lakh, crore) as printed on bills. num2words has no Hindi, so this stays
    in English on Hindi screens too, as it does on most Indian invoices.
    """
    from num2words import num2words

    rupees = int(Decimal(amount or 0).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return "Rupees " + num2words(rupees, lang="en_IN").title() + " Only"


def broker_commission(commission_type, rate, bags, kg, taxable):
    """The broker's cut on one sale."""
    rate = Decimal(rate or 0)
    if rate <= 0:
        return Decimal("0.00")

    if commission_type == Broker.PER_BAG:
        return money(rate * Decimal(bags or 0))
    if commission_type == Broker.PER_KG:
        return money(rate * Decimal(kg or 0))
    if commission_type == Broker.PER_QUINTAL:
        return money(rate * Decimal(kg or 0) / Decimal("100"))
    if commission_type == Broker.PERCENT:
        return money(Decimal(taxable or 0) * rate / Decimal("100"))

    return Decimal("0.00")


# --------------------------------------------------------------------------
# Stock
# --------------------------------------------------------------------------

def _sold_per_lot(company, exclude_sale=None):
    lots = SaleLot.objects.for_company(company)
    if exclude_sale is not None and exclude_sale.pk:
        lots = lots.exclude(sale=exclude_sale)

    return {
        row["purchase_item"]: row["bags"] or 0
        for row in lots.values("purchase_item").annotate(bags=Sum("bag_count"))
    }


def _sold_per_product(company, exclude_sale=None):
    """Bags sold per (product, bag weight), counting old sales that have no lots."""
    items = SaleItem.objects.for_company(company)
    if exclude_sale is not None and exclude_sale.pk:
        items = items.exclude(sale=exclude_sale)

    return {
        (row["product"], row["bag_weight"]): row["bags"] or 0
        for row in items.values("product", "bag_weight").annotate(bags=Sum("bag_count"))
    }


def stock_lots(company, exclude_sale=None, only_available=True):
    """
    Every purchase lot with the bags still left in it, oldest first.

    `exclude_sale` leaves one sale out of the "sold" count - used when editing
    that sale, so its own bags are available to it again.
    """
    sold = _sold_per_lot(company, exclude_sale)

    lots = (
        PurchaseItem.objects
        .for_company(company)
        .select_related("product", "product__unit", "product__rate_unit", "purchase", "purchase__mill")
        .order_by("purchase__purchase_date", "purchase__id", "id")
    )

    result = []
    for lot in lots:
        left = Decimal(lot.bag_count or 0) - Decimal(sold.get(lot.id, 0))
        if only_available and left <= 0:
            continue
        lot.bags_left = max(left, 0)
        result.append(lot)

    return result


def product_stock(company, exclude_sale=None):
    """Bags in stock per (product id, bag weight), from every purchase and sale."""
    bought = defaultdict(Decimal)
    for row in (
        PurchaseItem.objects.for_company(company)
        .values("product", "bag_weight")
        .annotate(bags=Sum("bag_count"))
    ):
        bought[(row["product"], row["bag_weight"])] += row["bags"] or 0

    sold = _sold_per_product(company, exclude_sale)

    keys = set(bought) | set(sold)
    return {key: bought.get(key, 0) - sold.get(key, 0) for key in keys}


def allocate(company, items, exclude_sale=None):
    """
    Decide which lots each sale line's bags come out of.

    Returns {index of item: [(lot, bags), ...]}. Raises StockError listing
    every line that cannot be filled, so the user sees all problems at once.
    """
    lots = stock_lots(company, exclude_sale=exclude_sale)
    left = {lot.id: lot.bags_left for lot in lots}
    by_id = {lot.id: lot for lot in lots}

    totals = product_stock(company, exclude_sale=exclude_sale)
    asked = defaultdict(Decimal)

    errors = []
    plan = {}

    # Lines with a chosen lot go first, so FIFO lines cannot eat their bags.
    order = sorted(range(len(items)), key=lambda i: 0 if items[i].purchase_item_id else 1)

    for index in order:
        item = items[index]
        need = Decimal(item.bag_count or 0)
        name = item.product.name
        unit = item.product.unit_label
        key = (item.product_id, Decimal(item.bag_weight or 0))
        asked[key] += need

        if item.purchase_item_id:
            lot = by_id.get(item.purchase_item_id)
            available = left.get(item.purchase_item_id, 0)

            if lot is None:
                errors.append(_("%(product)s: the chosen stock lot is empty.") % {"product": name})
                continue
            if lot.product_id != item.product_id or Decimal(lot.bag_weight) != Decimal(item.bag_weight or 0):
                errors.append(
                    _("%(product)s: the chosen lot is %(lot_product)s with pack size %(size)s - it does not match this line.")
                    % {"product": name, "lot_product": lot.product.name, "size": qty_str(lot.bag_weight)}
                )
                continue
            if need > available:
                errors.append(
                    _("%(product)s: only %(left)s %(unit)s left in lot %(lot)s, you asked for %(need)s.")
                    % {"product": name, "left": qty_str(available), "unit": unit,
                       "lot": lot.purchase.invoice_no, "need": qty_str(need)}
                )
                continue

            left[lot.id] -= need
            plan[index] = [(lot, need)]
            continue

        # FIFO: oldest lots of this product and pack size first.
        taken = []
        remaining = need
        for lot in lots:
            if remaining <= 0:
                break
            if lot.product_id != item.product_id or Decimal(lot.bag_weight) != Decimal(item.bag_weight or 0):
                continue
            available = left.get(lot.id, 0)
            if available <= 0:
                continue
            use = min(available, remaining)
            left[lot.id] -= use
            remaining -= use
            taken.append((lot, use))

        if remaining > 0:
            in_stock = need - remaining
            errors.append(
                _("%(product)s (pack size %(size)s): only %(left)s %(unit)s in stock, you asked for %(need)s.")
                % {"product": name, "size": qty_str(item.bag_weight), "left": qty_str(in_stock),
                   "unit": unit, "need": qty_str(need)}
            )
            continue

        plan[index] = taken

    # Old sales made before lots existed took stock without naming a lot, so
    # also check the plain "bought minus sold" total per rice and bag size.
    if not errors:
        for key, need in asked.items():
            available = totals.get(key, 0)
            if need > available:
                product = next(i.product for i in items if (i.product_id, Decimal(i.bag_weight or 0)) == key)
                errors.append(
                    _("%(product)s (pack size %(size)s): only %(left)s %(unit)s in stock, you asked for %(need)s.")
                    % {"product": product.name, "size": qty_str(key[1]), "left": qty_str(max(available, 0)),
                       "unit": product.unit_label, "need": qty_str(need)}
                )

    if errors:
        raise StockError(errors)

    return plan


def lot_cost_per_kg(lot, cache):
    """Landed cost per kg of one purchase lot (bill rate + its share of expenses, no GST)."""
    from core.services.costing import line_costing

    purchase = lot.purchase
    if purchase.id not in cache:
        cache[purchase.id] = {
            row["item"].id: Decimal(row["cost_per_kg"])
            for row in line_costing(purchase)
        }
    return cache[purchase.id].get(lot.id, Decimal(lot.purchase_price or 0))


# --------------------------------------------------------------------------
# Saving
# --------------------------------------------------------------------------

def save_sale(sale, items, company):
    """
    Save a sale with its lines and lot breakup, all or nothing.

    `sale` is an unsaved or existing Sale with its header fields set (customer
    snapshot, broker, tax type, transport...). `items` are unsaved SaleItem
    objects. On edit, the old lines and lots are replaced.

    Raises StockError when the stock does not cover the lines.
    Manual GST figures set on `sale` (manual_cgst...) are kept and applied.
    """
    with transaction.atomic():
        # Lock this company's lots for the moment we count them, so two people
        # cannot sell the same last bags at the same time.
        list(PurchaseItem.objects.for_company(company).select_for_update().values_list("id", flat=True))

        plan = allocate(company, items, exclude_sale=sale if sale.pk else None)

        from core.services.gst import clear_unused_manual, manual_values

        clear_unused_manual(sale)
        manual = manual_values(sale)
        totals = compute_totals(items, sale.tax_type, manual=manual)
        for field, value in totals.items():
            setattr(sale, field, value)

        # Freight on the invoice needs the weight, so it is added second.
        on_invoice = freight_figures(sale)["on_invoice"]
        if on_invoice:
            totals = compute_totals(items, sale.tax_type, freight=on_invoice, manual=manual)
            for field, value in totals.items():
                setattr(sale, field, value)

        if sale.freight_borne_by == Sale.FREIGHT_BILL and not sale.transport_invoice_no:
            from core.services.invoice_number import next_number

            sale.transport_invoice_no = next_number(company, "TRN", sale.sale_date)

        if not sale.broker_id:
            sale.broker_commission_type = ""
            sale.broker_commission_rate = Decimal("0")

        apply_settlement(sale)
        sale.company = company
        sale.save()

        # On edit, the old lines and lots are replaced by the new ones.
        SaleLot.objects.filter(sale=sale).delete()
        SaleItem.objects.filter(sale=sale).delete()

        cost_cache = {}
        for index, item in enumerate(items):
            item.pk = None
            item.sale = sale
            taken = plan.get(index, [])
            mills = {lot.purchase.mill_id for lot, _bags in taken}
            item.mill = taken[0][0].purchase.mill if len(mills) == 1 else None
            item.save()

            for lot, bags in taken:
                kg = Decimal(bags) * Decimal(lot.bag_weight)
                cost_per_kg = money(lot_cost_per_kg(lot, cost_cache))
                SaleLot.objects.create(
                    sale=sale,
                    sale_item=item,
                    purchase_item=lot,
                    mill=lot.purchase.mill,
                    bag_count=bags,
                    total_kg=kg,
                    buy_rate_per_kg=lot.purchase_price,
                    cost_per_kg=cost_per_kg,
                    cost_amount=money(kg * cost_per_kg),
                )

    return sale


def freight_figures(sale, dispatched_kg=None):
    """
    Who owes what for the truck, for every freight arrangement.

        total freight    = the amount typed in, else weight x rate per ton,
                           else what was paid to the driver
        buyer's share    = A, E: 0 · B, D: all of it · C: the share typed in
        on the invoice   = the buyer's share for B and C (D gets its own bill)
        adjustment       = buyer's share - what the buyer paid the driver
                           (added to / cut from what the buyer owes you)
        your cost        = total freight - buyer's share

    "Separate" freight is between the buyer and the truck: none of it is in
    your books.
    """
    if dispatched_kg is None:
        dispatched_kg = Decimal(sale.loading_weight_kg or 0) or Decimal(sale.total_quantity_kg or 0)

    paid_by_us = money(sale.transport_paid_by_dealer)
    paid_by_party = money(sale.transport_paid_by_customer)
    entered = money(sale.freight_amount)
    rate_based = money(Decimal(dispatched_kg) / Decimal("1000") * Decimal(sale.transport_rate_per_ton or 0))
    if entered > 0:
        total = entered
    elif rate_based > 0:
        total = rate_based
    else:
        total = paid_by_us + paid_by_party

    mode = sale.freight_borne_by
    zero = Decimal("0.00")
    if mode == Sale.FREIGHT_SEPARATE:
        return {
            "total": total, "paid_by_us": paid_by_us, "paid_by_party": paid_by_party,
            "customer_share": zero, "on_invoice": zero, "adjustment": zero, "cost": zero,
        }

    if mode in (Sale.FREIGHT_CUSTOMER, Sale.FREIGHT_BILL):
        share = total
    elif mode == Sale.FREIGHT_SHARED:
        share = min(money(sale.freight_customer_share), total)
    else:   # seller pays (A) or freight is inside the rate (E)
        share = zero

    return {
        "total": total,
        "paid_by_us": paid_by_us,
        "paid_by_party": paid_by_party,
        "customer_share": share,
        "on_invoice": share if mode in Sale.FREIGHT_ON_INVOICE else zero,
        "adjustment": money(share - paid_by_party),
        "cost": money(total - share),
    }


def settlement(sale):
    """
    The truck's money from dispatch to final payment, the way a rice trader's
    register works it out:

        party value      = invoice value on the weight the party RECEIVED
                           (transit shortage is your loss, not theirs)
      - cash discount    = CD % of the party value
      - brokerage        = only when the party pays the broker and cuts it
      - other deductions
      = what the party pays for the goods
      + the buyer's share of the freight    (on this invoice or a transport bill)
      - freight the party paid the driver
      = net receivable   -> the customer ledger

    Before unloading, the received weight is taken as the dispatched weight.
    """
    billed = Decimal(sale.total_quantity_kg or 0)
    # The weighbridge weight at loading, when entered; else bags x bag weight.
    dispatched = Decimal(sale.loading_weight_kg) if sale.loading_weight_kg else billed
    received = Decimal(sale.received_weight_kg) if sale.received_weight_kg is not None else dispatched
    # The party pays the invoice rate on the weight they received.
    ratio = (received / billed) if billed else Decimal("1")

    # Freight on the invoice is not shrunk by a transit shortage, and no CD
    # is taken on it - only the goods are.
    goods_total = Decimal(sale.total_amount or 0) - Decimal(sale.freight_on_invoice or 0)
    party_value = money(goods_total * ratio)
    party_taxable = money(Decimal(sale.taxable_amount or 0) * ratio)

    commission = broker_commission(
        sale.broker_commission_type if sale.broker_id else "",
        sale.broker_commission_rate if sale.broker_id else 0,
        sale.total_bags,
        received,
        party_taxable,
    )
    # Brokerage is cut from the payment when the broker collects for you
    # (he keeps it), or when the party pays the broker directly.
    party_pays_broker = bool(sale.broker_id) and (
        sale.broker_paid_by == Sale.BROKER_PAID_BY_CUSTOMER
        or sale.collect_from == Sale.COLLECT_FROM_BROKER
    )
    brokerage_cut = commission if party_pays_broker else Decimal("0.00")

    cash_discount = money(party_value * Decimal(sale.cash_discount_percent or 0) / Decimal("100"))
    other = money(sale.other_deductions)

    collected_by_broker = bool(sale.broker_id) and sale.collect_from == Sale.COLLECT_FROM_BROKER
    freight = freight_figures(sale, dispatched)

    goods_payable = party_value - cash_discount - brokerage_cut - other
    net_receivable = money(goods_payable + freight["adjustment"])

    return {
        "dispatched_kg": quantity(dispatched),
        "received_kg": quantity(received),
        "weight_loss_kg": quantity(dispatched - received),
        "unloaded": sale.received_weight_kg is not None,
        "party_value": party_value,
        "party_taxable": party_taxable,
        "cash_discount": cash_discount,
        "commission": commission,
        "party_pays_broker": party_pays_broker,
        "brokerage_cut": brokerage_cut,
        "other_deductions": other,
        "goods_payable": money(goods_payable),
        "freight_total": freight["total"],
        "freight_paid_by_us": freight["paid_by_us"],
        "freight_paid_by_party": freight["paid_by_party"],
        "freight_customer_share": freight["customer_share"],
        "freight_on_invoice": freight["on_invoice"],
        "freight_adjustment": freight["adjustment"],
        "freight_cost": freight["cost"],
        "net_receivable": net_receivable,
        "collected_by_broker": collected_by_broker,
    }


def apply_settlement(sale):
    """Store the settlement figures on the sale (it is not saved here)."""
    figures = settlement(sale)
    sale.transport_charge = figures["freight_total"]
    sale.broker_commission = figures["commission"]
    sale.cash_discount_amount = figures["cash_discount"]
    sale.net_receivable = figures["net_receivable"]
    sale.balance_amount = figures["net_receivable"] - Decimal(sale.advance_received or 0)
    return figures


def sale_profit(sale):
    """
    What this truck earned you.

        party value before GST, on the received weight
      - cash discount, brokerage the party cut, other deductions
      = your sale income
      - landed cost of the bags sold (mill rate + purchase expenses, no GST)
      - loading charge
      - freight you carry (advance + what the party paid the driver for you)
      - broker commission you pay yourself
      = profit

    GST is not your income and is left out. Old sales have no lot breakup,
    so their cost is unknown (None).
    """
    lots = list(sale.lots.select_related("purchase_item__product", "mill", "purchase_item__purchase"))
    figures = settlement(sale)

    income = (
        figures["party_taxable"] - figures["cash_discount"]
        - figures["brokerage_cut"] - figures["other_deductions"]
    )
    commission_we_pay = Decimal("0.00") if figures["party_pays_broker"] else figures["commission"]
    loading = money(sale.loading_charge)

    base = {
        "lots": lots,
        "settlement": figures,
        "income": money(income),
        "loading": loading,
        "freight_cost": figures["freight_cost"],
        "commission_we_pay": commission_we_pay,
    }

    if not lots:
        return {**base, "cost": None, "goods_cost": None, "profit": None, "margin_percent": None}

    goods_cost = sum((Decimal(lot.cost_amount) for lot in lots), Decimal("0"))
    cost = goods_cost + loading + figures["freight_cost"] + commission_we_pay
    profit = income - cost
    margin = (profit / income * 100) if income else Decimal("0")

    return {
        **base,
        "goods_cost": money(goods_cost),
        "cost": money(cost),
        "profit": money(profit),
        "margin_percent": money(margin),
    }


# --------------------------------------------------------------------------
# Profit earned so far - one rule for every screen
# --------------------------------------------------------------------------

PAID = "paid"
PART_PAID = "partial"
UNPAID = "due"


def payment_status(received, due):
    if due <= 0:
        return PAID
    return PART_PAID if received > 0 else UNPAID


def earned_profit(total_profit, sale_amount, received):
    """
    How much of a sale's profit is really in hand.

        profit earned = total profit x (received / what the party owes)

    Half the money in -> half the profit earned; all of it in -> the full
    profit. A LOSS is counted in full at once: it does not shrink just
    because the party has not paid yet. Returns (earned, pending); both are
    None when the sale's cost is unknown.
    """
    if total_profit is None:
        return None, None
    total_profit = Decimal(total_profit)
    if total_profit <= 0:
        return money(total_profit), Decimal("0.00")
    sale_amount = Decimal(sale_amount or 0)
    share = min(Decimal(received or 0) / sale_amount, Decimal("1")) if sale_amount > 0 else Decimal("0")
    earned = money(total_profit * share)
    return earned, money(total_profit - earned)
