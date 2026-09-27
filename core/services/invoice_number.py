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
