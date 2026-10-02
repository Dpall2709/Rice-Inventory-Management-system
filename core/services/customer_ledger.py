"""
Customer and broker ledgers - the selling-side twin of services/ledger.py.

Customer: money received can be recorded

    with the sale      - the advance typed on the invoice
    against a sale     - "received 50,000 for invoice SAL-...-0003"
    on account         - "received 1,00,000 from Maa Bhagwati Bhandar"

Money received on account (and anything paid beyond an invoice's total) is
applied to the opening balance first, then the oldest unpaid invoice, and so
on - the same way the mill ledger settles bills. Whatever is left over is an
advance the customer has with you.

Broker: every sale he brings earns a commission you owe him; commission paid
is a Payment of type "broker".
"""

from decimal import Decimal

from django.db.models import Q, Sum
from django.utils.translation import gettext as _

from core.models import Payment, Sale


def _money(value):
    return Decimal(value or 0)


def receivable(sale):
    """
    What the customer owes for one sale: the invoice after cash discount,
    brokerage they cut, short weight and freight adjustments (see
    sale_service.settlement). Falls back to the invoice total for rows that
    were never settled.
    """
    value = sale.net_receivable
    if value is None or (not value and sale.total_amount):
        return _money(sale.total_amount)
    return _money(value)


def collected_by_broker(sale):
    """True when the broker collects this truck's money and pays you."""
    return bool(sale.broker_id) and sale.collect_from == Sale.COLLECT_FROM_BROKER


def _customer_payments(company, customer):
    # Old receipts were linked only to a sale, newer ones also to the customer.
    # Money a broker paid you belongs to the broker's account, not here.
    return list(
        Payment.objects
        .filter(company=company, related_type="sale", broker__isnull=True)
        .filter(Q(customer=customer) | Q(sale__customer=customer))
        .select_related("sale")
        .order_by("payment_date", "id")
    )


def _settle(sales, payments, opening):
    """
    Match money received against what is owed, the way traders settle a khata:
    money against a named invoice settles that invoice; money on account (and
    anything paid beyond an invoice) clears the opening balance, then the
    oldest unpaid invoice, and so on. Whatever is left is an advance.
    """
    direct = {}
    on_account = Decimal("0")

    for sale in sales:
        if sale.advance_received:
            direct[sale.id] = direct.get(sale.id, Decimal("0")) + _money(sale.advance_received)

    for payment in payments:
        if payment.sale_id:
            direct[payment.sale_id] = direct.get(payment.sale_id, Decimal("0")) + _money(payment.amount)
        else:
            on_account += _money(payment.amount)

    overpaid = Decimal("0")
    for sale in sales:
        received = direct.get(sale.id, Decimal("0"))
        total = receivable(sale)
        if received > total:
            overpaid += received - total
            direct[sale.id] = total

    unapplied = on_account + overpaid
    opening_paid = min(unapplied, opening) if opening > 0 else Decimal("0")
    unapplied -= opening_paid

    rows = []
    for sale in sales:
        total = receivable(sale)
        direct_paid = direct.get(sale.id, Decimal("0"))
        outstanding = max(total - direct_paid, Decimal("0"))

        applied = min(unapplied, outstanding)
        unapplied -= applied

        paid = direct_paid + applied
        due = max(total - paid, Decimal("0"))

        rows.append({
            "sale": sale,
            "total": total,
            "direct_paid": direct_paid,
            "applied_from_account": applied,
            "paid": paid,
            "due": due,
            "status": "paid" if due <= 0 else ("partial" if paid > 0 else "due"),
            "overdue": bool(due > 0 and sale.due_date and sale.due_date < _today()),
            "collected_by_broker": collected_by_broker(sale),
        })

    received_total = (
        sum((_money(s.advance_received) for s in sales), Decimal("0"))
        + sum((_money(p.amount) for p in payments), Decimal("0"))
    )

    return {
        "rows": rows,
        "payments": payments,
        "opening": opening,
        "opening_paid": opening_paid,
        "opening_due": opening - opening_paid,
        "total_sold": sum((row["total"] for row in rows), Decimal("0")),
        "total_received": received_total,
        "total_due": (opening - opening_paid) + sum((row["due"] for row in rows), Decimal("0")),
        "on_account": on_account,
        "advance": unapplied,
        "history": _history(opening, sales, payments),
    }


def customer_statement(company, customer):
    """
    The full picture for one buyer: every invoice they pay you for directly,
    with what is paid and due, the opening balance, any advance, and the
    running-balance history. Trucks a broker collects for are listed
    separately - their money is owed by the broker.
    """
    all_sales = list(
        Sale.objects
        .for_company(company)
        .filter(customer=customer)
        .select_related("broker")
        .prefetch_related("items__product")
        .order_by("sale_date", "id")
    )
    sales = [sale for sale in all_sales if not collected_by_broker(sale)]
    statement = _settle(sales, _customer_payments(company, customer), _money(customer.opening_balance))
    statement["customer"] = customer
    statement["broker_sales"] = [sale for sale in all_sales if collected_by_broker(sale)]
    return statement


def broker_collections(company, broker):
    """
    Trucks this broker sold and collects for: what he owes you after CD and
    his brokerage, what he has paid, and what is still due from him.
    """
    sales = list(
        Sale.objects
        .for_company(company)
        .filter(broker=broker, collect_from=Sale.COLLECT_FROM_BROKER)
        .select_related("customer")
        .prefetch_related("items__product")
        .order_by("sale_date", "id")
    )
    payments = list(
        Payment.objects
        .filter(company=company, related_type="sale", broker=broker)
        .select_related("sale")
        .order_by("payment_date", "id")
    )
    statement = _settle(sales, payments, Decimal("0"))
    statement["broker"] = broker
    return statement


def _today():
    from django.utils import timezone

    return timezone.localdate()


def _history(opening, sales, payments):
    """The khata: invoices and receipts in date order with a running balance."""
    entries = []

    for sale in sales:
        items = list(sale.items.all())
        bags = sum(int(item.bag_count or 0) for item in items) or sale.total_bags
        rice = ", ".join(sorted({item.product.rice_name for item in items})) or _("goods")

        entries.append({
            "date": sale.sale_date,
            "order": (sale.sale_date, 0, sale.id),
            "kind": "invoice",
            "particulars": _("Invoice %(no)s - %(bags)s bags %(rice)s") % {
                "no": sale.invoice_no, "bags": bags, "rice": rice,
            } + (f" · {sale.customer_name}" if collected_by_broker(sale) else ""),
            "sale": sale,
            "debit": receivable(sale),
            "credit": Decimal("0"),
        })

        if sale.advance_received:
            entries.append({
                "date": sale.sale_date,
                "order": (sale.sale_date, 1, sale.id),
                "kind": "receipt",
                "particulars": _("Received with invoice %(no)s (%(mode)s)") % {
                    "no": sale.invoice_no, "mode": sale.advance_mode or _("cash"),
                },
                "sale": sale,
                "debit": Decimal("0"),
                "credit": _money(sale.advance_received),
            })

    for payment in payments:
        if payment.sale_id:
            against = _("invoice %(no)s") % {"no": payment.sale.invoice_no}
        else:
            against = _("on account")
        entries.append({
            "date": payment.payment_date,
            "order": (payment.payment_date, 2, payment.id),
            "kind": "receipt",
            "particulars": _("Received (%(mode)s) - %(against)s") % {
                "mode": payment.payment_mode or _("cash"), "against": against,
            },
            "sale": payment.sale if payment.sale_id else None,
            "payment": payment,
            "debit": Decimal("0"),
            "credit": _money(payment.amount),
        })

    entries.sort(key=lambda entry: entry["order"])

    balance = _money(opening)
    history = [{
        "date": None,
        "kind": "opening",
        "particulars": _("Opening balance"),
        "sale": None,
        "debit": balance if balance > 0 else Decimal("0"),
        "credit": Decimal("0"),
        "balance": balance,
    }]

    for entry in entries:
        balance = balance + entry["debit"] - entry["credit"]
        entry["balance"] = balance
        history.append(entry)

    return history


def sale_payment_status(company, sale):
    """Paid / due for one invoice, from whichever account it belongs to."""
    if collected_by_broker(sale):
        rows = broker_collections(company, sale.broker)["rows"]
    elif sale.customer_id:
        rows = customer_statement(company, sale.customer)["rows"]
    else:
        rows = []
    for row in rows:
        if row["sale"].id == sale.id:
            return row

    # A sale without a customer link: advance + payments against it.
    received = _money(sale.advance_received) + _money(
        Payment.objects.filter(company=company, related_type="sale", sale=sale)
        .aggregate(s=Sum("amount"))["s"]
    )
    total = receivable(sale)
    paid = min(received, total)
    due = total - paid
    return {
        "sale": sale,
        "total": total,
        "direct_paid": paid,
        "applied_from_account": Decimal("0"),
        "paid": paid,
        "due": due,
        "status": "paid" if due <= 0 else ("partial" if paid > 0 else "due"),
        "overdue": bool(due > 0 and sale.due_date and sale.due_date < _today()),
        "collected_by_broker": collected_by_broker(sale),
    }


def status_map_for_sales(company, sales):
    """Paid/due for many invoices at once - one ledger per customer or broker, not per row."""
    result = {}
    customers = {}
    brokers = {}
    loose = []

    for sale in sales:
        if collected_by_broker(sale):
            brokers[sale.broker_id] = sale.broker
        elif sale.customer_id:
            customers[sale.customer_id] = sale.customer
        else:
            loose.append(sale)

    for customer in customers.values():
        for row in customer_statement(company, customer)["rows"]:
            result[row["sale"].id] = row
    for broker in brokers.values():
        for row in broker_collections(company, broker)["rows"]:
            result[row["sale"].id] = row
    for sale in loose:
        result[sale.id] = sale_payment_status(company, sale)

    return result


def customer_balances(company, customers):
    """Total due per customer id, for the customer list."""
    return {
        customer.id: customer_statement(company, customer)["total_due"]
        for customer in customers
    }


# --------------------------------------------------------------------------
# Broker
# --------------------------------------------------------------------------

def broker_statement(company, broker):
    """Commission earned on each sale, commission paid, and what is still owed."""
    sales = list(
        Sale.objects
        .for_company(company)
        .filter(broker=broker)
        .select_related("customer")
        .order_by("sale_date", "id")
    )
    payments = list(
        Payment.objects
        .filter(company=company, related_type="broker", broker=broker)
        .order_by("payment_date", "id")
    )

    # When the brokerage is cut from the payment (the broker collects and keeps
    # it, or the party pays him directly) you owe him nothing for that truck.
    owed_sales = [
        s for s in sales
        if s.broker_paid_by != Sale.BROKER_PAID_BY_CUSTOMER and not collected_by_broker(s)
    ]
    paid_by_party = sum((_money(s.broker_commission) for s in sales if s not in owed_sales), Decimal("0"))
    earned = sum((_money(s.broker_commission) for s in owed_sales), Decimal("0"))
    paid = sum((_money(p.amount) for p in payments), Decimal("0"))
    opening = _money(broker.opening_balance)

    entries = []
    for sale in sales:
        if not sale.broker_commission or sale not in owed_sales:
            continue
        entries.append({
            "date": sale.sale_date,
            "order": (sale.sale_date, 0, sale.id),
            "kind": "commission",
            "particulars": _("Commission on %(no)s - %(customer)s, %(bags)s bags") % {
                "no": sale.invoice_no, "customer": sale.customer_name, "bags": sale.total_bags,
            },
            "sale": sale,
            "credit": _money(sale.broker_commission),   # you owe him more
            "debit": Decimal("0"),
        })
    for payment in payments:
        entries.append({
            "date": payment.payment_date,
            "order": (payment.payment_date, 1, payment.id),
            "kind": "payment",
            "particulars": _("Commission paid (%(mode)s)") % {"mode": payment.payment_mode or _("cash")},
            "sale": None,
            "payment": payment,
            "credit": Decimal("0"),
            "debit": _money(payment.amount),
        })
    entries.sort(key=lambda entry: entry["order"])

    balance = opening
    history = [{
        "date": None, "kind": "opening", "particulars": _("Opening balance"), "sale": None,
        "credit": opening if opening > 0 else Decimal("0"), "debit": Decimal("0"), "balance": balance,
    }]
    for entry in entries:
        balance = balance + entry["credit"] - entry["debit"]
        entry["balance"] = balance
        history.append(entry)

    owed = opening + earned - paid
    collections = broker_collections(company, broker)
    commission_owed = owed if owed > 0 else Decimal("0")

    return {
        "collections": collections,
        # Money the broker still has to pay you, net of commission you owe him.
        "broker_owes_us": collections["total_due"],
        "net_position": collections["total_due"] - commission_owed,
        "brokerage_kept": sum((_money(s.broker_commission) for s in sales if collected_by_broker(s)), Decimal("0")),
        "broker": broker,
        "sales": list(reversed(sales)),
        "payments": payments,
        "opening": opening,
        "total_sales_value": sum((_money(s.total_amount) for s in sales), Decimal("0")),
        "total_bags": sum((int(s.total_bags or 0) for s in sales)),
        "earned": earned,
        "paid_by_parties": paid_by_party,
        "paid": paid,
        "owed": owed if owed > 0 else Decimal("0"),
        "advance": -owed if owed < 0 else Decimal("0"),
        "history": history,
    }
