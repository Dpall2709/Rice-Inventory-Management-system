"""
Scan a supplier's bill to fill the purchase form.

    GET  /purchase/scan/                the scan page (camera / photo / PDF / QR text)
    POST /purchase/scan/                read what was given, keep a draft in the session,
                                        then open the normal purchase form pre-filled
    POST /purchase/scan/add-supplier/   create the supplier read from the bill
    GET  /purchase/<id>/bill/           the original bill file (only for its own company)

Nothing is saved as a purchase here - the user checks the pre-filled form and
presses Save, which runs every normal validation.
"""

import mimetypes
import os
import uuid

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.http import FileResponse, Http404
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from core.forms import MillForm
from core.models import Mill, Purchase
from core.services.bill_scan import (
    ALLOWED_IMAGE_TYPES,
    BillScanError,
    ai_enabled,
    build_draft,
    parse_qr,
    read_bill_with_ai,
)
from core.tenancy import company_of, tenant_object_or_404

from ..base_imports import *

SESSION_KEY = "purchase_scan_draft"
PENDING_DIR = "purchase_bills/pending"


def get_draft(request):
    return request.session.get(SESSION_KEY)


def clear_draft(request, delete_file=False):
    draft = request.session.pop(SESSION_KEY, None)
    if delete_file and draft and draft.get("bill_file"):
        try:
            default_storage.delete(draft["bill_file"])
        except OSError:
            pass
    request.session.modified = True


def _guess_type(upload):
    content_type = (upload.content_type or "").lower()
    if content_type in ALLOWED_IMAGE_TYPES or content_type == "application/pdf":
        return content_type
    guessed, _enc = mimetypes.guess_type(upload.name or "")
    return guessed or content_type


@login_required
def scan_purchase_bill(request):
    company = company_of(request)
    error = ""

    if request.method == "POST":
        qr_text = (request.POST.get("qr_text") or "").strip()
        upload = request.FILES.get("bill")

        if not qr_text and not upload:
            error = _("Scan the QR code or choose a photo / PDF of the bill first.")
        else:
            qr = parse_qr(qr_text) if qr_text else None
            ai = None
            bill_path = ""
            ai_error = ""

            if upload:
                content_type = _guess_type(upload)
                if content_type not in ALLOWED_IMAGE_TYPES and content_type != "application/pdf":
                    if content_type.startswith("image/"):
                        # e.g. iPhone HEIC - Pillow normalises what it can.
                        content_type = "image/jpeg"
                    else:
                        error = _("Upload a photo (JPG, PNG) or a PDF of the bill.")

                if not error:
                    raw = upload.read()
                    extension = ".pdf" if content_type == "application/pdf" else (
                        os.path.splitext(upload.name or "")[1].lower() or ".jpg")
                    bill_path = default_storage.save(
                        f"{PENDING_DIR}/{company.id}-{uuid.uuid4().hex}{extension}", ContentFile(raw)
                    )

                    if ai_enabled():
                        try:
                            ai = read_bill_with_ai(raw, content_type)
                        except BillScanError as exc:
                            ai_error = str(exc)

            if not error:
                if not ai and not (qr and qr.get("kind") in ("einvoice", "upi")):
                    if bill_path:
                        default_storage.delete(bill_path)
                    if ai_error:
                        error = ai_error
                    elif qr:
                        error = _("That QR code is not a GST e-invoice or UPI code, so nothing could be filled from it.")
                    else:
                        error = _("Reading bill photos is not switched on. Scan the bill's QR code instead, or ask the owner to add ANTHROPIC_API_KEY.")
                else:
                    clear_draft(request, delete_file=True)
                    draft = build_draft(company, qr=qr, ai=ai, bill_file=bill_path)
                    if ai_error:
                        draft["warnings"].insert(0, ai_error)
                    request.session[SESSION_KEY] = draft
                    return redirect(f"{reverse('add_purchase')}?scan=1")

    return render(request, "core/purchase_scan.html", {
        "error": error,
        "ai_enabled": ai_enabled(),
        "has_draft": bool(get_draft(request)),
    })


@login_required
@require_POST
def scan_add_supplier(request):
    """Create the mill read from the bill, then go back to the pre-filled form."""
    company = company_of(request)
    draft = get_draft(request)
    if not draft:
        return redirect("scan_purchase_bill")

    supplier = draft.get("supplier") or {}
    form = MillForm(
        {
            "mill_name": request.POST.get("mill_name") or supplier.get("name", ""),
            "mobile": request.POST.get("mobile") or supplier.get("mobile", ""),
            "gst_number": supplier.get("gstin", ""),
            "address": supplier.get("address", ""),
            "city": supplier.get("city", ""),
            "state": supplier.get("state", ""),
            "owner_name": "",
            "opening_balance": "0",
            "notes": _("Added from a scanned bill."),
        },
        company=company,
    )

    if form.is_valid():
        mill = form.save(commit=False)
        mill.company = company
        mill.save()
        draft["mill_id"] = mill.id
        draft["mill_name"] = mill.mill_name
        request.session[SESSION_KEY] = draft
        messages.success(request, _("Supplier “%(mill)s” added.") % {"mill": mill.mill_name})
    else:
        errors = "; ".join(str(e) for errs in form.errors.values() for e in errs)
        messages.error(request, _("Could not add the supplier: %(errors)s") % {"errors": errors})

    return redirect(f"{reverse('add_purchase')}?scan=1")


@login_required
def discard_scan(request):
    clear_draft(request, delete_file=True)
    return redirect("add_purchase")


@login_required
def purchase_bill_file(request, purchase_id):
    """The original bill - served through Django so only its own company can open it."""
    purchase = tenant_object_or_404(Purchase, request, purchase_id)
    if not purchase.bill_file:
        raise Http404
    try:
        handle = purchase.bill_file.open("rb")
    except (FileNotFoundError, OSError):
        raise Http404
    content_type, _enc = mimetypes.guess_type(purchase.bill_file.name)
    return FileResponse(handle, content_type=content_type or "application/octet-stream")


def draft_initial(company, draft):
    """Initial values for PurchaseForm and its item formset, from a scan draft."""
    from core.models import Product

    form_initial = {
        "mill": draft.get("mill_id"),
        "invoice_no": draft.get("bill_number", ""),
        "purchase_date": draft.get("bill_date") or None,
        "tax_type": draft.get("tax_type") or "cgst_sgst",
        "discount_amount": draft.get("discount") or None,
        "transport_amount": draft.get("freight") or None,
        "transport_by_mill": bool(draft.get("freight")),
        "labour_amount": draft.get("labour") or None,
        "labour_by_mill": bool(draft.get("labour")),
        "margin_percent": company.default_margin_percent,
    }

    products = {p.id: p for p in Product.objects.for_company(company)}
    lines = []
    for line in draft.get("lines") or []:
        product = products.get(line.get("product_id"))
        gst = line.get("gst_percent")
        if (gst in ("", None)) and product:
            gst = product.gst_percent
        lines.append({
            "product": product.id if product else None,
            "bag_weight": line.get("bag_weight") or 50,
            "bag_count": line.get("bag_count"),
            "purchase_price": line.get("rate") or None,
            "gst_percent": gst if gst not in ("", None) else 0,
        })

    return form_initial, lines


def attach_scan(purchase, draft):
    """Move the scanned file onto the saved purchase and record where the data came from."""
    path = draft.get("bill_file")
    if path and default_storage.exists(path):
        with default_storage.open(path, "rb") as handle:
            name = os.path.basename(path).split("-", 1)[-1]
            purchase.bill_file.save(f"{purchase.id}-{name}", ContentFile(handle.read()), save=False)
        default_storage.delete(path)
    purchase.entry_source = draft.get("source") or "manual"
    purchase.irn = draft.get("irn", "")[:80]
