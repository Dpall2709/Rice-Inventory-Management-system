"""
Supplier ledger: matching money paid against the bills it settles.

A payment can be recorded in two ways:

    against one bill   - "I paid 1,00,000 for bill 01"
    against the mill   - "I paid 1,00,000 to Raju Rice Mill"

The second kind used to vanish from the invoice table: the bill still showed
its full due even though the money had been paid. That made the invoice rows
disagree with the mill's balance.

Here, money paid to the mill in general is applied to the oldest debt first -
the opening balance, then the oldest unpaid bill, and so on, which is how a
trader and a mill actually settle accounts. Anything left over is shown as an
advance instead of disappearing.
"""

from decimal import Decimal

from django.db.models import Sum

from core.models import Payment, Purchase


def _money(value):
    return Decimal(value or 0)


def mill_statement(company, mill):
    """
    The full picture for one supplier.

    Returns a dictionary with:
        rows            one entry per bill, with what it was paid and what is due
        opening_*       the opening balance and how much of it is settled
        totals          purchased, paid, due
        advance         money paid beyond every bill
        on_account      payments that were made to the mill, not to a bill
    """
    purchases = list(
        Purchase.objects
        .for_company(company)
        .filter(mill=mill)
        .prefetch_related("purchaseitem_set__product")
        .order_by("purchase_date", "id")
    )

    payments = list(
        Payment.objects
        .filter(company=company, related_type="purchase", mill=mill)
        .order_by("payment_date", "id")
    )

    # Money already tied to a particular bill.
    direct = {}
    on_account = Decimal("0")

    for payment in payments:
        if payment.purchase_id:
            direct[payment.purchase_id] = direct.get(payment.purchase_id, Decimal("0")) + _money(payment.amount)
        else:
            on_account += _money(payment.amount)

    # A payment larger than the bill it names settles that bill, and the rest
    # works like money paid to the mill in general. Before this, the extra
    # simply vanished: paying 10,00,000 against a 1,51,200 bill left the other
    # bills showing their full due.
    totals_by_bill = {p.id: _money(p.total_amount) for p in purchases}
    bills_by_id = {p.id: p for p in purchases}
    overpaid = Decimal("0")
    overpaid_by_bill = []          # [(purchase, extra amount)] - for explaining it
    direct_paid_raw = dict(direct)  # what was actually entered against each bill
    for purchase_id, amount in list(direct.items()):
        bill_total = totals_by_bill.get(purchase_id, Decimal("0"))
        if amount > bill_total:
            overpaid += amount - bill_total
            overpaid_by_bill.append((bills_by_id.get(purchase_id), amount - bill_total))
            direct[purchase_id] = bill_total

    unapplied = on_account + overpaid

    # The opening balance is the oldest debt, so it is settled first.
    opening = _money(mill.opening_balance)
    opening_paid = min(unapplied, opening)
    unapplied -= opening_paid

    rows = []
    total_purchased = Decimal("0")
    total_paid = Decimal("0")

    for purchase in purchases:
        total = _money(purchase.total_amount)
        direct_paid = direct.get(purchase.id, Decimal("0"))

        outstanding = total - direct_paid
        if outstanding < 0:
            outstanding = Decimal("0")

        applied = min(unapplied, outstanding)
        unapplied -= applied

        paid = direct_paid + applied
        due = total - paid
        if due < 0:
            due = Decimal("0")

        if due <= 0:
            status = "paid"
        elif paid > 0:
            status = "partial"
        else:
            status = "due"

        rows.append({
            "purchase": purchase,
            "total": total,
            "entered_against_bill": direct_paid_raw.get(purchase.id, Decimal("0")),
            "direct_paid": direct_paid,
            "applied_from_account": applied,
            "paid": paid,
            "due": due,
            "status": status,
        })

        total_purchased += total
        total_paid += paid

    return {
        "mill": mill,
        "rows": rows,
        "payments": payments,

        "opening": opening,
        "opening_paid": opening_paid,
        "opening_due": opening - opening_paid,

        "total_purchased": total_purchased,
        "total_paid_on_bills": total_paid,
        "total_paid": sum((_money(p.amount) for p in payments), Decimal("0")),
        "total_due": (opening - opening_paid) + sum(row["due"] for row in rows),

        "on_account": on_account,
        "overpaid_on_bills": overpaid,  # paid against a bill beyond its total
        "overpaid_by_bill": overpaid_by_bill,
        "advance": unapplied,           # paid more than everything owed
        "history": account_history(mill, purchases, payments),
    }


def paid_map_for_purchases(company, purchases):
    """
    How much is really paid against each of these bills, including money that
    was paid to the mill in general.

    Used by the purchase list, so its "due" column agrees with the ledger.
    """
    result = {}

    mills = {p.mill_id for p in purchases}
    if not mills:
        return result

    from core.models import Mill

    for mill in Mill.objects.filter(id__in=mills):
        statement = mill_statement(company, mill)
        for row in statement["rows"]:
            result[row["purchase"].id] = {
                "paid": row["paid"],
                "due": row["due"],
                "status": row["status"],
                "applied_from_account": row["applied_from_account"],
            }

    return result


def purchase_payment_status(company, purchase):
    """The paid/due figures for one bill, counting on-account money."""
    statement = mill_statement(company, purchase.mill)

    for row in statement["rows"]:
        if row["purchase"].id == purchase.id:
            return row

    total = _money(purchase.total_amount)
    return {
        "purchase": purchase,
        "total": total,
        "direct_paid": Decimal("0"),
        "applied_from_account": Decimal("0"),
        "paid": Decimal("0"),
        "due": total,
        "status": "due",
    }


def account_history(mill, purchases, payments):
    """
    The supplier's account in date order, with a running balance - the way a
    khata / ledger book reads.

        Date  | Particulars              | Bill (you owe) | Paid   | Balance
        01 Sep  Opening balance                               ...
        05 Sep  Bill 01 - 300 bags          4,41,000                4,41,000
        09 Sep  Payment (UPI) - bill 01                1,00,000     3,41,000

    Every bill and every payment stays here for good, including those of a
    supplier who has been fully settled - that history is the proof of what
    was bought and paid.
    """
    entries = []

    for purchase in purchases:
        items = list(purchase.purchaseitem_set.all())
        bags = sum(item.bag_count or 0 for item in items)
        rice = ", ".join(sorted({item.product.rice_name for item in items})) or "rice"

        entries.append({
            "date": purchase.purchase_date,
            "order": (purchase.purchase_date, 0, purchase.id),
            "kind": "bill",
            "particulars": f"Bill {purchase.invoice_no} - {bags} bags {rice}",
            "reference": purchase.purchase_ref,
            "purchase": purchase,
            "debit": _money(purchase.total_amount),
            "credit": Decimal("0"),
        })

    for payment in payments:
        against = f"bill {payment.purchase.invoice_no}" if payment.purchase_id else "on account"
        entries.append({
            "date": payment.payment_date,
            "order": (payment.payment_date, 1, payment.id),
            "kind": "payment",
            "particulars": f"Payment ({payment.payment_mode or 'cash'}) - {against}",
            "reference": payment.notes or "",
            "purchase": payment.purchase if payment.purchase_id else None,
            "debit": Decimal("0"),
            "credit": _money(payment.amount),
        })

    entries.sort(key=lambda entry: entry["order"])

    balance = _money(mill.opening_balance)
    history = [{
        "date": None,
        "kind": "opening",
        "particulars": "Opening balance",
        "reference": "",
        "purchase": None,
        "debit": balance if balance > 0 else Decimal("0"),
        "credit": Decimal("0"),
        "balance": balance,
    }]

    for entry in entries:
        balance = balance + entry["debit"] - entry["credit"]
        entry["balance"] = balance
        history.append(entry)

    return history
