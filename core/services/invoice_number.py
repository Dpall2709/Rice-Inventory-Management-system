"""
Sale invoice numbers, one series per company.

The old code looked at every company's sales and took the highest number, so
two tenants shared one series and two users saving at the same moment could get
the same number. This version keeps a counter row per company and locks it while
it is being read, so every number is handed out exactly once.

Format:  <PREFIX>-<YYYYMMDD>-<0001>   e.g.  SAL-20260927-0003
"""

from django.db import transaction
from django.utils import timezone

from core.models import InvoiceSequence


@transaction.atomic
def next_sale_invoice_no(company, on_date=None):
    """
    Reserve and return the next invoice number for this company.

    Must be called inside the same transaction that creates the Sale, which is
    already the case in the sale-saving code.
    """
    on_date = on_date or timezone.localdate()

    prefix = (company.invoice_prefix or "SAL").strip().upper()
    key = f"{prefix}-{on_date.strftime('%Y%m%d')}"

    sequence, _ = InvoiceSequence.objects.get_or_create(company=company, key=key)

    # select_for_update() makes a second user wait here instead of reading the
    # same number. The lock is released when the transaction ends.
    sequence = (
        InvoiceSequence.objects
        .select_for_update()
        .get(pk=sequence.pk)
    )

    sequence.last_number += 1
    sequence.save(update_fields=["last_number", "updated_at"])

    return f"{key}-{sequence.last_number:04d}"
