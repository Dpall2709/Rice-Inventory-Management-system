"""
The GST sale invoice as a PDF.

Built with ReportLab's flowing layout (platypus) instead of drawing text at
fixed x/y positions. The old version placed every block at a hard-coded
height, so on an A4 page the bottom section was squeezed into ~30 mm: the
terms were cut off, the bank details ran into the signature, and the QR box
was drawn below the page edge. Here every box takes the height its text
needs, long names and addresses wrap inside their cell, and an invoice with
many lines continues on a second page with the table header repeated.

Layout (A4, 12 mm margins all round):

    Original for recipient | TAX INVOICE / BILL OF SUPPLY | invoice no.
    seller: name, address, contact, GSTIN / PAN
    invoice details        | transport details
    bill to                | ship to
    item lines (one row per rice line)
    amount in words, bank, QR | taxable, CGST/SGST or IGST, total, received, due
    TRANSPORT / FREIGHT box: what we paid the driver, what you pay (not in the total)
    terms                  | for <company> / authorised signatory
"""

from decimal import Decimal
from io import BytesIO

import qrcode
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    Image,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from xml.sax.saxutils import escape

from ..models import Sale
from ..services.customer_ledger import sale_payment_status
from ..services.sale_service import amount_in_words
from ..tenancy import company_of, tenant_object_or_404

MARGIN = 12 * mm
PAGE_W, PAGE_H = A4
WIDTH = PAGE_W - 2 * MARGIN          # 186 mm of usable width

BORDER = colors.HexColor("#111827")
GRID = colors.HexColor("#9ca3af")
SHADE = colors.HexColor("#f3f4f6")

DEFAULT_TERMS = [
    "Goods once sold will not be taken back.",
    "Interest @ 18% p.a. will be charged if payment is delayed.",
    "Subject to local jurisdiction only.",
]


def _styles():
    base = ParagraphStyle("base", fontName="Helvetica", fontSize=8.5, leading=11)
    return {
        "base": base,
        "small": ParagraphStyle("small", parent=base, fontSize=7.5, leading=9.5),
        "label": ParagraphStyle("label", parent=base, fontName="Helvetica-Bold", fontSize=7.5,
                                leading=9.5, textColor=colors.HexColor("#4b5563")),
        "bold": ParagraphStyle("bold", parent=base, fontName="Helvetica-Bold"),
        "center": ParagraphStyle("center", parent=base, alignment=TA_CENTER),
        "title": ParagraphStyle("title", parent=base, fontName="Helvetica-Bold", fontSize=10.5,
                                alignment=TA_CENTER, leading=13),
        "company": ParagraphStyle("company", parent=base, fontName="Helvetica-Bold", fontSize=15,
                                  leading=19, alignment=TA_CENTER),
        "right": ParagraphStyle("right", parent=base, alignment=TA_RIGHT),
        "right_bold": ParagraphStyle("right_bold", parent=base, fontName="Helvetica-Bold", alignment=TA_RIGHT),
        "th": ParagraphStyle("th", parent=base, fontName="Helvetica-Bold", fontSize=7.5, leading=9.5),
        "th_right": ParagraphStyle("th_right", parent=base, fontName="Helvetica-Bold", fontSize=7.5,
                                   leading=9.5, alignment=TA_RIGHT),
    }


def _p(text, style):
    """A wrapping paragraph. Text is escaped; <br/> is added for new lines."""
    safe = escape(str(text or "")).replace("\n", "<br/>")
    return Paragraph(safe, style)


def _rich(html, style):
    """A paragraph whose markup (<b>, <br/>) was built here, not typed by users."""
    return Paragraph(html, style)


def _rs(value):
    """Indian digit grouping: 12,34,567.89 (Helvetica has no ₹ sign, so 'Rs.')."""
    value = Decimal(value or 0).quantize(Decimal("0.01"))
    sign = "-" if value < 0 else ""
    whole, frac = f"{abs(value):.2f}".split(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        whole = ",".join(groups + [tail])
    return f"{sign}{whole}.{frac}"


def _qr_image(company, sale, due):
    """
    A UPI payment QR when the company has a UPI id (scan to pay the balance),
    otherwise a QR with the invoice summary.
    """
    upi = (company.upi_id or "").strip()
    if upi:
        from urllib.parse import quote

        data = (
            f"upi://pay?pa={quote(upi)}&pn={quote(company.company_name)}"
            f"&am={Decimal(due):.2f}&cu=INR&tn={quote('Invoice ' + sale.invoice_no)}"
        )
        caption = "Scan to pay (UPI)"
    else:
        data = (
            f"Invoice: {sale.invoice_no}\nDate: {sale.sale_date:%d-%m-%Y}\n"
            f"Customer: {sale.customer_name}\nTotal: Rs. {sale.total_amount}\nDue: Rs. {due}"
        )
        caption = "Invoice details"

    try:
        qr = qrcode.QRCode(box_size=6, border=1)
        qr.add_data(data)
        qr.make(fit=True)
        buffer = BytesIO()
        qr.make_image(fill_color="black", back_color="white").save(buffer, format="PNG")
        buffer.seek(0)
        return Image(buffer, width=24 * mm, height=24 * mm), caption
    except Exception:
        return None, ""


def _box(rows, col_widths, extra=()):
    """A bordered table with a vertical rule between its columns."""
    table = Table(rows, colWidths=col_widths)
    style = [
        ("BOX", (0, 0), (-1, -1), 0.8, BORDER),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
    if len(col_widths) > 1:
        style.append(("LINEAFTER", (0, 0), (-2, -1), 0.8, BORDER))
    style.extend(extra)
    table.setStyle(TableStyle(style))
    return table


FREIGHT_FILL = colors.HexColor("#FEF3C7")      # soft amber - stands out, prints well
FREIGHT_BORDER = colors.HexColor("#B45309")


def _transport_box(sale, st):
    """
    Freight, in its own highlighted box, separate from the goods: what the
    truck costs, what WE have paid, and what YOU (the party) have to pay -
    worded for who carries the freight on this sale. Never part of the
    invoice total.
    """
    from ..services.sale_service import settlement

    figures = settlement(sale)
    total = figures["freight_total"]
    we_paid = figures["freight_paid_by_us"]
    if not total and not we_paid and not sale.vehicle_number:
        return None

    you_pay = max(total - we_paid, Decimal("0"))
    rate = Decimal(sale.transport_rate_per_ton or 0)

    head = ParagraphStyle("fh", parent=st["bold"], textColor=FREIGHT_BORDER, fontSize=9.5)
    big = ParagraphStyle("fb", parent=st["right_bold"], fontSize=10)

    details = []
    if sale.vehicle_number:
        details.append(f"Vehicle: {sale.vehicle_number}")
    if sale.driver_name or sale.driver_mobile:
        details.append("Driver: " + " ".join(x for x in [sale.driver_name, sale.driver_mobile] if x))
    if sale.transporter_name:
        details.append(f"Transporter: {sale.transporter_name}")
    weight = f"{figures['dispatched_kg'] / Decimal('1000'):.3f} ton"
    details.append(f"Weight: {weight}" + (f" @ Rs. {_rs(rate)} per ton" if rate else ""))

    lines = [("Total freight for this truck", total)]
    if sale.freight_borne_by == "us":
        lines += [
            ("WE HAVE PAID - advance to the driver", we_paid),
            ("YOU HAVE TO PAY - balance to the driver on unloading", you_pay),
        ]
        note = (
            f"We have paid Rs. {_rs(we_paid)} to the driver as advance. Please pay the driver the balance "
            f"Rs. {_rs(you_pay)} when the goods are unloaded, and deduct that amount from your payment to us."
        )
    elif sale.freight_borne_by == "customer":
        lines += [
            ("WE HAVE PAID - advance to the driver on your behalf", we_paid),
            ("YOU HAVE TO PAY - balance to the driver on unloading", you_pay),
        ]
        note = (
            f"The freight is to your account. We have paid Rs. {_rs(we_paid)} advance to the driver for you - "
            f"please add it to your payment to us. Pay the driver the balance Rs. {_rs(you_pay)} on unloading."
        )
    else:
        note = "The freight is to be settled directly between you and the transporter."

    money_rows = [[_p(label, st["bold"] if "PAY" in label else st["base"]), _p(f"Rs. {_rs(value)}", big)]
                  for label, value in lines]
    money_table = Table(money_rows, colWidths=[WIDTH * 0.42, WIDTH * 0.18])
    money_table.setStyle(TableStyle([
        ("LINEBELOW", (0, 0), (-1, -2), 0.25, FREIGHT_BORDER),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))

    left = [_p("TRANSPORT / FREIGHT  (not included in the invoice total)", head), Spacer(1, 3)]
    left += [_p(line, st["small"]) for line in details]
    right = [money_table, Spacer(1, 4), _p(note, st["small"])]

    box = Table([[left, right]], colWidths=[WIDTH * 0.36, WIDTH * 0.64])
    box.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 1.2, FREIGHT_BORDER),
        ("BACKGROUND", (0, 0), (-1, -1), FREIGHT_FILL),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 7), ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    return KeepTogether([box])


def _logo(company):
    """The company's uploaded logo, scaled to fit 24 mm, or None."""
    if not getattr(company, "logo", None):
        return None
    try:
        from reportlab.lib.utils import ImageReader

        with company.logo.open("rb") as handle:
            data = BytesIO(handle.read())
        width, height = ImageReader(data).getSize()
        data.seek(0)
        scale = min(24 * mm / width, 20 * mm / height)
        return Image(data, width=width * scale, height=height * scale)
    except Exception:
        return None


def _with_state_code(state, gstin):
    """'Bihar (10)' - GST invoices name the state code with the place of supply."""
    code = (gstin or "")[:2]
    if state and code.isdigit():
        return f"{state} ({code})"
    return state or "-"


def build_invoice_pdf(company, sale):
    """Return the invoice PDF as bytes."""
    st = _styles()
    # Lines of the same product from different mills print as one line.
    from ..services.sale_service import invoice_lines

    items = invoice_lines(sale)
    status = sale_payment_status(company, sale)
    half = WIDTH / 2

    story = []

    # ---- title strip -------------------------------------------------------
    title = "TAX INVOICE" if sale.is_tax_invoice else "BILL OF SUPPLY"
    story.append(_box(
        [[_p("Original for recipient", st["small"]), _p(title, st["title"]),
          _p(sale.invoice_no, ParagraphStyle("r", parent=st["small"], alignment=TA_RIGHT))]],
        [WIDTH * 0.3, WIDTH * 0.4, WIDTH * 0.3],
        extra=[("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LINEAFTER", (0, 0), (-2, -1), 0, colors.white)],
    ))

    # ---- seller ------------------------------------------------------------
    address = ", ".join(
        part.strip() for part in [company.address, company.city, company.state, company.pincode]
        if part and part.strip()
    )
    contact = " | ".join(x for x in [
        f"Mobile: {company.mobile}" if company.mobile else "",
        f"Email: {company.email}" if company.email else "",
    ] if x)
    tax_ids = " | ".join(x for x in [
        f"GSTIN: {company.gst_number}" if company.gst_number else "",
        f"PAN: {company.pan_number}" if company.pan_number else "",
    ] if x)

    seller = [_p(company.company_name, st["company"])]
    for line in (address, contact, tax_ids):
        if line:
            seller.append(_p(line, st["center"]))
    logo = _logo(company)
    if logo is not None:
        # Logo on the left, name and details centred in the rest.
        header = Table([[logo, seller]], colWidths=[28 * mm, WIDTH - 28 * mm - 12])
        header.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ]))
        seller_cell = [header]
    else:
        seller_cell = seller
    story.append(_box([[seller_cell]], [WIDTH], extra=[("TOPPADDING", (0, 0), (-1, -1), 7),
                                                        ("BOTTOMPADDING", (0, 0), (-1, -1), 7)]))

    # ---- invoice + transport ----------------------------------------------
    def kv_table(pairs, width):
        rows = [[_p(k, st["label"]), _p(v, st["base"])] for k, v in pairs]
        table = Table(rows, colWidths=[width * 0.38, width * 0.62])
        table.setStyle(TableStyle([
            ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 2),
            ("TOPPADDING", (0, 0), (-1, -1), 1), ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        return table

    inner = half - 10
    invoice_pairs = [
        ("Invoice No.", sale.invoice_no),
        ("Invoice Date", f"{sale.sale_date:%d-%m-%Y}"),
    ]
    if sale.due_date:
        invoice_pairs.append(("Due Date", f"{sale.due_date:%d-%m-%Y}"))
    invoice_pairs.append(("Place of Supply", _with_state_code(sale.place_of_supply, sale.customer_gst)))
    invoice_pairs.append(("Reverse Charge", "No"))

    transport_pairs = [
        ("Vehicle No.", sale.vehicle_number or "-"),
        ("Driver", " / ".join(x for x in [sale.driver_name, sale.driver_mobile] if x) or "-"),
        ("Transporter", sale.transporter_name or "-"),
        ("Weight", f"{sale.total_ton:.3f} ton ({sale.total_quantity_kg} kg)"),
    ]

    story.append(_box(
        [[[_p("Invoice Details", st["bold"]), Spacer(1, 3), kv_table(invoice_pairs, inner)],
          [_p("Transport Details", st["bold"]), Spacer(1, 3), kv_table(transport_pairs, inner)]]],
        [half, half],
    ))

    # ---- buyer -------------------------------------------------------------
    def party(heading, address_text):
        block = [_p(heading, st["label"]), _p(sale.customer_name, st["bold"])]
        if address_text:
            block.append(_p(address_text, st["base"]))
        if sale.customer_gst:
            block.append(_rich(f"GSTIN: <b>{escape(sale.customer_gst)}</b>", st["base"]))
        if sale.place_of_supply:
            block.append(_p(f"State: {sale.place_of_supply}", st["base"]))
        mobile = getattr(sale.customer, "mobile", "") if sale.customer_id else ""
        if mobile:
            block.append(_p(f"Mobile: {mobile}", st["base"]))
        return block

    story.append(_box(
        [[party("BILL TO", sale.billing_address),
          party("SHIP TO", sale.shipping_address or sale.billing_address)]],
        [half, half],
    ))

    # ---- item lines --------------------------------------------------------
    widths_mm = [8, 50, 15, 12, 18, 15, 22, 11, 16, 19]       # = 186 mm
    widths = [w * mm for w in widths_mm]
    head = ["#", "Item Description", "HSN", "Bags", "Qty (kg)", "Rate/kg", "Taxable", "GST%", "GST", "Amount"]
    rows = [[_p(h, st["th"] if i < 3 else st["th_right"]) for i, h in enumerate(head)]]

    for index, item in enumerate(items, start=1):
        description = [_p(item.product.rice_name, st["bold"]),
                       _p(f"{item.bag_count} {'bag' if item.bag_count == 1 else 'bags'} x {item.bag_weight} kg", st["small"])]
        rows.append([
            _p(index, st["base"]),
            description,
            _p(item.product.hsn_code or "-", st["base"]),
            _p(item.bag_count, st["right"]),
            _p(f"{item.total_weight:.2f}", st["right"]),
            _p(f"{item.rate_per_kg:.2f}", st["right"]),
            _p(_rs(item.amount), st["right"]),
            _p(f"{item.gst_percent:g}" if item.gst_percent else "-", st["right"]),
            _p(_rs(item.gst_amount) if item.gst_amount else "-", st["right"]),
            _p(_rs(item.line_total), st["right_bold"]),
        ])

    if not items:
        rows.append(["", _p("No lines", st["base"])] + [""] * 8)

    rows.append([
        "", _p("Total", st["bold"]), "",
        _p(sale.total_bags, st["right_bold"]),
        _p(f"{sale.total_quantity_kg:.2f}", st["right_bold"]),
        "",
        _p(_rs(sale.taxable_amount), st["right_bold"]),
        "",
        _p(_rs(sale.gst_amount), st["right_bold"]),
        _p(_rs(sale.taxable_amount + sale.gst_amount), st["right_bold"]),
    ])

    item_table = Table(rows, colWidths=widths, repeatRows=1)
    item_table.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.8, BORDER),
        ("LINEBELOW", (0, 0), (-1, 0), 0.8, BORDER),
        ("LINEABOVE", (0, -1), (-1, -1), 0.8, BORDER),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, GRID),
        ("BACKGROUND", (0, 0), (-1, 0), SHADE),
        ("BACKGROUND", (0, -1), (-1, -1), SHADE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(item_table)

    transport = _transport_box(sale, st)
    if transport is not None:
        story.append(Spacer(1, 4))
        story.append(transport)
        story.append(Spacer(1, 4))

    # ---- words, bank, QR | totals -----------------------------------------
    left_w = WIDTH * 0.56
    right_w = WIDTH - left_w

    bank_lines = [f"A/C Name: {company.bank_account_name or company.company_name}"]
    if company.bank_account_no:
        bank_lines.append(f"A/C No: {company.bank_account_no}")
    if company.bank_name:
        bank_lines.append(f"Bank: {company.bank_name}" + (f", {company.bank_branch}" if company.bank_branch else ""))
    if company.bank_ifsc:
        bank_lines.append(f"IFSC: {company.bank_ifsc}")
    if company.upi_id:
        bank_lines.append(f"UPI: {company.upi_id}")

    qr, caption = _qr_image(company, sale, status["due"])
    bank_block = [_p("Bank / Payment Details", st["label"])] + [_p(line, st["base"]) for line in bank_lines]
    if qr is not None:
        qr_cell = [qr, _p(caption, ParagraphStyle("c", parent=st["small"], alignment=TA_CENTER))]
        bank_and_qr = Table([[bank_block, qr_cell]], colWidths=[left_w - 10 - 28 * mm, 28 * mm])
        bank_and_qr.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ]))
    else:
        bank_and_qr = bank_block

    left = [
        _p("Amount in Words", st["label"]),
        _p(amount_in_words(sale.total_amount), st["bold"]),
        Spacer(1, 6),
        bank_and_qr,
    ]

    total_rows = [("Taxable Amount", _rs(sale.taxable_amount))]
    if sale.cgst_amount:
        total_rows.append(("CGST", _rs(sale.cgst_amount)))
        total_rows.append(("SGST", _rs(sale.sgst_amount)))
    if sale.igst_amount:
        total_rows.append(("IGST", _rs(sale.igst_amount)))
    if sale.round_off:
        total_rows.append(("Round Off", f"{sale.round_off:+.2f}"))
    grand_index = len(total_rows)
    total_rows.append(("Invoice Total (Rs.)", _rs(sale.total_amount)))
    # What the party pays US against this invoice: the invoice total, less the
    # freight balance they pay the driver for us (or plus our advance when the
    # freight is theirs). Cash discount and brokerage are settled later and
    # belong on the settlement statement, not on the invoice.
    from ..services.sale_service import settlement as _settlement

    figures = _settlement(sale)
    you_pay_driver = max(figures["freight_total"] - figures["freight_paid_by_us"], Decimal("0"))
    payable = Decimal(sale.total_amount or 0)
    if sale.freight_borne_by == "us" and you_pay_driver:
        total_rows.append(("Less: freight you pay the driver", "- " + _rs(you_pay_driver)))
        payable -= you_pay_driver
    elif sale.freight_borne_by == "customer" and figures["freight_paid_by_us"]:
        total_rows.append(("Add: freight advance paid by us", "+ " + _rs(figures["freight_paid_by_us"])))
        payable += figures["freight_paid_by_us"]
    if payable != Decimal(sale.total_amount or 0):
        total_rows.append(("Payable to us (Rs.)", _rs(payable)))
    total_rows.append(("Received", _rs(status["paid"])))
    total_rows.append(("Balance Due (Rs.)", _rs(max(payable - status["paid"], Decimal("0")))))

    totals = Table(
        [[_p(k, st["bold"] if i in (grand_index, len(total_rows) - 1) else st["base"]),
          _p(v, st["right_bold"] if i in (grand_index, len(total_rows) - 1) else st["right"])]
         for i, (k, v) in enumerate(total_rows)],
        colWidths=[right_w * 0.55, right_w * 0.45],
    )
    totals.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LINEABOVE", (0, grand_index), (-1, grand_index), 0.8, BORDER),
        ("LINEBELOW", (0, grand_index), (-1, grand_index), 0.8, BORDER),
        ("BACKGROUND", (0, grand_index), (-1, grand_index), SHADE),
    ]))

    summary = _box([[left, totals]], [left_w, right_w],
                   extra=[("RIGHTPADDING", (1, 0), (1, 0), 0), ("LEFTPADDING", (1, 0), (1, 0), 0),
                          ("TOPPADDING", (1, 0), (1, 0), 0)])

    bottom = [summary]

    # The broker is internal and is never printed on the customer's invoice.

    # ---- terms | signature -------------------------------------------------
    if (company.invoice_terms or "").strip():
        terms = [line.strip() for line in company.invoice_terms.splitlines() if line.strip()]
    else:
        terms = [f"{i}. {t}" for i, t in enumerate(DEFAULT_TERMS, start=1)]

    terms_block = [_p("Terms and Conditions", st["label"]), _p("E. & O.E.", st["small"])]
    terms_block += [_p(t, st["small"]) for t in terms]
    if sale.notes:
        terms_block += [Spacer(1, 4), _p("Note: " + sale.notes, st["small"])]

    sign_block = [
        _p(f"For {company.company_name}", st["right_bold"]),
        Spacer(1, 16 * mm),
        _p("Authorised Signatory", st["right"]),
    ]
    bottom.append(_box([[terms_block, sign_block]], [WIDTH * 0.62, WIDTH * 0.38]))

    # Totals, bank, terms and signature always stay together on one page.
    story.append(KeepTogether(bottom))

    # ---- page furniture ----------------------------------------------------
    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(colors.HexColor("#6b7280"))
        canvas.drawString(MARGIN, MARGIN / 2, f"{company.company_name} · {sale.invoice_no}")
        canvas.drawRightString(PAGE_W - MARGIN, MARGIN / 2, f"Page {doc.page}")
        canvas.drawCentredString(PAGE_W / 2, MARGIN / 2, "This is a computer generated invoice.")
        canvas.restoreState()

    out = BytesIO()
    doc = SimpleDocTemplate(
        out,
        pagesize=A4,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=MARGIN,
        bottomMargin=MARGIN,
        title=f"Invoice {sale.invoice_no}",
        author=company.company_name,
        subject=f"Invoice to {sale.customer_name}",
    )
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return out.getvalue()


@login_required
def sale_invoice_pdf(request, sale_id):
    company = company_of(request)
    sale = tenant_object_or_404(Sale.objects.select_related("customer"), request, sale_id)

    pdf = build_invoice_pdf(company, sale)

    response = HttpResponse(pdf, content_type="application/pdf")
    # inline: opens in the browser's PDF viewer; ?download=1 saves the file.
    disposition = "attachment" if request.GET.get("download") else "inline"
    response["Content-Disposition"] = f'{disposition}; filename="Invoice_{sale.invoice_no}.pdf"'
    return response


def build_statement_pdf(company, sale):
    """
    The settlement statement for the party after unloading: weight sent and
    received, value on the received weight, cash discount, brokerage and
    freight cuts, what is due, and what has been received so far.
    """
    from ..services.sale_service import settlement

    st = _styles()
    figures = settlement(sale)
    status = sale_payment_status(company, sale)
    story = []

    story.append(_box(
        [[_p("SETTLEMENT STATEMENT", st["title"])]], [WIDTH],
        extra=[("VALIGN", (0, 0), (-1, -1), "MIDDLE")],
    ))

    address = ", ".join(p.strip() for p in [company.address, company.city, company.state, company.pincode] if p and p.strip())
    seller = [_p(company.company_name, st["company"])]
    if address:
        seller.append(_p(address, st["center"]))
    if company.gst_number:
        seller.append(_p(f"GSTIN: {company.gst_number}", st["center"]))
    story.append(_box([[seller]], [WIDTH]))

    half = WIDTH / 2
    left = [
        _p("PARTY", st["label"]), _p(sale.customer_name, st["bold"]),
        _p(sale.billing_address or "", st["base"]),
    ]
    if sale.customer_gst:
        left.append(_p(f"GSTIN: {sale.customer_gst}", st["base"]))
    right = [
        _p("TRUCK", st["label"]),
        _p(f"Invoice {sale.invoice_no} dated {sale.sale_date:%d-%m-%Y}", st["base"]),
        _p(f"Vehicle: {sale.vehicle_number or '-'}", st["base"]),
        _p(f"Unloaded: {sale.unload_date:%d-%m-%Y}" if sale.unload_date else "Unloaded: not yet", st["base"]),
    ]
    if sale.broker_id:
        right.append(_p(f"Broker: {sale.broker.broker_name}", st["base"]))
    story.append(_box([[left, right]], [half, half]))

    lines = [
        ("Weight sent", f"{figures['dispatched_kg']} kg"),
        ("Weight received", f"{figures['received_kg']} kg" + ("" if figures["unloaded"] else " (expected)")),
        ("Short in transit", f"{figures['weight_loss_kg']} kg"),
        ("Invoice total (Rs.)", _rs(sale.total_amount)),
        ("Value on received weight (Rs.)", _rs(figures["party_value"])),
    ]
    if figures["cash_discount"]:
        lines.append((f"Less: cash discount {sale.cash_discount_percent}%", "- " + _rs(figures["cash_discount"])))
    if figures["brokerage_cut"]:
        lines.append(("Less: brokerage (paid by party to broker)", "- " + _rs(figures["brokerage_cut"])))
    if figures["other_deductions"]:
        note = f" ({sale.other_deductions_note})" if sale.other_deductions_note else ""
        lines.append((f"Less: other deductions{note}", "- " + _rs(figures["other_deductions"])))
    lines.append(("Goods payable (Rs.)", _rs(figures["goods_payable"])))
    if figures["freight_adjustment"] < 0:
        lines.append(("Less: freight paid by party to the driver", "- " + _rs(figures["freight_paid_by_party"])))
    elif figures["freight_adjustment"] > 0:
        lines.append(("Add: freight advance paid by us", "+ " + _rs(figures["freight_adjustment"])))
    total_index = len(lines)
    lines.append(("NET AMOUNT PAYABLE (Rs.)", _rs(figures["net_receivable"])))
    lines.append(("Received so far", _rs(status["paid"])))
    lines.append(("BALANCE DUE (Rs.)", _rs(status["due"])))

    table = Table(
        [[_p(k, st["bold"] if i in (total_index, len(lines) - 1) else st["base"]),
          _p(v, st["right_bold"] if i in (total_index, len(lines) - 1) else st["right"])]
         for i, (k, v) in enumerate(lines)],
        colWidths=[WIDTH * 0.68, WIDTH * 0.32],
    )
    table.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.8, BORDER),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, GRID),
        ("BACKGROUND", (0, total_index), (-1, total_index), SHADE),
        ("BACKGROUND", (0, -1), (-1, -1), SHADE),
        ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(table)
    story.append(Spacer(1, 6))
    story.append(_p("Amount in words: " + amount_in_words(figures["net_receivable"]), st["bold"]))

    bank = [f"A/C Name: {company.bank_account_name or company.company_name}"]
    if company.bank_account_no:
        bank.append(f"A/C No: {company.bank_account_no}")
    if company.bank_name:
        bank.append(f"Bank: {company.bank_name}" + (f", {company.bank_branch}" if company.bank_branch else ""))
    if company.bank_ifsc:
        bank.append(f"IFSC: {company.bank_ifsc}")
    if company.upi_id:
        bank.append(f"UPI: {company.upi_id}")
    story.append(Spacer(1, 8))
    story.append(_box(
        [[[_p("Pay to", st["label"])] + [_p(line, st["base"]) for line in bank],
          [_p(f"For {company.company_name}", st["right_bold"]), Spacer(1, 14 * mm),
           _p("Authorised Signatory", st["right"])]]],
        [WIDTH * 0.6, WIDTH * 0.4],
    ))

    out = BytesIO()
    doc = SimpleDocTemplate(out, pagesize=A4, leftMargin=MARGIN, rightMargin=MARGIN,
                            topMargin=MARGIN, bottomMargin=MARGIN,
                            title=f"Settlement {sale.invoice_no}", author=company.company_name)
    doc.build(story)
    return out.getvalue()


@login_required
def sale_statement_pdf(request, sale_id):
    company = company_of(request)
    sale = tenant_object_or_404(Sale.objects.select_related("customer", "broker"), request, sale_id)
    response = HttpResponse(build_statement_pdf(company, sale), content_type="application/pdf")
    disposition = "attachment" if request.GET.get("download") else "inline"
    response["Content-Disposition"] = f'{disposition}; filename="Settlement_{sale.invoice_no}.pdf"'
    return response
