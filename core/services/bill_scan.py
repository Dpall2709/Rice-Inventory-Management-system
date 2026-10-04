"""
Reading a supplier's bill so the purchase entry fills itself.

Two sources, used together when both are available:

1. The QR code on a GST e-invoice. It is a signed JWT issued by the GST
   portal (NIC). Its payload carries the bill header only:

       SellerGstin, BuyerGstin, DocNo, DocTyp, DocDt (dd/mm/yyyy),
       TotInvVal, ItemCnt, MainHsnCode, Irn, IrnDt

   It never carries the rice lines. The signature is not verified here (that
   needs NIC's public key); the values are only used to pre-fill a form the
   user checks before saving.

   Kacha bills often carry a UPI QR instead (upi://pay?pa=...&pn=...&am=...),
   which gives the supplier's name and sometimes the amount.

2. A photo or PDF of the bill, read by Claude into a fixed JSON shape:
   supplier, bill number, date, tax, and every rice line (bags, bag weight,
   rate per kg, GST %). Needs ANTHROPIC_API_KEY in the environment.

The result is a "draft": plain JSON-safe data kept in the session and turned
into the initial values of the normal purchase form. Nothing is saved until
the user presses Save on that form.
"""

import base64
import io
import json
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from urllib.parse import parse_qs, unquote, urlparse

from django.conf import settings
from django.utils.translation import gettext as _

GSTIN_RE = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][0-9A-Z]Z[0-9A-Z]$")

# GST state codes - the first two digits of a GSTIN.
STATE_CODES = {
    "01": "Jammu and Kashmir", "02": "Himachal Pradesh", "03": "Punjab", "04": "Chandigarh",
    "05": "Uttarakhand", "06": "Haryana", "07": "Delhi", "08": "Rajasthan", "09": "Uttar Pradesh",
    "10": "Bihar", "11": "Sikkim", "12": "Arunachal Pradesh", "13": "Nagaland", "14": "Manipur",
    "15": "Mizoram", "16": "Tripura", "17": "Meghalaya", "18": "Assam", "19": "West Bengal",
    "20": "Jharkhand", "21": "Odisha", "22": "Chhattisgarh", "23": "Madhya Pradesh",
    "24": "Gujarat", "26": "Dadra and Nagar Haveli and Daman and Diu", "27": "Maharashtra",
    "29": "Karnataka", "30": "Goa", "31": "Lakshadweep", "32": "Kerala", "33": "Tamil Nadu",
    "34": "Puducherry", "35": "Andaman and Nicobar Islands", "36": "Telangana",
    "37": "Andhra Pradesh", "38": "Ladakh",
}


class BillScanError(Exception):
    """Something the user should be told in plain words."""


def ai_enabled():
    return bool(getattr(settings, "ANTHROPIC_API_KEY", ""))


def _dec(value):
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, ValueError):
        return None


def state_from_gstin(gstin):
    return STATE_CODES.get((gstin or "")[:2], "")


# --------------------------------------------------------------------------
# QR codes
# --------------------------------------------------------------------------

def _b64url_json(part):
    padded = part + "=" * (-len(part) % 4)
    return json.loads(base64.urlsafe_b64decode(padded.encode()).decode("utf-8"))


def _parse_doc_date(text):
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text.strip(), fmt).date()
        except (ValueError, AttributeError):
            continue
    return None


def parse_qr(text):
    """
    Understand whatever a QR code on a bill contained.

    Returns a dict with "kind" ("einvoice", "upi" or "text") and the fields
    found. Never raises for unknown content - it simply returns kind "text".
    """
    text = (text or "").strip()
    if not text:
        return None

    # GST e-invoice: header.payload.signature (a JWT).
    parts = text.split(".")
    if len(parts) == 3 and len(parts[1]) > 40:
        try:
            payload = _b64url_json(parts[1])
            data = payload.get("data", payload)
            if isinstance(data, str):
                data = json.loads(data)
        except (ValueError, UnicodeDecodeError):
            data = None

        if isinstance(data, dict) and (data.get("SellerGstin") or data.get("DocNo")):
            bill_date = _parse_doc_date(data.get("DocDt", ""))
            seller = (data.get("SellerGstin") or "").upper()
            return {
                "kind": "einvoice",
                "seller_gstin": seller,
                "buyer_gstin": (data.get("BuyerGstin") or "").upper(),
                "bill_number": str(data.get("DocNo") or ""),
                "doc_type": data.get("DocTyp") or "",
                "bill_date": bill_date.isoformat() if bill_date else "",
                "grand_total": str(_dec(data.get("TotInvVal")) or ""),
                "item_count": data.get("ItemCnt") or "",
                "main_hsn": str(data.get("MainHsnCode") or ""),
                "irn": data.get("Irn") or "",
                "seller_state": state_from_gstin(seller),
            }

    # UPI payment QR on a kacha bill.
    if text.lower().startswith("upi://"):
        query = parse_qs(urlparse(text).query)
        first = lambda key: unquote(query.get(key, [""])[0])  # noqa: E731
        return {
            "kind": "upi",
            "upi_id": first("pa"),
            "payee_name": first("pn"),
            "grand_total": str(_dec(first("am")) or ""),
            "note": first("tn"),
        }

    # Anything else: keep it, and try to spot a GSTIN in it.
    found = re.search(r"\b[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][0-9A-Z]Z[0-9A-Z]\b", text.upper())
    return {
        "kind": "text",
        "text": text[:500],
        "seller_gstin": found.group(0) if found else "",
    }


# --------------------------------------------------------------------------
# Reading the bill image / PDF with Claude
# --------------------------------------------------------------------------

_NUM = {"type": ["number", "null"]}
_STR = {"type": "string"}

BILL_SCHEMA = {
    "type": "object",
    "properties": {
        "is_bill": {"type": "boolean"},
        "supplier": {
            "type": "object",
            "properties": {
                "name": _STR, "gstin": _STR, "mobile": _STR,
                "address": _STR, "city": _STR, "state": _STR,
            },
            "required": ["name", "gstin", "mobile", "address", "city", "state"],
            "additionalProperties": False,
        },
        "buyer_name": _STR,
        "buyer_gstin": _STR,
        "bill_number": _STR,
        "bill_date": {"type": "string", "description": "YYYY-MM-DD, or empty"},
        "tax_type": {"type": "string", "enum": ["none", "cgst_sgst", "igst"]},
        "lines": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "description": _STR,
                    "hsn": _STR,
                    "bag_weight_kg": _NUM,
                    "bag_count": _NUM,
                    "quantity_kg": _NUM,
                    "rate_per_kg": _NUM,
                    "gst_percent": _NUM,
                    "amount": _NUM,
                },
                "required": ["description", "hsn", "bag_weight_kg", "bag_count",
                             "quantity_kg", "rate_per_kg", "gst_percent", "amount"],
                "additionalProperties": False,
            },
        },
        "discount": _NUM,
        "freight": _NUM,
        "labour": _NUM,
        "cgst": _NUM,
        "sgst": _NUM,
        "igst": _NUM,
        "round_off": _NUM,
        "grand_total": _NUM,
        "warnings": {"type": "array", "items": _STR},
    },
    "required": ["is_bill", "supplier", "buyer_name", "buyer_gstin", "bill_number", "bill_date",
                 "tax_type", "lines", "discount", "freight", "labour", "cgst", "sgst", "igst",
                 "round_off", "grand_total", "warnings"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """You read purchase bills that Indian rice mills and rice wholesalers give to a rice trader, and turn them into data for the trader's billing software. Bills may be printed, handwritten, in English, Hindi or a mix, GST tax invoices or kacha bills without GST.

Fill the schema from what is written on the bill:
- supplier = the seller who issued the bill (the mill), not the buyer.
- bill_number = the seller's invoice / bill number. bill_date as YYYY-MM-DD.
- tax_type: "cgst_sgst" if CGST and SGST are charged, "igst" if IGST is charged, "none" if no GST.
- lines: one entry per rice/goods line. Convert quantities and rates so the software gets bags, kg per bag and rate per kg:
  - "200 bags x 50 kg" or "200 bori 50 kg" -> bag_count 200, bag_weight_kg 50.
  - Quantity given in quintals (qtl, क्विंटल) -> quantity_kg = quintals x 100; rate per quintal -> rate_per_kg = rate / 100.
  - Rate per bag -> rate_per_kg = rate / bag weight. Rate per ton -> rate / 1000.
  - If only total weight and bag count are given, bag_weight_kg = weight / bags.
  - amount = the line's taxable value as printed. gst_percent = the line's GST rate (CGST + SGST combined, or IGST).
- discount, freight, labour (hamali, loading), cgst, sgst, igst, round_off, grand_total as printed on the bill.
- Use null for any number that is not on the bill and cannot be worked out from it; use "" for missing text. Never invent values.
- warnings: short notes for the trader about anything unclear, unreadable, handwritten corrections, conversions you made (e.g. "Rate was Rs 2,850 per quintal, converted to 28.50 per kg"), or totals that do not add up.
- is_bill: false if the image is not a bill at all."""

ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
MAX_UPLOAD_BYTES = 15 * 1024 * 1024


def _prepare_image(raw):
    """Shrink very large phone photos and normalise to JPEG; keeps tokens and upload small."""
    from PIL import Image, ImageOps

    try:
        image = Image.open(io.BytesIO(raw))
        image = ImageOps.exif_transpose(image)
    except Exception as error:  # unreadable or unsupported (e.g. HEIC)
        raise BillScanError(_(
            "This photo format cannot be read. Take the photo again as JPG or PNG, or upload a PDF."
        )) from error

    image = image.convert("RGB")
    image.thumbnail((2000, 2000))
    out = io.BytesIO()
    image.save(out, format="JPEG", quality=88)
    return out.getvalue(), "image/jpeg"


def read_bill_with_ai(raw, content_type):
    """
    Send the bill to Claude and return the extracted dict (BILL_SCHEMA shape).

    Raises BillScanError with a user-facing message on any failure.
    """
    if not ai_enabled():
        raise BillScanError(_(
            "Reading bill photos is not switched on. Add ANTHROPIC_API_KEY to the .env file."
        ))
    if len(raw) > MAX_UPLOAD_BYTES:
        raise BillScanError(_("The file is larger than 15 MB. Upload a smaller photo or PDF."))

    import anthropic

    if content_type == "application/pdf":
        source_block = {
            "type": "document",
            "source": {"type": "base64", "media_type": "application/pdf",
                       "data": base64.standard_b64encode(raw).decode()},
        }
    else:
        data, media_type = _prepare_image(raw)
        source_block = {
            "type": "image",
            "source": {"type": "base64", "media_type": media_type,
                       "data": base64.standard_b64encode(data).decode()},
        }

    client = anthropic.Anthropic(
        api_key=settings.ANTHROPIC_API_KEY,
        timeout=120.0,
        max_retries=1,
    )

    try:
        response = client.beta.messages.create(
            model=settings.BILL_SCAN_MODEL,
            max_tokens=16000,
            system=SYSTEM_PROMPT,
            messages=[{
                "role": "user",
                "content": [
                    source_block,
                    {"type": "text", "text": "Read this purchase bill."},
                ],
            }],
            output_config={
                "effort": "medium",
                "format": {"type": "json_schema", "schema": BILL_SCHEMA},
            },
            # If the model declines, the API retries on a fallback model.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
    except anthropic.AuthenticationError as error:
        raise BillScanError(_("The ANTHROPIC_API_KEY in .env is not valid.")) from error
    except anthropic.RateLimitError as error:
        raise BillScanError(_("Too many bills are being read right now. Try again in a minute.")) from error
    except anthropic.BadRequestError as error:
        raise BillScanError(_("This file could not be read. Try a clearer photo or a PDF.")) from error
    except anthropic.APIConnectionError as error:
        raise BillScanError(_("Could not reach the bill reader. Check the internet connection.")) from error
    except anthropic.APIStatusError as error:
        raise BillScanError(_("The bill reader is busy right now. Try again shortly.")) from error

    if response.stop_reason == "refusal":
        raise BillScanError(_("The bill reader could not process this file."))
    if response.stop_reason == "max_tokens":
        raise BillScanError(_("This bill is too long to read in one go. Upload it page by page."))

    text = next((block.text for block in response.content if block.type == "text"), "")
    try:
        data = json.loads(text)
    except ValueError as error:
        raise BillScanError(_("The bill could not be read clearly. Try a sharper photo.")) from error

    if not data.get("is_bill", True):
        raise BillScanError(_("This does not look like a bill. Upload a photo of the supplier's bill."))

    return data


# --------------------------------------------------------------------------
# Turning what was read into a purchase-form draft
# --------------------------------------------------------------------------

def _match_mill(company, gstin, name):
    from core.models import Mill

    mills = Mill.objects.for_company(company)
    if gstin:
        mill = mills.filter(gst_number__iexact=gstin).first()
        if mill:
            return mill
    name = (name or "").strip()
    if name:
        mill = mills.filter(mill_name__iexact=name).first()
        if mill:
            return mill
        # "Satya Rice Mill Pvt Ltd" on the bill vs "Satya Rice Mill" saved.
        core = re.sub(r"\b(pvt|private|ltd|limited|llp|and|&|co|company|m/s)\b\.?", " ", name, flags=re.I)
        core = " ".join(core.split())
        if len(core) >= 4:
            mill = mills.filter(mill_name__icontains=core).first()
            if mill:
                return mill
            for candidate in mills:
                if candidate.mill_name.lower() in name.lower():
                    return candidate
    return None


def _match_product(company, description, hsn):
    from core.models import Product

    products = list(Product.objects.for_company(company).filter(is_active=True))
    text = (description or "").lower()
    best, best_len = None, 0
    for product in products:
        name = product.rice_name.lower().strip()
        if name and name in text and len(name) > best_len:
            best, best_len = product, len(name)
    if best:
        return best
    # Every word of the product name appears in the description.
    for product in products:
        words = [w for w in re.split(r"\W+", product.rice_name.lower()) if len(w) > 2]
        if words and all(w in text for w in words):
            return product
    return None


def _money_str(value):
    value = _dec(value)
    return str(value.quantize(Decimal("0.01"))) if value is not None else ""


def build_draft(company, qr=None, ai=None, bill_file=""):
    """
    Combine what the QR and the AI read, match the supplier and rice to this
    company's records, and return a JSON-safe draft for the purchase form.
    """
    qr = qr or {}
    ai = ai or {}
    supplier = dict(ai.get("supplier") or {})
    warnings = list(ai.get("warnings") or [])

    # The QR is signed by the GST portal, so its header wins over the photo.
    gstin = (qr.get("seller_gstin") or supplier.get("gstin") or "").upper().replace(" ", "")
    bill_number = qr.get("bill_number") or ai.get("bill_number") or ""
    bill_date = qr.get("bill_date") or ai.get("bill_date") or ""
    grand_total = qr.get("grand_total") or _money_str(ai.get("grand_total"))
    supplier_name = supplier.get("name") or qr.get("payee_name") or ""

    if gstin and not GSTIN_RE.match(gstin):
        warnings.append(_("The supplier GSTIN “%(gstin)s” does not look valid - check it.") % {"gstin": gstin})
        gstin_ok = False
    else:
        gstin_ok = bool(gstin)

    try:
        parsed_date = date.fromisoformat(bill_date) if bill_date else None
    except ValueError:
        parsed_date = None
    if parsed_date and parsed_date > date.today():
        warnings.append(_("The bill date read from the bill is in the future - check it."))
        parsed_date = None

    our_gstin = (company.gst_number or "").upper()
    buyer_gstin = (qr.get("buyer_gstin") or ai.get("buyer_gstin") or "").upper()
    if our_gstin and buyer_gstin and buyer_gstin != our_gstin:
        warnings.append(
            _("This bill is made out to GSTIN %(buyer)s, not your GSTIN %(ours)s.")
            % {"buyer": buyer_gstin, "ours": our_gstin}
        )

    mill = _match_mill(company, gstin if gstin_ok else "", supplier_name)

    # Tax type: from the bill, else from the states.
    tax_type = ai.get("tax_type") or ""
    if not tax_type:
        company_state = (company.state or "").strip().lower()
        seller_state = (state_from_gstin(gstin) or supplier.get("state") or "").strip().lower()
        if qr.get("kind") == "einvoice":
            tax_type = "igst" if (company_state and seller_state and company_state != seller_state) else "cgst_sgst"
        else:
            tax_type = "cgst_sgst"

    lines = []
    for line in ai.get("lines") or []:
        product = _match_product(company, line.get("description"), line.get("hsn"))
        bags = _dec(line.get("bag_count"))
        weight = _dec(line.get("bag_weight_kg"))
        kg = _dec(line.get("quantity_kg"))
        if bags and not weight and kg:
            weight = kg / bags
        if weight and not bags and kg:
            bags = kg / weight
        rate = _dec(line.get("rate_per_kg"))
        if not rate and _dec(line.get("amount")) and kg:
            rate = _dec(line.get("amount")) / kg

        lines.append({
            "description": line.get("description") or "",
            "hsn": line.get("hsn") or "",
            "product_id": product.id if product else None,
            "product_name": product.rice_name if product else "",
            "bag_weight": int(round(weight)) if weight else None,
            "bag_count": int(round(bags)) if bags else None,
            "rate": str(rate.quantize(Decimal("0.01"))) if rate else "",
            "gst_percent": str(_dec(line.get("gst_percent")) or "") if tax_type != "none" else "0",
            "amount": _money_str(line.get("amount")),
        })

        if bags and bags != int(bags):
            warnings.append(
                _("“%(line)s”: bag count %(bags)s is not a whole number - check it.")
                % {"line": line.get("description"), "bags": bags}
            )

    if not lines and qr.get("kind") == "einvoice":
        hsn = qr.get("main_hsn")
        product = None
        if hsn:
            from core.models import Product
            product = Product.objects.for_company(company).filter(hsn_code=hsn, is_active=True).first()
        lines.append({
            "description": f"HSN {hsn}" if hsn else "",
            "hsn": hsn or "",
            "product_id": product.id if product else None,
            "product_name": product.rice_name if product else "",
            "bag_weight": None, "bag_count": None, "rate": "",
            "gst_percent": str(product.gst_percent) if product else "",
            "amount": "",
        })

    return {
        "source": "+".join(x for x in [
            "qr" if qr.get("kind") in ("einvoice", "upi") else "",
            "ai" if ai else "",
        ] if x) or "manual",
        "qr_kind": qr.get("kind", ""),
        "irn": qr.get("irn", ""),
        "supplier": {
            "name": supplier_name,
            "gstin": gstin if gstin_ok else "",
            "mobile": supplier.get("mobile", ""),
            "address": supplier.get("address", ""),
            "city": supplier.get("city", ""),
            "state": supplier.get("state") or state_from_gstin(gstin),
        },
        "mill_id": mill.id if mill else None,
        "mill_name": mill.mill_name if mill else "",
        "bill_number": bill_number,
        "bill_date": parsed_date.isoformat() if parsed_date else "",
        "tax_type": tax_type,
        "lines": lines,
        "discount": _money_str(ai.get("discount")),
        "freight": _money_str(ai.get("freight")),
        "labour": _money_str(ai.get("labour")),
        "grand_total": grand_total,
        "item_count": qr.get("item_count", ""),
        "warnings": warnings,
        "bill_file": bill_file,
    }
