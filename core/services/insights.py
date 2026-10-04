"""
What the owner should know and do - in plain sentences, worked out from the
business's own trucks, parties and stock.

    pulse(...)          four traffic lights: margin, collection speed,
                        overdue money, stock age
    reminders(...)      who owes too much or for too long, trucks not
                        unloaded, mills waiting for money - each with the
                        button that does the job
    profit_tips(...)    where the money is made and lost: brokers, customers,
                        products and mills compared per kg; shortage, CD,
                        brokerage and freight as a share of sales; loss trucks

Everything is per company and works for any product - nothing assumes rice.
"""

from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from django.db.models import Avg, Max
from django.urls import reverse
from django.utils.translation import gettext as _

from core.models import Payment, PurchaseItem, Sale
from core.services.sale_service import money
from core.services.trade_register import AWAITING, ON_THE_WAY, PARTIAL, SETTLED, register_rows

ZERO = Decimal("0")

# Thresholds a small trader would recognise. Kept here so they are easy to tune.
UNLOAD_LATE_DAYS = 5          # truck sent, unloading not recorded
PAYMENT_LATE_DAYS = 15        # unloaded, still not paid
BIG_BALANCE_SHARE = Decimal("0.35")   # one party holds this share of all money owed to you
MIN_TRUCKS_TO_COMPARE = 2     # need at least this many trucks before judging a broker/customer


def _rows(company, start, end):
    sales = Sale.objects.for_company(company).filter(sale_date__range=(start, end))
    return register_rows(company, sales)


def _per_kg(profit, kg):
    return money(profit / kg) if kg else ZERO


def _short_inr(amount):
    """Rs. 19.1 lakh / 45,000 - the way traders say amounts."""
    amount = Decimal(amount or 0)
    sign = "-" if amount < 0 else ""
    amount = abs(amount)
    if amount >= Decimal("10000000"):
        return f"{sign}₹{amount / Decimal('10000000'):.2f} " + _("crore")
    if amount >= Decimal("100000"):
        return f"{sign}₹{amount / Decimal('100000'):.2f} " + _("lakh")
    return f"{sign}₹{amount:,.0f}"


# --------------------------------------------------------------------------
# Pulse
# --------------------------------------------------------------------------

def pulse(company, start, end, today):
    """Four indicators, each green / amber / red with one line of meaning."""
    length = (end - start).days + 1
    current = [r for r in _rows(company, start, end) if r["profit"] is not None]
    previous = [
        r for r in _rows(company, start - timedelta(days=length), start - timedelta(days=1))
        if r["profit"] is not None
    ]

    def margin(rows):
        income = sum((r["net_receivable"] for r in rows), ZERO)
        profit = sum((r["profit"] for r in rows), ZERO)
        return (profit / income * 100) if income else None

    now, before = margin(current), margin(previous)
    if now is None:
        margin_light = {"tone": "muted", "value": "—", "text": _("No costed trucks in this period yet.")}
    else:
        tone = "good" if now >= 3 else ("warn" if now >= 1 else "bad")
        if before is None:
            text = _("Profit as a share of what parties pay you.")
        elif now >= before:
            text = _("Up from %(before)s%% in the period before.") % {"before": f"{before:.1f}"}
        else:
            text = _("Down from %(before)s%% in the period before.") % {"before": f"{before:.1f}"}
            tone = "warn" if tone == "good" else tone
        margin_light = {"tone": tone, "value": f"{now:.1f}%", "text": text}

    # Days from unloading to the last payment, on trucks fully paid in the last 90 days.
    window = _rows(company, today - timedelta(days=120), today)
    waits = [
        (r["last_payment"] - r["unload_date"]).days
        for r in window
        if r["status"] == SETTLED and r["unload_date"] and r["last_payment"]
        and r["last_payment"] >= r["unload_date"]
    ]
    if waits:
        days = sum(waits) / len(waits)
        tone = "good" if days <= 10 else ("warn" if days <= 20 else "bad")
        collect_light = {"tone": tone, "value": _("%(days)s days") % {"days": round(days)},
                         "text": _("Average wait from unloading to full payment.")}
    else:
        collect_light = {"tone": "muted", "value": "—", "text": _("Shown once a few trucks are fully paid.")}

    open_rows = [r for r in window if r["due"] > 0]
    owed = sum((r["due"] for r in open_rows), ZERO)
    late = sum(
        (r["due"] for r in open_rows
         if r["unload_date"] and (today - r["unload_date"]).days > PAYMENT_LATE_DAYS),
        ZERO,
    )
    if owed:
        share = late / owed * 100
        tone = "good" if share < 20 else ("warn" if share < 50 else "bad")
        overdue_light = {"tone": tone, "value": f"{share:.0f}%",
                         "text": _("%(late)s of %(owed)s owed to you is over %(days)s days old.") % {
                             "late": _short_inr(late), "owed": _short_inr(owed), "days": PAYMENT_LATE_DAYS}}
    else:
        overdue_light = {"tone": "good", "value": "0%", "text": _("Nobody owes you money right now.")}

    from core.services.sale_service import stock_lots

    lots = stock_lots(company)
    bags = sum(lot.bags_left for lot in lots)
    if bags:
        age = sum((today - lot.purchase.purchase_date).days * lot.bags_left for lot in lots) / bags
        tone = "good" if age <= 20 else ("warn" if age <= 45 else "bad")
        stock_light = {"tone": tone, "value": _("%(days)s days") % {"days": round(age)},
                       "text": _("Average age of the stock in your godown.")}
    else:
        stock_light = {"tone": "muted", "value": "—", "text": _("No stock in the godown.")}

    return [
        {"key": "margin", "label": _("Profit margin"), **margin_light},
        {"key": "collect", "label": _("Getting paid"), **collect_light},
        {"key": "overdue", "label": _("Money stuck with parties"), **overdue_light},
        {"key": "stock", "label": _("Stock age"), **stock_light},
    ]


# --------------------------------------------------------------------------
# Reminders
# --------------------------------------------------------------------------

def account_reminder(company, name, amount, since, trucks):
    """A polite account-level reminder, Hindi (Roman script) then English."""
    params = {
        "name": name,
        "amount": f"{Decimal(amount):,.2f}",
        "since": since.strftime("%d-%m-%Y"),
        "trucks": trucks,
        "company": company.company_name,
    }
    return _(
        "Namaste %(name)s ji, aapke khaate mein %(trucks)s gaadi ka ₹%(amount)s baaki hai "
        "(sabse purana %(since)s se). Kripya jaldi bhugtan kar dein.\n"
        "Dear %(name)s, ₹%(amount)s is pending on your account for %(trucks)s truck(s), "
        "the oldest since %(since)s. Kindly arrange the payment at the earliest.\n"
        "Dhanyavaad / Thank you - %(company)s"
    ) % params


def reminders(company, today, recv, mills):
    """
    The 'remind me' list, most urgent first. Each item: id (for snoozing in
    the browser), tone, icon, title, detail and buttons.
    """
    items = []
    window = _rows(company, today - timedelta(days=365), today)

    # 1. Trucks sent but never unloaded.
    for r in window:
        if r["status"] == ON_THE_WAY and (today - r["sale"].sale_date).days > UNLOAD_LATE_DAYS:
            sale = r["sale"]
            items.append({
                "id": f"unload-{sale.id}", "tone": "warn", "icon": "🚚", "rank": 2,
                "title": _("Truck %(truck)s to %(party)s: unloading not recorded") % {
                    "truck": sale.vehicle_number or sale.invoice_no, "party": sale.customer_name},
                "detail": _("Sent %(days)s days ago. Enter the weight they received so the bill is final.") % {
                    "days": (today - sale.sale_date).days},
                "buttons": [{"label": _("Record unloading"), "url": reverse("settle_sale", args=[sale.id]), "primary": True}],
            })

    # 2. Parties holding a lot of your money, or for a long time.
    owed_by = defaultdict(lambda: {"due": ZERO, "oldest": None, "party": None, "kind": None, "trucks": 0})
    total_owed = ZERO
    for r in window:
        if r["due"] <= 0:
            continue
        sale = r["sale"]
        if sale.broker_id and sale.collect_from == Sale.COLLECT_FROM_BROKER:
            key, party, kind = ("broker", sale.broker_id), sale.broker, "broker"
        elif sale.customer_id:
            key, party, kind = ("customer", sale.customer_id), sale.customer, "customer"
        else:
            continue
        entry = owed_by[key]
        entry.update(party=party, kind=kind)
        entry["due"] += r["due"]
        entry["trucks"] += 1
        since = sale.unload_date or sale.sale_date
        entry["oldest"] = since if entry["oldest"] is None or since < entry["oldest"] else entry["oldest"]
        total_owed += r["due"]

    # "Share of all money owed" only means something when several parties owe.
    several = len(owed_by) >= 2
    for entry in owed_by.values():
        days = (today - entry["oldest"]).days
        share = (entry["due"] / total_owed) if (total_owed and several) else ZERO
        if days <= PAYMENT_LATE_DAYS and share < BIG_BALANCE_SHARE:
            continue
        party = entry["party"]
        is_broker = entry["kind"] == "broker"
        name = party.broker_name if is_broker else party.customer_name
        phone = party.mobile
        reasons = []
        if days > PAYMENT_LATE_DAYS:
            reasons.append(_("oldest unpaid truck is %(days)s days old") % {"days": days})
        if share >= BIG_BALANCE_SHARE:
            reasons.append(_("%(pct)s%% of all money owed to you") % {"pct": f"{share * 100:.0f}"})
        buttons = [{
            "label": _("Receive payment"),
            "url": reverse("add_broker_receipt", args=[party.id]) if is_broker
            else reverse("add_customer_payment", args=[party.id]),
            "primary": True,
        }]
        if phone:
            from urllib.parse import quote

            buttons.append({"label": _("Call"), "url": f"tel:{phone}"})
            message = account_reminder(company, name, entry["due"], entry["oldest"], entry["trucks"])
            buttons.append({"label": "WhatsApp", "url": f"https://wa.me/{party.whatsapp_number}?text={quote(message)}", "external": True})
        buttons.append({
            "label": _("Open account"),
            "url": reverse("broker_report_detail", args=[party.id]) if is_broker
            else reverse("customer_ledger", args=[party.id]),
        })
        items.append({
            "id": f"owes-{entry['kind']}-{party.id}", "rank": 1 if days > 30 or share >= Decimal("0.5") else 2,
            "tone": "bad" if days > 30 else "warn", "icon": "🤝" if is_broker else "👤",
            "title": _("%(name)s owes you %(amount)s") % {"name": name, "amount": _short_inr(entry["due"])},
            "detail": " · ".join(reasons).capitalize() + ".",
            "buttons": buttons,
        })

    # 3. Mills waiting for money - largest first.
    for row in mills["rows"][:3]:
        mill = row["mill"]
        last = (
            Payment.objects.for_company(company)
            .filter(related_type="purchase", mill=mill).aggregate(last=Max("payment_date"))["last"]
        )
        days = (today - last).days if last else None
        if days is None:
            detail = _("No payment recorded yet.")
        elif days == 0:
            detail = _("Last payment today.")
        else:
            detail = _("Last payment %(days)s days ago.") % {"days": days}
        items.append({
            "id": f"mill-{mill.id}", "rank": 3, "tone": "info", "icon": "🏭",
            "title": _("You owe %(mill)s %(amount)s") % {"mill": mill.mill_name, "amount": _short_inr(row["due"])},
            "detail": detail,
            "buttons": [
                {"label": _("Pay"), "url": reverse("add_mill_payment", args=[mill.id]), "primary": True},
                {"label": _("Open account"), "url": reverse("mill_report_detail", args=[mill.id])},
            ],
        })

    items.sort(key=lambda item: (item["rank"], {"bad": 0, "warn": 1, "info": 2}.get(item["tone"], 3)))
    return items


# --------------------------------------------------------------------------
# Profit tips
# --------------------------------------------------------------------------

def _compare(rows, key_fn, name_fn):
    """Profit per kg grouped by key, for groups with enough trucks."""
    groups = defaultdict(lambda: {"kg": ZERO, "profit": ZERO, "trucks": 0, "name": ""})
    for r in rows:
        key = key_fn(r)
        if key is None:
            continue
        group = groups[key]
        group["kg"] += r["weight_kg"] or 0
        group["profit"] += r["profit"]
        group["trucks"] += 1
        group["name"] = name_fn(r)
    result = []
    for key, group in groups.items():
        if group["trucks"] >= MIN_TRUCKS_TO_COMPARE and group["kg"]:
            result.append({**group, "key": key, "per_kg": _per_kg(group["profit"], group["kg"])})
    result.sort(key=lambda g: g["per_kg"], reverse=True)
    return result


def profit_tips(company, start, end, today):
    rows = [r for r in _rows(company, start, end) if r["profit"] is not None]
    tips = []
    if not rows:
        return tips

    sales_value = sum((r["party_value"] for r in rows), ZERO) or Decimal("1")

    # Loss trucks.
    losses = [r for r in rows if r["profit"] < 0]
    if losses:
        lost = -sum((r["profit"] for r in losses), ZERO)
        tips.append({
            "tone": "bad", "icon": "🔻",
            "title": _("%(n)s truck(s) made a loss of %(amount)s") % {"n": len(losses), "amount": _short_inr(lost)},
            "detail": _("Check the selling rate, shortage and freight on these trucks before the next deal with the same party."),
            "link": reverse("trade_register") + f"?from={start}&to={end}",
            "link_label": _("See the trucks"),
        })

    # Brokers compared.
    brokers = _compare(rows, lambda r: r["sale"].broker_id, lambda r: r["sale"].broker.broker_name if r["sale"].broker else "")
    if len(brokers) >= 2 and brokers[0]["per_kg"] > brokers[-1]["per_kg"]:
        best, worst = brokers[0], brokers[-1]
        tips.append({
            "tone": "good", "icon": "🤝",
            "title": _("Trucks through %(best)s earn ₹%(b)s/kg, through %(worst)s only ₹%(w)s/kg") % {
                "best": best["name"], "b": best["per_kg"], "worst": worst["name"], "w": worst["per_kg"]},
            "detail": _("Give more trucks to the better broker, or ask the other for a lower brokerage or CD."),
            "link": reverse("broker_report_detail", args=[worst["key"]]),
            "link_label": _("Open %(name)s") % {"name": worst["name"]},
        })

    # Customers compared.
    customers = _compare(rows, lambda r: r["sale"].customer_id, lambda r: r["sale"].customer_name)
    if len(customers) >= 2 and customers[0]["per_kg"] > customers[-1]["per_kg"]:
        best, worst = customers[0], customers[-1]
        tips.append({
            "tone": "info", "icon": "👥",
            "title": _("%(best)s gives you ₹%(b)s/kg, %(worst)s only ₹%(w)s/kg") % {
                "best": best["name"], "b": best["per_kg"], "worst": worst["name"], "w": worst["per_kg"]},
            "detail": _("Quote %(worst)s a little higher, or offer the stock to your better-paying parties first.") % {
                "worst": worst["name"]},
            "link": reverse("customer_ledger", args=[worst["key"]]),
            "link_label": _("Open %(name)s") % {"name": worst["name"]},
        })

    # Shortage in transit.
    shortage_kg = sum((r["loss_kg"] or 0 for r in rows if r["loss_kg"] and r["loss_kg"] > 0), ZERO)
    if shortage_kg > 0:
        kg_sent = sum((r["weight_kg"] for r in rows if r["loss_kg"] is not None), ZERO) or Decimal("1")
        rate = sum((r["sale_rate"] for r in rows), ZERO) / len(rows)
        cost = money(shortage_kg * rate)
        pct = shortage_kg / kg_sent * 100
        tips.append({
            "tone": "warn" if pct > Decimal("0.3") else "info", "icon": "⚖️",
            "title": _("Shortage in transit cost you about %(amount)s (%(kg)s kg, %(pct)s%%)") % {
                "amount": _short_inr(cost), "kg": f"{shortage_kg:,.0f}", "pct": f"{pct:.2f}"},
            "detail": _("Weigh trucks at loading and compare transporters - a few kg per truck adds up over a season."),
        })

    # CD + brokerage.
    cd = sum((r["cash_discount"] for r in rows), ZERO)
    brokerage = sum((r["commission"] for r in rows if r["sale"].broker_id), ZERO)
    if cd + brokerage > 0:
        share = (cd + brokerage) / sales_value * 100
        tips.append({
            "tone": "info", "icon": "💸",
            "title": _("CD and brokerage took %(amount)s - %(pct)s%% of your sales") % {
                "amount": _short_inr(cd + brokerage), "pct": f"{share:.2f}"},
            "detail": _("Direct sales (no broker, no CD) keep this money - worth it for parties who pay on time."),
        })

    # Freight per kg.
    freight = sum((r["freight_cost"] or 0 for r in rows), ZERO)
    kg = sum((r["weight_kg"] for r in rows), ZERO)
    if freight and kg:
        tips.append({
            "tone": "info", "icon": "🚛",
            "title": _("Freight cost you ₹%(per_kg)s per kg (%(amount)s in all)") % {
                "per_kg": f"{freight / kg:.2f}", "amount": _short_inr(freight)},
            "detail": _("Compare it with your margin per kg - on far routes, quote the freight into your selling rate."),
        })

    # Cheapest mill for the same product, last 90 days.
    since = today - timedelta(days=90)
    prices = (
        PurchaseItem.objects.for_company(company)
        .filter(purchase__purchase_date__gte=since)
        .values("product__rice_name", "bag_weight", "purchase__mill__mill_name")
        .annotate(rate=Avg("purchase_price"))
    )
    by_product = defaultdict(list)
    for p in prices:
        by_product[(p["product__rice_name"], p["bag_weight"])].append(p)
    best_gap = None
    for (product, weight), mills in by_product.items():
        if len(mills) < 2:
            continue
        mills.sort(key=lambda m: m["rate"])
        gap = Decimal(mills[-1]["rate"]) - Decimal(mills[0]["rate"])
        if gap > 0 and (best_gap is None or gap > best_gap[0]):
            best_gap = (gap, product, weight, mills[0], mills[-1])
    if best_gap:
        gap, product, weight, cheap, dear = best_gap
        tips.append({
            "tone": "good", "icon": "🏭",
            "title": _("%(product)s is ₹%(gap)s/kg cheaper from %(cheap)s than from %(dear)s") % {
                "product": product, "gap": f"{gap:.2f}", "cheap": cheap["purchase__mill__mill_name"],
                "dear": dear["purchase__mill__mill_name"]},
            "detail": _("Average buying rate over the last 90 days. Buying from the cheaper mill adds this straight to your margin."),
        })

    # Best product.
    products = _compare(
        rows,
        lambda r: r["sale"].items.first().product_id if r["sale"].items.exists() else None,
        lambda r: r["sale"].items.first().product.rice_name,
    )
    if len(products) >= 2:
        best = products[0]
        tips.append({
            "tone": "good", "icon": "📦",
            "title": _("%(product)s earns you the most: ₹%(per_kg)s per kg") % {
                "product": best["name"], "per_kg": best["per_kg"]},
            "detail": _("Keep it in stock - check the low-stock list below."),
        })

    order = {"bad": 0, "warn": 1, "good": 2, "info": 3}
    tips.sort(key=lambda tip: order.get(tip["tone"], 4))
    return tips
