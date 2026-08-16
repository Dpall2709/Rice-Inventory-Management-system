from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.conf import settings
from num2words import num2words
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase.pdfmetrics import stringWidth

from io import BytesIO
from decimal import Decimal, ROUND_HALF_UP

import qrcode

from ..models import Sale, SaleItem
def _amount_words(n: Decimal):
    number = int(n)
    words = num2words(number, lang='en_IN')
    return words.title() + " Only"


def sale_invoice_pdf(request, sale_id):
    company = request.user.userprofile.company
    sale = get_object_or_404(Sale, id=sale_id, company=company)
    items = SaleItem.objects.filter(sale=sale).select_related("product", "mill")

    # ===== Company =====
    company_name = getattr(settings, "COMPANY_NAME", "Company Name")
    company_address = getattr(settings, "COMPANY_ADDRESS", "")
    company_phone = getattr(settings, "COMPANY_PHONE", "")
    company_email = getattr(settings, "COMPANY_EMAIL", "")
    company_gstin = getattr(settings, "COMPANY_GSTIN", "")
    company_pan = getattr(settings, "COMPANY_PAN", "")

    # ===== Bank =====
    bank_ac_name = getattr(settings, "BANK_ACCOUNT_NAME", company_name)
    bank_ac_no = getattr(settings, "BANK_ACCOUNT_NO", "")
    bank_name = getattr(settings, "BANK_NAME", "")
    bank_ifsc = getattr(settings, "BANK_IFSC", "")
    bank_branch = getattr(settings, "BANK_BRANCH", "")
    upi_id = getattr(settings, "UPI_ID", "")

    # ===== Amounts (invoice total = RICE ONLY) =====
    taxable = Decimal(str(sale.taxable_amount or 0))
    gst_amt = Decimal(str(sale.gst_amount or 0))
    gst_percent = Decimal(str(sale.gst_percent or 0))
    rice_total = Decimal(str(sale.total_amount or 0))  # ✅ rice only

    rice_advance = Decimal(str(sale.advance_received or 0))
    rice_due = Decimal(str(sale.balance_amount or 0))

    # ===== Transport (INFO ONLY; not included in invoice total) =====
    total_kg = Decimal(str(sale.total_quantity_kg or 0))
    total_ton = (total_kg / Decimal("1000")) if total_kg else Decimal("0")

    transport_rate = Decimal(str(sale.transport_rate_per_ton or 0))
    transport_amt = Decimal(str(sale.transport_charge or 0))
    paid_dealer = Decimal(str(sale.transport_paid_by_dealer or 0))
    paid_customer = Decimal(str(sale.transport_paid_by_customer or 0))
    transport_due = transport_amt - (paid_dealer + paid_customer)
    if transport_due < 0:
        transport_due = Decimal("0")

    # ===== Product line (one product per sale) =====
    first = items.first()
    product_name = first.product.rice_name if first else "Rice Sale"
    hsn = first.product.hsn_code if (first and first.product.hsn_code) else "-"
    total_bags = sum(int(x.bag_count or 0) for x in items) if first else 0

    sell_rate = (taxable / total_kg) if total_kg else Decimal("0")

    # ===== QR (OPTIONAL) =====
    qr_reader = None
    try:
        qr_text = (
            f"TAX INVOICE\n"
            f"Invoice: {sale.invoice_no}\n"
            f"Date: {sale.sale_date}\n"
            f"Customer: {sale.customer_name}\n"
            f"Rice Total: {rice_total}\n"
            f"Rice Due: {rice_due}\n"
        )
        qr = qrcode.QRCode(box_size=5, border=2)
        qr.add_data(qr_text)
        qr.make(fit=True)
        qr_img = qr.make_image(fill_color="black", back_color="white")
        qr_buf = BytesIO()
        qr_img.save(qr_buf, format="PNG")
        qr_buf.seek(0)
        qr_reader = ImageReader(qr_buf)
    except Exception:
        qr_reader = None

    # ===== PDF =====
    out = BytesIO()
    c = canvas.Canvas(out, pagesize=A4)
    W, H = A4

    L = 12 * mm
    R = W - 12 * mm
    TOP = H - 12 * mm
    BOT = 12 * mm
    BW = R - L

    PAD = 3 * mm
    LINE = 1

    def rect(x, y, w, h, lw=LINE):
        c.setLineWidth(lw)
        c.rect(x, y, w, h)

    def vline(x, y1, y2, lw=LINE):
        c.setLineWidth(lw)
        c.line(x, y1, x, y2)

    def hline(x1, x2, y, lw=LINE):
        c.setLineWidth(lw)
        c.line(x1, y, x2, y)

    def txt(x, y, s, size=9, bold=False):
        c.setFont("Helvetica-Bold" if bold else "Helvetica", size)
        c.drawString(x, y, str(s))

    def rtxt(x, y, s, size=9, bold=False):
        c.setFont("Helvetica-Bold" if bold else "Helvetica", size)
        c.drawRightString(x, y, str(s))

    def ctxt(x, y, s, size=10, bold=False):
        c.setFont("Helvetica-Bold" if bold else "Helvetica", size)
        c.drawCentredString(x, y, str(s))

    def fit_text(s, max_w, size=9, bold=False):
        """Truncate text to fit max width (prevents overlap in columns)."""
        font = "Helvetica-Bold" if bold else "Helvetica"
        s = str(s)
        if stringWidth(s, font, size) <= max_w:
            return s
        ell = "..."
        while s and stringWidth(s + ell, font, size) > max_w:
            s = s[:-1]
        return (s + ell) if s else ell

    def wrap_lines(s, max_w, size=8, bold=False):
        """Word-wrap to fit inside a column width."""
        font = "Helvetica-Bold" if bold else "Helvetica"
        words = str(s).split()
        lines, line = [], ""
        for w in words:
            test = (line + " " + w).strip()
            if stringWidth(test, font, size) <= max_w:
                line = test
            else:
                if line:
                    lines.append(line)
                line = w
        if line:
            lines.append(line)
        return lines

    y = TOP

    # ===== Top strip (padding) =====
    strip_h = 12 * mm
    rect(L, y - strip_h, BW, strip_h)
    txt(L + PAD, y - 8.5, "Page No. 1 of 1", size=9)
    ctxt(L + BW / 2, y - 8.5, "Bill of Supply", size=10, bold=True)
    rtxt(R - PAD, y - 8.5, "Original Copy", size=9)
    y -= strip_h

    # ===== Company box =====
    comp_h = 34 * mm
    rect(L, y - comp_h, BW, comp_h)
    ctxt(L + BW/2, y - 12, company_name, size=12, bold=True)
    ctxt(L + BW/2, y - 24, company_address, size=9)
    ctxt(L + BW/2, y - 34, f"Mobile: +91 {company_phone} | Email: {company_email}", size=9)

    gstpan = " | ".join([x for x in [
        f"GSTIN - {company_gstin}" if company_gstin else "",
        f"PAN - {company_pan}" if company_pan else ""
    ] if x])
    if gstpan:
        ctxt(L + BW/2, y - 44, gstpan, size=9)

    y -= comp_h

    # ===== Invoice details + Transport =====
    info_h = 42 * mm
    rect(L, y - info_h, BW, info_h)
    mid = L + BW/2
    vline(mid, y - info_h, y)

    txt(L + PAD, y - 10, "Invoice Details", bold=True)
    left_lines = [
        ("Invoice Number", sale.invoice_no),
        ("Invoice Date", str(sale.sale_date)),
        ("Due Date", "-"),
        ("Place of Supply", "-"),
        ("Broker Name", sale.broker.broker_name if sale.broker else "NA"),
    ]
    yy = y - 20
    for k, v in left_lines:
        txt(L + PAD, yy, k, bold=True, size=9)
        txt(L + 55*mm, yy, f": {v}", size=9)
        yy -= 5.5 * mm

    txt(mid + PAD, y - 10, "Transport Details (Info Only)", bold=True)
    right_lines = [
        ("Transporter", sale.transporter_name),
        ("Vehicle No.", f"{sale.vehicle_number}  | {sale.driver_name}"),
        ("Rate/Ton", f"Rs. {transport_rate:.2f}"),
        ("Total Ton", f"{total_ton:.3f}"),
        ("Transport Amount", f"Rs. {transport_amt:.2f}"),
        ("Advance (Dealer)", f"Rs. {paid_dealer:.2f}"),
    ]
    if paid_customer > 0:
        right_lines.append(("Paid (Customer)", f"Rs. {paid_customer:.2f}"))
    right_lines.append(("Transport Due", f"Rs. {transport_due:.2f}"))

    yy = y - 20
    for k, v in right_lines:
        txt(mid + PAD, yy, k, bold=True, size=8)
        txt(mid + 55*mm, yy, f": {v}", size=8)
        yy -= 5.2 * mm

    y -= info_h

    # ===== Billing + Shipping =====
    bs_h = 34 * mm
    rect(L, y - bs_h, BW, bs_h)
    vline(mid, y - bs_h, y)

    txt(L + PAD, y - 10, "Billing Details", bold=True)
    b_lines = [("Name", sale.customer_name), ("GSTIN", sale.customer_gst or "-"), ("Address", "-")]
    yy = y - 22
    for k, v in b_lines:
        txt(L + PAD, yy, k, bold=True)
        txt(L + 45*mm, yy, f": {v}")
        yy -= 6 * mm

    txt(mid + PAD, y - 10, "Shipping Details", bold=True)
    s_lines = [("Name", sale.customer_name), ("GSTIN", sale.customer_gst or "-"), ("Address", "-")]
    yy = y - 22
    for k, v in s_lines:
        txt(mid + PAD, yy, k, bold=True)
        txt(mid + 45*mm, yy, f": {v}")
        yy -= 6 * mm

    y -= bs_h

    # ===== Items table (FIX: columns inside BW so headers never overlap) =====
    table_h = 82 * mm
    rect(L, y - table_h, BW, table_h)

    # ✅ A4 usable width BW = (R-L). Build columns using widths that sum to BW (=186mm)
    # columns: Sr | Description | HSN | Bags | KG | Rate | Taxable | GST% | GST | Amount
    w_sr      = 10 * mm
    w_desc    = 64 * mm
    w_hsn     = 14 * mm
    w_bags    = 12 * mm
    w_kg      = 16 * mm
    w_rate    = 14 * mm
    w_taxable = 18 * mm
    w_gstp    = 10 * mm
    w_gst     = 12 * mm
    w_amount  = 16 * mm

    # Sanity: (w_sr+w_desc+...+w_amount) == BW
    col = [L]
    for w in [w_sr, w_desc, w_hsn, w_bags, w_kg, w_rate, w_taxable, w_gstp, w_gst, w_amount]:
        col.append(col[-1] + w)
    # col[-1] should be == R (or extremely close due to float)

    # Draw vertical lines (inside the box)
    for x in col[1:-1]:
        vline(x, y - table_h, y)

    # Header separator
    header_h = 12 * mm
    hline(L, R, y - header_h)

    # ---- Header row (small font for tight columns) ----
    txt(L + 2,      y - 9*mm, "Sr", bold=True, size=8)
    txt(col[1] + 2, y - 9*mm, "Item Description", bold=True, size=8)
    txt(col[2] + 2, y - 9*mm, "HSN", bold=True, size=8)

    rtxt(col[4] - 2, y - 9*mm, "Bags",   bold=True, size=8)
    rtxt(col[5] - 2, y - 9*mm, "KG",     bold=True, size=8)
    rtxt(col[6] - 2, y - 9*mm, "Rate",   bold=True, size=8)
    rtxt(col[7] - 2, y - 9*mm, "Taxable",bold=True, size=8)
    rtxt(col[8] - 2, y - 9*mm, "GST%",   bold=True, size=8)
    rtxt(col[9] - 2, y - 9*mm, "GST",    bold=True, size=8)
    rtxt(R - 2,      y - 9*mm, "Amount", bold=True, size=8)

    # ---- Data row ----
    row_y = y - 22 * mm
    txt(L + 2, row_y, "1", size=9)

    # Description must never enter HSN column
    desc_max_w = (col[2] - col[1]) - 6
    safe_desc = fit_text(product_name, desc_max_w, size=9)
    txt(col[1] + 2, row_y, safe_desc, size=9)

    txt(col[2] + 2, row_y, hsn, size=9)

    rtxt(col[4] - 2, row_y, str(total_bags),     size=9)
    rtxt(col[5] - 2, row_y, f"{total_kg:.2f}",   size=9)
    rtxt(col[6] - 2, row_y, f"{sell_rate:.2f}",  size=9)
    rtxt(col[7] - 2, row_y, f"{taxable:.2f}",    size=9)
    rtxt(col[8] - 2, row_y, f"{gst_percent:.2f}",size=9)
    rtxt(col[9] - 2, row_y, f"{gst_amt:.2f}",    size=9)
    rtxt(R - 2,      row_y, f"{rice_total:.2f}", size=9)

    y -= table_h

    # ===== Rice totals =====
    tot_h = 38 * mm   # 🔥 reduce from 44mm to 38mm
    rect(L, y - tot_h, BW, tot_h)

    txt(L + PAD, y - 10, "Rice Payment Summary (Invoice Total = Rice Only)", bold=True)

    txt(L + PAD, y - 20, "Taxable Amount", bold=True)
    txt(L + 52*mm, y - 20, f": Rs. {taxable:.2f}")

    txt(L + PAD, y - 28, "GST Amount", bold=True)
    txt(L + 52*mm, y - 28, f": Rs. {gst_amt:.2f}")

    txt(L + PAD, y - 36, "Advance Received (Rice)", bold=True)
    txt(L + 52*mm, y - 36, f": Rs. {rice_advance:.2f}")

    rtxt(R - PAD, y - 20, f"Rice Total: Rs. {rice_total:.2f}", bold=True)
    rtxt(R - PAD, y - 30, f"Rice Due: Rs. {rice_due:.2f}", bold=True)

    txt(L + PAD, y - 46, f"Amount in Words: {_amount_words(rice_total)}", size=9, bold=True)

    y -= tot_h

    # ===== Bottom section: Terms | Bank | QR/Stamp =====
    bottom_h = y - BOT
    rect(L, BOT, BW, bottom_h)

    c1 = L + BW/3
    c2 = L + 2*BW/3
    vline(c1, BOT, y)
    vline(c2, BOT, y)

    # Terms
    txt(L + PAD, y - 12, "Terms and Conditions", bold=True, size=10)

    terms = [
        "E & O.E.",
        "1. Goods once sold will not be taken back.",
        "2. Interest @ 18% p.a. will be charged if payment is delayed.",
        "3. In case of non-payment, legal action may be initiated.",
        "4. Subject to local jurisdiction only."
    ]

    terms_left = L + PAD
    terms_right = c1 - PAD
    terms_w = terms_right - terms_left

    ty = y - 24   # 🔥 little more space from title

    for t in terms:
        lines = wrap_lines(t, terms_w, size=8)
        for line in lines:
            if ty < BOT + 20:   # 🔥 increase bottom margin safety
                break
            txt(terms_left, ty, line, size=8)
            ty -= 9  # 🔥 slightly tighter spacing so all lines fit



    # Bank details
    midL = c1
    txt(midL + PAD, y - 12, "Bank / Payment Details", bold=True, size=10)
    by = y - 26
    txt(midL + PAD, by, f"A/C Name: {bank_ac_name}", size=8); by -= 10
    txt(midL + PAD, by, f"A/C No: {bank_ac_no}", size=8); by -= 10
    txt(midL + PAD, by, f"Bank: {bank_name}", size=8); by -= 10
    txt(midL + PAD, by, f"IFSC: {bank_ifsc}", size=8); by -= 10
    txt(midL + PAD, by, f"Branch: {bank_branch}", size=8); by -= 10
    if upi_id:
        txt(midL + PAD, by, f"UPI: {upi_id}", size=8)

    # Right: QR or Stamp
    rightL = c2
    txt(rightL + PAD, y - 12, "Stamp / QR", bold=True, size=10)

    stamp_box = 62 * mm
    box_x = rightL + (BW/3 - stamp_box)/2
    box_y = y - 80 * mm

    rect(box_x, box_y, stamp_box, stamp_box)

    if qr_reader is not None and box_y > (BOT + 5*mm):
        c.drawImage(qr_reader, box_x + 2, box_y + 2, width=stamp_box-4, height=stamp_box-4, mask="auto")
        ctxt(box_x + stamp_box/2, box_y + stamp_box + 3, "QR", size=9, bold=True)

    rtxt(R - PAD, BOT + 25, f"For {company_name}", size=9)
    rtxt(R - PAD, BOT + 12, "Authorized Signatory", size=9)

    c.showPage()
    c.save()

    pdf = out.getvalue()
    out.close()

    filename = f"Invoice_{sale.invoice_no}.pdf"
    resp = HttpResponse(content_type="application/pdf")
    resp["Content-Disposition"] = f'attachment; filename="{filename}"'
    resp.write(pdf)
    return resp