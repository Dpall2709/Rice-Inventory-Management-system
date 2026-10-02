"""
The owner's dashboard: how the business is doing, and what to do today.

Every function here takes a company and returns plain dicts of Decimals, ints
and model instances - no formatting, no request. The view stitches them
together and the template only displays them.

It deliberately reuses the ledgers instead of re-deriving dues:

    customer dues      services.customer_ledger.customer_statement
    mill dues          services.ledger.mill_statement
    broker commission  services.customer_ledger.broker_statement
    stock              services.sale_service.product_stock / stock_lots
    landed cost        services.costing (via the lot cost used when selling)

Profit uses the same formula as services.sale_service.sale_profit (selling
value before GST - landed cost of the lots sold - broker commission), but as
one aggregate query instead of one query per sale.
"""

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from urllib.parse import quote

from django.db.models import Count, Q, Sum
from django.utils import timezone
from django.utils.translation import gettext as _

from core.models import (
    Broker, Customer, Mill, Payment, Product, Purchase, Sale, SaleItem,
)
from core.services.costing import product_costing
from core.services.customer_ledger import (
    broker_collections, broker_statement, customer_statement, sale_payment_status,
)
from core.services.ledger import mill_statement
from core.services.sale_service import lot_cost_per_kg, money, product_stock, settlement, stock_lots

ZERO = Decimal("0")

# Thresholds - kept here so they are easy to find and tune.
LOW_STOCK_BAGS = 20            # this many bags or fewer is "low"
LOW_STOCK_DAYS = 7             # or fewer days of cover than this
SALES_WINDOW_DAYS = 30         # window for "average daily sales"
OLD_INVOICE_DAYS = 15          # invoice without a due date counts as late after this
SLOW_STOCK_DAYS = 45           # a lot older than this ...
SLOW_NO_SALE_DAYS = 30         # ... whose rice has not sold in this long is "stuck"
TOP_N = 5
ACTION_LIMIT = 8               # rows shown per action group

PERIODS = ("today", "month", "last_month", "fy")
DEFAULT_PERIOD = "month"


def _d(value):
    return Decimal(value or 0)


def _month_start(day):
    return day.replace(day=1)


def _add_months(day, months):
    """First day of the month `months` away from `day`'s month."""
    index = day.year * 12 + (day.month - 1) + months
    return date(index // 12, index % 12 + 1, 1)


def _month_end(day):
    return _add_months(day, 1) - timedelta(days=1)


# --------------------------------------------------------------------------
# Period
# --------------------------------------------------------------------------

def period_range(period, today=None):
    """
    (key, start, end, label) for ?period=. Unknown values fall back to this
    month. The Indian financial year runs 1 April - 31 March.
    """
    today = today or timezone.localdate()
    if period not in PERIODS:
        period = DEFAULT_PERIOD

    if period == "today":
        return {"key": period, "start": today, "end": today, "label": _("Today")}

    if period == "last_month":
        start = _add_months(today, -1)
        return {"key": period, "start": start, "end": _month_end(start), "label": _("Last month")}

    if period == "fy":
        year = today.year if today.month >= 4 else today.year - 1
        return {
            "key": period,
            "start": date(year, 4, 1),
            "end": date(year + 1, 3, 31),
            "label": _("FY %(start)s-%(end)s") % {"start": year, "end": str(year + 1)[-2:]},
        }

    start = _month_start(today)
    return {"key": "month", "start": start, "end": _month_end(start), "label": _("This month")}


def period_choices():
    return [
        {"key": "today", "label": _("Today")},
        {"key": "month", "label": _("This month")},
        {"key": "last_month", "label": _("Last month")},
        {"key": "fy", "label": _("This financial year")},
    ]


# --------------------------------------------------------------------------
# Period numbers
# --------------------------------------------------------------------------

def _sales_with_cost(company):
    """Sales annotated with the landed cost and number of their lots."""
    return (
        Sale.objects.for_company(company)
        .annotate(lot_cost=Sum("lots__cost_amount"), lot_count=Count("lots"))
    )


def _profit_of(sale):
    """
    Same maths as sale_service.sale_profit(), for a Sale annotated with
    lot_cost / lot_count (one query for many sales). Returns (income, profit);
    profit is None when the sale has no lot data.
    """
    figures = settlement(sale)
    income = (
        figures["party_taxable"] - figures["cash_discount"]
        - figures["brokerage_cut"] - figures["other_deductions"]
    )
    if not sale.lot_count:
        return income, None
    commission_we_pay = ZERO if figures["party_pays_broker"] else figures["commission"]
    cost = _d(sale.lot_cost) + _d(sale.loading_charge) + figures["freight_cost"] + commission_we_pay
    return income, income - cost


def period_kpis(company, start, end):
    sales = Sale.objects.for_company(company).filter(sale_date__range=(start, end))
    totals = sales.aggregate(
        total=Sum("total_amount"), taxable=Sum("taxable_amount"), gst=Sum("gst_amount"),
        bags=Sum("total_bags"), advance=Sum("advance_received"), count=Count("id"),
    )

    purchases = Purchase.objects.for_company(company).filter(purchase_date__range=(start, end))
    bought = purchases.aggregate(
        total=Sum("total_amount"), cgst=Sum("cgst_amount"), sgst=Sum("sgst_amount"),
        igst=Sum("igst_amount"), count=Count("id"),
    )

    payments = Payment.objects.for_company(company).filter(payment_date__range=(start, end))
    received_later = _d(payments.filter(related_type="sale").aggregate(s=Sum("amount"))["s"])
    paid_to_mills = _d(payments.filter(related_type="purchase").aggregate(s=Sum("amount"))["s"])
    paid_to_brokers = _d(payments.filter(related_type="broker").aggregate(s=Sum("amount"))["s"])

    profit = ZERO
    revenue_with_cost = ZERO
    without_cost = 0
    for sale in _sales_with_cost(company).filter(sale_date__range=(start, end)):
        income, value = _profit_of(sale)
        if value is None:
            without_cost += 1
            continue
        profit += value
        revenue_with_cost += income

    received = _d(totals["advance"]) + received_later
    output_gst = _d(totals["gst"])
    input_gst = _d(bought["cgst"]) + _d(bought["sgst"]) + _d(bought["igst"])

    return {
        "sales_total": _d(totals["total"]),
        "sales_taxable": _d(totals["taxable"]),
        "sales_bags": int(totals["bags"] or 0),
        "sales_count": int(totals["count"] or 0),

        "purchases_total": _d(bought["total"]),
        "purchases_count": int(bought["count"] or 0),

        "received": money(received),
        "paid_to_mills": money(paid_to_mills),
        "paid_to_brokers": money(paid_to_brokers),
        "cash_position": money(received - paid_to_mills),

        "profit": money(profit),
        "profit_margin": money(profit / revenue_with_cost * 100) if revenue_with_cost else None,
        "sales_without_cost": without_cost,

        "output_gst": money(output_gst),
        "input_gst": money(input_gst),
        "gst_payable": money(output_gst - input_gst),
    }


# --------------------------------------------------------------------------
# Receivables (one ledger per customer, reused by several sections)
# --------------------------------------------------------------------------

def receivables(company, today=None):
    """
    Every unpaid invoice with its age, the total each customer owes, and the
    ageing buckets. Customers are looped once - small businesses have tens of
    them, not thousands.
    """
    today = today or timezone.localdate()
    by_customer = {}
    invoices = []          # unpaid invoices: {sale, customer, due, age, ...}
    opening_due_total = ZERO

    for customer in Customer.objects.for_company(company).order_by("customer_name"):
        statement = customer_statement(company, customer)
        by_customer[customer.id] = {"customer": customer, "due": statement["total_due"]}
        opening_due_total += _d(statement["opening_due"])
        for row in statement["rows"]:
            if row["due"] > 0:
                invoices.append({"sale": row["sale"], "customer": customer, "due": row["due"]})

    # Trucks a broker collects for: the broker owes this money, not the party.
    broker_due = ZERO
    for broker in Broker.objects.for_company(company):
        for row in broker_collections(company, broker)["rows"]:
            if row["due"] > 0:
                broker_due += row["due"]
                invoices.append({"sale": row["sale"], "customer": row["sale"].customer,
                                 "broker": broker, "due": row["due"]})

    # Old sales typed by hand have no customer link.
    loose_due = ZERO
    for sale in Sale.objects.for_company(company).filter(customer__isnull=True):
        row = sale_payment_status(company, sale)
        if row["due"] > 0:
            loose_due += row["due"]
            invoices.append({"sale": sale, "customer": None, "due": row["due"]})

    buckets = [
        {"key": "0_15", "label": _("0-15 days"), "amount": ZERO, "count": 0},
        {"key": "16_30", "label": _("16-30 days"), "amount": ZERO, "count": 0},
        {"key": "31_60", "label": _("31-60 days"), "amount": ZERO, "count": 0},
        {"key": "60_plus", "label": _("Over 60 days"), "amount": ZERO, "count": 0},
    ]

    for invoice in invoices:
        sale = invoice["sale"]
        age = (today - sale.sale_date).days
        invoice["age"] = age
        if sale.due_date:
            invoice["days_late"] = (today - sale.due_date).days
            invoice["late"] = sale.due_date < today
            invoice["kind"] = "overdue"
        else:
            invoice["days_late"] = age - OLD_INVOICE_DAYS
            invoice["late"] = age > OLD_INVOICE_DAYS
            invoice["kind"] = "old"

        index = 0 if age <= 15 else 1 if age <= 30 else 2 if age <= 60 else 3
        buckets[index]["amount"] += invoice["due"]
        buckets[index]["count"] += 1

    # An opening balance predates the software, so it is the oldest money owed.
    if opening_due_total > 0:
        buckets[3]["amount"] += opening_due_total

    total_due = sum((entry["due"] for entry in by_customer.values()), ZERO) + loose_due + broker_due
    largest = max((b["amount"] for b in buckets), default=ZERO)
    for bucket in buckets:
        bucket["amount"] = money(bucket["amount"])
        bucket["pct"] = _pct(bucket["amount"], largest)

    return {
        "by_customer": by_customer,
        "invoices": invoices,
        "total_due": money(total_due),
        "customers_with_dues": sum(1 for entry in by_customer.values() if entry["due"] > 0) + (1 if loose_due else 0),
        "buckets": buckets,
        "opening_due": money(opening_due_total),
        "broker_due": money(broker_due),
    }


def _pct(value, largest):
    """Bar length 0-100 for a chart. Floats are fine here - it is only drawing."""
    if not largest or value <= 0:
        return 0
    return round(float(value) / float(largest) * 100, 1)


# --------------------------------------------------------------------------
# Payables
# --------------------------------------------------------------------------

def mill_dues(company):
    rows = []
    for mill in Mill.objects.for_company(company):
        due = mill_statement(company, mill)["total_due"]
        if due > 0:
            rows.append({"mill": mill, "due": money(due)})
    rows.sort(key=lambda row: row["due"], reverse=True)
    return {"rows": rows, "total": money(sum((r["due"] for r in rows), ZERO))}


def broker_dues(company):
    rows = []
    for broker in Broker.objects.for_company(company):
        owed = broker_statement(company, broker)["owed"]
        if owed > 0:
            rows.append({"broker": broker, "owed": money(owed)})
    rows.sort(key=lambda row: row["owed"], reverse=True)
    return {"rows": rows, "total": money(sum((r["owed"] for r in rows), ZERO))}


# --------------------------------------------------------------------------
# Stock
# --------------------------------------------------------------------------

def stock_overview(company, today=None):
    """
    Stock per rice and bag size, valued at landed cost, plus the low-stock and
    slow-moving lists.

    Bags left come from product_stock(), which also counts old sales made
    before lots existed. The value uses the weighted landed cost of the lots
    that still hold bags, so an old sale without lots cannot inflate it.
    """
    today = today or timezone.localdate()
    lots = stock_lots(company)

    cost_cache = {}
    lot_rows = []
    by_key = defaultdict(lambda: {"kg": ZERO, "value": ZERO})
    for lot in lots:
        lot.purchase.company = company           # avoids a query per purchase
        cost_per_kg = _d(lot_cost_per_kg(lot, cost_cache))
        kg = Decimal(lot.bags_left) * Decimal(lot.bag_weight or 0)
        value = kg * cost_per_kg
        key = (lot.product_id, int(lot.bag_weight or 0))
        by_key[key]["kg"] += kg
        by_key[key]["value"] += value
        lot_rows.append({"lot": lot, "kg": kg, "cost_per_kg": cost_per_kg, "value": value})

    window_start = today - timedelta(days=SALES_WINDOW_DAYS - 1)
    recent = defaultdict(int)
    for row in (
        SaleItem.objects.for_company(company)
        .filter(sale__sale_date__range=(window_start, today))
        .values("product", "bag_weight").annotate(bags=Sum("bag_count"))
    ):
        recent[(row["product"], row["bag_weight"])] += int(row["bags"] or 0)
    sold_recently = {product_id for (product_id, _w), bags in recent.items() if bags > 0}

    stock = product_stock(company)
    products = {p.id: p for p in Product.objects.for_company(company)}
    suggestions = {}

    rows = []
    for key, bags in stock.items():
        product = products.get(key[0])
        if product is None:
            continue
        bags_left = max(int(bags), 0)
        if not product.is_active and bags_left == 0:
            continue

        lot_kg = by_key[key]["kg"]
        avg_cost = (by_key[key]["value"] / lot_kg) if lot_kg else ZERO
        kg = Decimal(bags_left) * Decimal(key[1])
        value = kg * avg_cost

        sold_30 = recent.get(key, 0)
        per_day = Decimal(sold_30) / Decimal(SALES_WINDOW_DAYS)
        days_cover = (Decimal(bags_left) / per_day) if per_day else None

        if bags_left <= 0:
            status = "out"
        elif bags_left <= LOW_STOCK_BAGS or (days_cover is not None and days_cover < LOW_STOCK_DAYS):
            status = "low"
        else:
            status = "ok"

        if product.id not in suggestions:
            suggestions[product.id] = product_costing(company, product)["suggested_per_kg"]

        rows.append({
            "product": product,
            "bag_weight": key[1],
            "bags": bags_left,
            "kg": money(kg),
            "value": money(value),
            "avg_cost_per_kg": money(avg_cost),
            "suggested_per_kg": suggestions[product.id],
            "sold_30": sold_30,
            "per_day": per_day.quantize(Decimal("0.1")),
            "days_cover": int(days_cover) if days_cover is not None else None,
            "status": status,
        })

    rows.sort(key=lambda r: ({"out": 0, "low": 1, "ok": 2}[r["status"]], r["product"].rice_name.lower(), r["bag_weight"]))

    # Low stock worth acting on: anything low, and sold-out rice that is still selling.
    low = [
        r for r in rows
        if r["product"].is_active and (r["status"] == "low" or (r["status"] == "out" and r["sold_30"] > 0))
    ]

    slow_cutoff = today - timedelta(days=SLOW_STOCK_DAYS)
    slow = []
    for row in lot_rows:
        lot = row["lot"]
        if lot.purchase.purchase_date <= slow_cutoff and lot.product_id not in sold_recently:
            slow.append({
                "lot": lot,
                "product": lot.product,
                "mill": lot.purchase.mill,
                "bags": lot.bags_left,
                "bag_weight": lot.bag_weight,
                "age": (today - lot.purchase.purchase_date).days,
                "value": money(row["value"]),
            })
    slow.sort(key=lambda r: r["value"], reverse=True)

    return {
        "rows": rows,
        "low": low,
        "slow": slow,
        "slow_value": money(sum((r["value"] for r in slow), ZERO)),
        "total_value": money(sum((r["value"] for r in rows), ZERO)),
        "total_bags": sum(r["bags"] for r in rows),
        "total_kg": money(sum((r["kg"] for r in rows), ZERO)),
    }


# --------------------------------------------------------------------------
# Rankings
# --------------------------------------------------------------------------

def top_customers(company, start, end, due_by_customer):
    rows = (
        Sale.objects.for_company(company).filter(sale_date__range=(start, end))
        .values("customer", "customer_name")
        .annotate(total=Sum("total_amount"), bags=Sum("total_bags"), count=Count("id"))
        .order_by("-total")
    )
    merged = {}
    for row in rows:
        key = row["customer"] or ("name", row["customer_name"])
        entry = merged.setdefault(key, {
            "customer_id": row["customer"],
            "name": row["customer_name"],
            "total": ZERO, "bags": 0, "count": 0,
        })
        entry["total"] += _d(row["total"])
        entry["bags"] += int(row["bags"] or 0)
        entry["count"] += int(row["count"] or 0)

    result = sorted(merged.values(), key=lambda e: e["total"], reverse=True)[:TOP_N]
    for entry in result:
        if entry["customer_id"] in due_by_customer:
            info = due_by_customer[entry["customer_id"]]
            entry["name"] = info["customer"].customer_name
            entry["due"] = info["due"]
        else:
            entry["due"] = None
    return result


def top_products(company, start, end):
    """Bags, selling value and profit per rice in the period (profit only where lots are known)."""
    stats = {}
    items = (
        SaleItem.objects.for_company(company)
        .filter(sale__sale_date__range=(start, end))
        .select_related("product")
        .annotate(lot_cost=Sum("lots__cost_amount"), lot_count=Count("lots"))
    )
    for item in items:
        entry = stats.setdefault(item.product_id, {
            "product": item.product, "bags": 0, "kg": ZERO, "amount": ZERO,
            "profit": ZERO, "costed_amount": ZERO, "uncosted_bags": 0,
        })
        entry["bags"] += int(item.bag_count or 0)
        entry["kg"] += _d(item.total_weight)
        entry["amount"] += _d(item.amount)
        if item.lot_count:
            entry["profit"] += _d(item.amount) - _d(item.lot_cost)
            entry["costed_amount"] += _d(item.amount)
        else:
            entry["uncosted_bags"] += int(item.bag_count or 0)

    rows = list(stats.values())
    for row in rows:
        row["profit"] = money(row["profit"])
        row["margin"] = money(row["profit"] / row["costed_amount"] * 100) if row["costed_amount"] else None
    rows.sort(key=lambda r: (r["profit"], r["bags"]), reverse=True)
    return rows[:TOP_N]


# --------------------------------------------------------------------------
# Trend
# --------------------------------------------------------------------------

def trends(company, today=None):
    """Last 6 months of sales, purchases and profit, and the last 14 days of sales."""
    today = today or timezone.localdate()
    first_month = _add_months(today, -5)

    months = []
    cursor = first_month
    for _i in range(6):
        months.append({"start": cursor, "sales": ZERO, "purchases": ZERO, "profit": ZERO})
        cursor = _add_months(cursor, 1)
    month_index = {(m["start"].year, m["start"].month): m for m in months}

    day_start = today - timedelta(days=13)
    days = [{"day": day_start + timedelta(days=i), "sales": ZERO, "bags": 0} for i in range(14)]
    day_index = {d["day"]: d for d in days}

    for sale in (
        _sales_with_cost(company)
        .filter(sale_date__range=(first_month, _month_end(today)))
    ):
        month = month_index.get((sale.sale_date.year, sale.sale_date.month))
        if month:
            month["sales"] += _d(sale.total_amount)
            _income, profit = _profit_of(sale)
            if profit is not None:
                month["profit"] += profit
        day = day_index.get(sale.sale_date)
        if day:
            day["sales"] += _d(sale.total_amount)
            day["bags"] += int(sale.total_bags or 0)

    for row in (
        Purchase.objects.for_company(company)
        .filter(purchase_date__range=(first_month, _month_end(today)))
        .values("purchase_date", "total_amount")
    ):
        month = month_index.get((row["purchase_date"].year, row["purchase_date"].month))
        if month:
            month["purchases"] += _d(row["total_amount"])

    largest = max(
        [m["sales"] for m in months] + [m["purchases"] for m in months] + [m["profit"] for m in months],
        default=ZERO,
    )
    for month in months:
        for field in ("sales", "purchases", "profit"):
            month[field] = money(month[field])
            month[field + "_pct"] = _pct(month[field], largest)

    largest_day = max((d["sales"] for d in days), default=ZERO)
    for day in days:
        day["sales"] = money(day["sales"])
        day["pct"] = _pct(day["sales"], largest_day)
        day["is_today"] = day["day"] == today

    return {
        "months": months,
        "days": days,
        "has_months": any(m["sales"] or m["purchases"] for m in months),
        "has_days": any(d["sales"] for d in days),
        "fourteen_day_total": money(sum((d["sales"] for d in days), ZERO)),
    }


# --------------------------------------------------------------------------
# Actions
# --------------------------------------------------------------------------

def inr_text(amount):
    """12,34,567 - Indian grouping for text that leaves the page (WhatsApp)."""
    value = money(amount)
    rupees = int(value)
    paise = int((value - rupees) * 100)
    digits = str(abs(rupees))
    if len(digits) > 3:
        head, tail = digits[:-3], digits[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        digits = ",".join(groups + [tail])
    text = ("-" if rupees < 0 else "") + digits
    return f"{text}.{paise:02d}" if paise else text


def reminder_message(company, customer_name, invoice_no, amount, sale_date):
    """A polite payment reminder, Hindi (Roman script) then English."""
    params = {
        "name": customer_name,
        "invoice": invoice_no,
        "amount": inr_text(amount),
        "date": sale_date.strftime("%d-%m-%Y"),
        "company": company.company_name,
    }
    return _(
        "Namaste %(name)s ji, invoice %(invoice)s (%(date)s) ka ₹%(amount)s abhi baaki hai. "
        "Kripya jaldi bhugtan kar dein.\n"
        "Dear %(name)s, ₹%(amount)s is pending on invoice %(invoice)s dated %(date)s. "
        "Kindly arrange the payment at the earliest.\n"
        "Dhanyavaad / Thank you - %(company)s"
    ) % params


def action_items(company, recv, mills, brokers, stock):
    """The 'do this today' list, most urgent first."""
    late = [inv for inv in recv["invoices"] if inv["late"]]
    late.sort(key=lambda inv: (inv["days_late"], inv["due"]), reverse=True)

    collect = []
    for inv in late:
        sale = inv["sale"]
        customer = inv["customer"]
        broker = inv.get("broker")
        if broker:
            # Collected through a broker: he is the one to chase.
            name = broker.broker_name
            phone = broker.mobile
            whatsapp = broker.whatsapp_number
        else:
            name = customer.customer_name if customer else sale.customer_name
            phone = customer.mobile if customer else ""
            whatsapp = customer.whatsapp_number if customer else ""
        collect.append({
            "sale": sale,
            "customer": None if broker else customer,
            "broker": broker,
            "name": name,
            "due": inv["due"],
            "days_late": inv["days_late"],
            "age": inv["age"],
            "kind": inv["kind"],
            "phone": phone,
            "whatsapp_url": (
                "https://wa.me/%s?text=%s" % (
                    whatsapp,
                    quote(reminder_message(company, name, sale.invoice_no, inv["due"], sale.sale_date)),
                ) if whatsapp else ""
            ),
        })

    no_cost = list(
        _sales_with_cost(company).filter(lot_count=0)
        .order_by("-sale_date", "-id")
        .only("id", "invoice_no", "customer_name", "sale_date", "total_amount")
    )

    groups = {
        "collect": collect,
        "collect_total": money(sum((c["due"] for c in collect), ZERO)),
        "pay_mills": mills["rows"][:TOP_N],
        "low_stock": stock["low"],
        "slow_stock": stock["slow"],
        "pay_brokers": brokers["rows"],
        "no_cost": no_cost,
    }
    groups["count"] = (
        len(collect) + len(groups["pay_mills"]) + len(stock["low"]) + len(stock["slow"])
        + len(brokers["rows"]) + len(no_cost)
    )
    groups["limit"] = ACTION_LIMIT
    return groups


# --------------------------------------------------------------------------
# Onboarding
# --------------------------------------------------------------------------

def setup_progress(company):
    steps = {
        "mill": Mill.objects.for_company(company).exists(),
        "purchase": Purchase.objects.for_company(company).exists(),
        "customer": Customer.objects.for_company(company).exists(),
        "sale": Sale.objects.for_company(company).exists(),
    }
    steps["done"] = sum(1 for value in steps.values() if value)
    steps["complete"] = steps["done"] == 4
    steps["has_data"] = steps["purchase"] or steps["sale"]
    return steps


# --------------------------------------------------------------------------
# Everything
# --------------------------------------------------------------------------

def build_dashboard(company, period=None, today=None):
    today = today or timezone.localdate()
    setup = setup_progress(company)
    current = period_range(period, today)

    data = {
        "today": today,
        "period": current,
        "periods": period_choices(),
        "setup": setup,
    }
    if not setup["has_data"]:
        return data

    recv = receivables(company, today)
    mills = mill_dues(company)
    brokers = broker_dues(company)
    stock = stock_overview(company, today)

    data.update({
        "kpis": period_kpis(company, current["start"], current["end"]),
        "balances": {
            "customers_owe": recv["total_due"],
            "customers_with_dues": recv["customers_with_dues"],
            "you_owe_mills": mills["total"],
            "mills_with_dues": len(mills["rows"]),
            "broker_owed": brokers["total"],
            "stock_value": stock["total_value"],
            "stock_bags": stock["total_bags"],
        },
        "receivables": recv,
        "actions": action_items(company, recv, mills, brokers, stock),
        "stock": stock,
        "trends": trends(company, today),
        "top_customers": top_customers(company, current["start"], current["end"], recv["by_customer"]),
        "top_products": top_products(company, current["start"], current["end"]),
    })
    return data
