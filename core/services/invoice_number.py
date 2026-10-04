"""
Document numbers, one series per company.

Used for sale invoices (SAL-20260927-0001) and purchase references
(PUR-20260927-0001).

Each company has its own counter row per prefix per day, locked while the next
number is handed out, so two users saving at the same moment can never receive
the same number.
"""

from django.db import transaction
from django.utils import timezone

from core.models import InvoiceSequence


@transaction.atomic
def next_number(company, prefix, on_date=None):
    """Reserve and return the next number in this company's `prefix` series."""
    on_date = on_date or timezone.localdate()

    prefix = (prefix or "DOC").strip().upper()
    key = f"{prefix}-{on_date.strftime('%Y%m%d')}"

    sequence, _ = InvoiceSequence.objects.get_or_create(company=company, key=key)

    # select_for_update() makes a second user wait here instead of reading the
    # same number. The lock is released when the transaction ends.
    sequence = InvoiceSequence.objects.select_for_update().get(pk=sequence.pk)

    sequence.last_number += 1
    sequence.save(update_fields=["last_number", "updated_at"])

    return f"{key}-{sequence.last_number:04d}"


def next_sale_invoice_no(company, on_date=None):
    """The next sale invoice number, using the company's own prefix."""
    return next_number(company, company.invoice_prefix or "SAL", on_date)


def next_purchase_ref(company, on_date=None):
    """Our internal reference for a purchase bill (the supplier has their own)."""
    return next_number(company, "PUR", on_date)


SUPPLIER_BILL_PREFIX = "BILL"


def _supplier_key(mill):
    return f"{SUPPLIER_BILL_PREFIX}-M{mill.pk}"


def _taken(mill, number):
    from core.models import Purchase

    return Purchase.objects.filter(mill=mill, invoice_no__iexact=number).exists()


@transaction.atomic
def next_supplier_bill_no(mill):
    """
    The next automatic bill number for one supplier: BILL-001, BILL-002, ...

    Used when the mill's bill has no number of its own. Every supplier has
    its own series, kept in the same locked counter table as invoices, and a
    number already typed in by hand for this supplier is skipped.
    """
    sequence, _ = InvoiceSequence.objects.get_or_create(company=mill.company, key=_supplier_key(mill))
    sequence = InvoiceSequence.objects.select_for_update().get(pk=sequence.pk)

    number = sequence.last_number
    while True:
        number += 1
        candidate = f"{SUPPLIER_BILL_PREFIX}-{number:03d}"
        if not _taken(mill, candidate):
            break

    sequence.last_number = number
    sequence.save(update_fields=["last_number", "updated_at"])
    return candidate


def peek_supplier_bill_no(mill):
    """What the next automatic number will be, without reserving it (for hints)."""
    sequence = InvoiceSequence.objects.filter(company=mill.company, key=_supplier_key(mill)).first()
    number = sequence.last_number if sequence else 0
    while True:
        number += 1
        candidate = f"{SUPPLIER_BILL_PREFIX}-{number:03d}"
        if not _taken(mill, candidate):
            return candidate
