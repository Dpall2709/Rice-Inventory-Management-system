"""
Sale money maths and stock, in one place.

    invoice lines       bags x bag weight x selling rate   = taxable amount
                        + GST per line (each rice can carry its own rate)
    tax split           CGST + SGST (same state) / IGST (other state) / none
    round off           grand total rounded to whole rupees
    = invoice total     what the customer owes you (rice only)

Transport is NOT part of the invoice total: it is shown for information and
settled between the customer and the truck.

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

TWO = Decimal("0.01")


def money(value):
    return Decimal(value or 0).quantize(TWO, rounding=ROUND_HALF_UP)


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


def compute_totals(items, tax_type):
    """
    Work out every total for one sale. Each SaleItem gets its computed fields
    filled in as a side effect, so the caller can just save them.
    """
    taxable = Decimal("0")
    gst_total = Decimal("0")
    bags = 0
    kg = Decimal("0")

    for item in items:
        if tax_type == Sale.NO_TAX:
            item.gst_percent = Decimal("0")
        item.compute()

        taxable += item.amount
        gst_total += item.gst_amount
        bags += int(item.bag_count or 0)
        kg += item.total_weight

    cgst = sgst = igst = Decimal("0")
    if tax_type == Sale.CGST_SGST:
        cgst = money(gst_total / 2)
        sgst = gst_total - cgst          # never lose a paisa on odd amounts
    elif tax_type == Sale.IGST:
        igst = gst_total

    before_round = taxable + cgst + sgst + igst
    rounded = before_round.quantize(Decimal("1"), rounding=ROUND_HALF_UP)

    # One rate across the bill is shown on old screens; mixed rates show 0.
    rates = {Decimal(item.gst_percent or 0) for item in items}
    single_rate = rates.pop() if len(rates) == 1 else Decimal("0")

    return {
        "total_bags": bags,
        "total_quantity_kg": money(kg),
        "taxable_amount": money(taxable),
        "gst_percent": single_rate,
        "cgst_amount": money(cgst),
        "sgst_amount": money(sgst),
        "igst_amount": money(igst),
        "gst_amount": money(cgst + sgst + igst),
        "round_off": money(rounded - before_round),
        "total_amount": money(rounded),
    }


def invoice_lines(sale):
    """
    The lines as the customer should see them. A truck filled from two or
    three mills is entered as several lines of the same product (one per
    lot); on the invoice they are one line - same product, bag size, rate
    and GST - with the bags and amounts added up.
    """
    from types import SimpleNamespace

    merged = {}
    order = []
    for item in sale.items.select_related("product").order_by("id"):
        key = (item.product_id, item.bag_weight, Decimal(item.rate_per_kg), Decimal(item.gst_percent))
        if key not in merged:
            merged[key] = SimpleNamespace(
                product=item.product, bag_weight=item.bag_weight, rate_per_kg=item.rate_per_kg,
                gst_percent=item.gst_percent, bag_count=0, total_weight=Decimal("0"),
                amount=Decimal("0"), gst_amount=Decimal("0"), line_total=Decimal("0"),
            )
            order.append(key)
        line = merged[key]
        line.bag_count += int(item.bag_count or 0)
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
        .select_related("product", "purchase", "purchase__mill")
        .order_by("purchase__purchase_date", "purchase__id", "id")
    )

    result = []
    for lot in lots:
        left = int(lot.bag_count or 0) - int(sold.get(lot.id, 0))
        if only_available and left <= 0:
            continue
        lot.bags_left = max(left, 0)
        result.append(lot)

    return result


def product_stock(company, exclude_sale=None):
    """Bags in stock per (product id, bag weight), from every purchase and sale."""
    bought = defaultdict(int)
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
    asked = defaultdict(int)

    errors = []
    plan = {}

    # Lines with a chosen lot go first, so FIFO lines cannot eat their bags.
    order = sorted(range(len(items)), key=lambda i: 0 if items[i].purchase_item_id else 1)

    for index in order:
        item = items[index]
        need = int(item.bag_count or 0)
        name = item.product.rice_name
        key = (item.product_id, int(item.bag_weight or 0))
        asked[key] += need

        if item.purchase_item_id:
            lot = by_id.get(item.purchase_item_id)
            available = left.get(item.purchase_item_id, 0)

            if lot is None:
                errors.append(_("%(rice)s: the chosen stock lot has no bags left.") % {"rice": name})
                continue
            if lot.product_id != item.product_id or int(lot.bag_weight) != int(item.bag_weight or 0):
                errors.append(
                    _("%(rice)s: the chosen lot is %(lot_rice)s in %(weight)s kg bags - it does not match this line.")
                    % {"rice": name, "lot_rice": lot.product.rice_name, "weight": lot.bag_weight}
                )
                continue
            if need > available:
                errors.append(
                    _("%(rice)s: only %(left)s bags left in lot %(lot)s, you asked for %(need)s.")
                    % {"rice": name, "left": available, "lot": lot.purchase.invoice_no, "need": need}
                )
                continue

            left[lot.id] -= need
            plan[index] = [(lot, need)]
            continue

        # FIFO: oldest lots of this rice and bag size first.
        taken = []
        remaining = need
        for lot in lots:
            if remaining <= 0:
                break
            if lot.product_id != item.product_id or int(lot.bag_weight) != int(item.bag_weight or 0):
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
                _("%(rice)s (%(weight)s kg bags): only %(left)s bags in stock, you asked for %(need)s.")
                % {"rice": name, "weight": item.bag_weight, "left": in_stock, "need": need}
            )
            continue

        plan[index] = taken

    # Old sales made before lots existed took stock without naming a lot, so
    # also check the plain "bought minus sold" total per rice and bag size.
    if not errors:
        for key, need in asked.items():
            available = totals.get(key, 0)
            if need > available:
                product = next(i.product for i in items if (i.product_id, int(i.bag_weight or 0)) == key)
                errors.append(
                    _("%(rice)s (%(weight)s kg bags): only %(left)s bags in stock, you asked for %(need)s.")
                    % {"rice": product.rice_name, "weight": key[1], "left": max(available, 0), "need": need}
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
    """
    with transaction.atomic():
        # Lock this company's lots for the moment we count them, so two people
        # cannot sell the same last bags at the same time.
        list(PurchaseItem.objects.for_company(company).select_for_update().values_list("id", flat=True))

        plan = allocate(company, items, exclude_sale=sale if sale.pk else None)

        totals = compute_totals(items, sale.tax_type)
        for field, value in totals.items():
            setattr(sale, field, value)

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
      - freight the party paid the driver   (when you carry the freight)
      + your freight advance                (when the party carries it)
      = net receivable   -> the customer ledger

    Before unloading, the received weight is taken as the dispatched weight.
    """
    billed = Decimal(sale.total_quantity_kg or 0)
    # The weighbridge weight at loading, when entered; else bags x bag weight.
    dispatched = Decimal(sale.loading_weight_kg) if sale.loading_weight_kg else billed
    received = Decimal(sale.received_weight_kg) if sale.received_weight_kg is not None else dispatched
    # The party pays the invoice rate on the weight they received.
    ratio = (received / billed) if billed else Decimal("1")

    total = Decimal(sale.total_amount or 0)
    party_value = money(total * ratio)
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

    rate_based = money(dispatched / Decimal("1000") * Decimal(sale.transport_rate_per_ton or 0))
    collected_by_broker = bool(sale.broker_id) and sale.collect_from == Sale.COLLECT_FROM_BROKER
    paid_by_us = money(sale.transport_paid_by_dealer)
    paid_by_party = money(sale.transport_paid_by_customer)
    freight_total = rate_based if rate_based > 0 else paid_by_us + paid_by_party

    if sale.freight_borne_by == Sale.FREIGHT_US:
        freight_adjustment = -paid_by_party
        freight_cost = freight_total
    elif sale.freight_borne_by == Sale.FREIGHT_CUSTOMER:
        freight_adjustment = paid_by_us
        freight_cost = Decimal("0.00")
    else:
        freight_adjustment = Decimal("0.00")
        freight_cost = Decimal("0.00")

    goods_payable = party_value - cash_discount - brokerage_cut - other
    net_receivable = money(goods_payable + freight_adjustment)

    return {
        "dispatched_kg": money(dispatched),
        "received_kg": money(received),
        "weight_loss_kg": money(dispatched - received),
        "unloaded": sale.received_weight_kg is not None,
        "party_value": party_value,
        "party_taxable": party_taxable,
        "cash_discount": cash_discount,
        "commission": commission,
        "party_pays_broker": party_pays_broker,
        "brokerage_cut": brokerage_cut,
        "other_deductions": other,
        "goods_payable": money(goods_payable),
        "freight_total": freight_total,
        "freight_paid_by_us": paid_by_us,
        "freight_paid_by_party": paid_by_party,
        "freight_adjustment": money(freight_adjustment),
        "freight_cost": money(freight_cost),
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
