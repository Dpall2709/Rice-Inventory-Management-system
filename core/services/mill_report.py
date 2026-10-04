"""
The supplier statement, as a PDF and as an Excel workbook.

Both are built from the same ledger data as the screen, so a mill, an
accountant and the owner all see identical numbers.

The PDF is meant to be sent to the mill for confirmation ("this is what my
books say"), so it is laid out like a statement of account: who it is from,
who it is for, a summary, then bill-by-bill with what is still due, then the
payments, and finally what remains.
"""

from datetime import datetime
from decimal import Decimal
from io import BytesIO

from django.http import HttpResponse
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from core.services.ledger import mill_statement

INDIGO = colors.HexColor("#4f46e5")
INK = colors.HexColor("#0f172a")
MUTED = colors.HexColor("#64748b")
LINE = colors.HexColor("#e2e8f0")
BAND = colors.HexColor("#f8fafc")
GREEN = colors.HexColor("#15803d")
RED = colors.HexColor("#b91c1c")


def money(value):
    """1234567.5 -> '12,34,567.50' (Indian grouping)."""
    value = Decimal(value or 0)
    negative = value < 0
    whole, _, paise = f"{abs(value):.2f}".partition(".")

    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        whole = ",".join(parts + [tail])

    return ("-" if negative else "") + f"{whole}.{paise}"


def statement_context(company, mill):
    """Everything both exports need, in one place."""
    data = mill_statement(company, mill)

    bags = 0
    kg = Decimal("0")
    for row in data["rows"]:
        for item in row["purchase"].purchaseitem_set.all():
            bags += item.bag_count or 0
            kg += Decimal(item.total_kg or 0)

    data["total_bags"] = bags
    data["total_kg"] = kg
    data["company"] = company
    data["generated_at"] = datetime.now()
    return data


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------

def build_pdf(company, mill):
    data = statement_context(company, mill)

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=14 * mm,
        rightMargin=14 * mm,
        topMargin=14 * mm,
        bottomMargin=16 * mm,
        title=f"Statement - {mill.mill_name}",
        author=company.company_name,
    )

    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=styles["Heading1"], fontSize=16, textColor=INK, spaceAfter=2)
    small = ParagraphStyle("small", parent=styles["Normal"], fontSize=8.5, textColor=MUTED)
    label = ParagraphStyle("label", parent=styles["Normal"], fontSize=7.5, textColor=MUTED)
    cell = ParagraphStyle("cell", parent=styles["Normal"], fontSize=8.5, textColor=INK)
    tight = ParagraphStyle("tight", parent=styles["Normal"], fontSize=7.5, textColor=INK, leading=9.5)
    section = ParagraphStyle(
        "section", parent=styles["Heading2"], fontSize=11, textColor=INDIGO, spaceBefore=10, spaceAfter=4
    )

    story = []

    # ---------------- header: who is sending this, and to whom ----------------
    address = ", ".join(x for x in [company.address, company.city, company.state, company.pincode] if x)

    seller = [
        Paragraph(f"<b>{company.company_name}</b>", cell),
        Paragraph(address or "&nbsp;", small),
        Paragraph(
            " · ".join(x for x in [company.mobile, company.email] if x) or "&nbsp;", small
        ),
        Paragraph(f"GSTIN: {company.gst_number}" if company.gst_number else "&nbsp;", small),
    ]

    title = [
        Paragraph("SUPPLIER STATEMENT", h1),
        Paragraph(
            f"{mill.mill_name}"
            + (f" · {mill.owner_name}" if mill.owner_name else ""),
            cell,
        ),
        Paragraph(
            " · ".join(x for x in [mill.mobile, mill.city, mill.gst_number] if x) or "&nbsp;",
            small,
        ),
        Paragraph(f"Generated {data['generated_at']:%d %b %Y, %H:%M}", small),
    ]

    story.append(Table(
        [[seller, title]],
        colWidths=[90 * mm, 92 * mm],
        style=TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("ALIGN", (1, 0), (1, 0), "RIGHT"),
            ("LINEBELOW", (0, 0), (-1, 0), 1, INDIGO),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
        ]),
    ))
    story.append(Spacer(1, 8))

    # ---------------- the four numbers that matter ----------------
    def tile(name, value, colour=INK):
        return [
            Paragraph(name.upper(), label),
            Paragraph(f"<font color='{colour}'><b>{value}</b></font>", ParagraphStyle(
                "tilev", parent=styles["Normal"], fontSize=12.5, textColor=colour
            )),
        ]

    story.append(Table(
        [[
            tile("Total purchased", f"Rs {money(data['total_purchased'])}"),
            tile("Total paid", f"Rs {money(data['total_paid'])}", GREEN),
            tile("Balance due", f"Rs {money(data['total_due'])}", RED if data["total_due"] > 0 else GREEN),
            tile("Stock bought", f"{data['total_bags']} bags / {money(data['total_kg'])} kg"),
        ]],
        colWidths=[45.5 * mm] * 4,   # = 182mm
        style=TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("BACKGROUND", (0, 0), (-1, -1), BAND),
            ("BOX", (0, 0), (-1, -1), 0.5, LINE),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, LINE),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 7),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ]),
    ))

    if data["opening"]:
        story.append(Spacer(1, 5))
        story.append(Paragraph(
            f"Opening balance {money(data['opening'])}"
            f" · settled {money(data['opening_paid'])}"
            f" · still due {money(data['opening_due'])}",
            small,
        ))

    # ---------------- bill by bill ----------------
    story.append(Paragraph("Purchase bills", section))

    head = ["Date", "Bill no", "Rice bought", "Bags", "Qty (kg)", "Rate/kg", "Bill total", "Paid", "Due"]
    rows = [head]

    for row in data["rows"]:
        purchase = row["purchase"]
        items = list(purchase.purchaseitem_set.all())

        description = "<br/>".join(
            f"{item.product.rice_name} · {item.bag_count}×{item.bag_weight}kg @ Rs {money(item.purchase_price)}"
            for item in items
        ) or "-"

        bags = sum(item.bag_count or 0 for item in items)
        kg = sum(Decimal(item.total_kg or 0) for item in items)
        rates = {money(item.purchase_price) for item in items}

        rows.append([
            Paragraph(f"{purchase.purchase_date:%d-%m-%Y}", tight),
            Paragraph(f"<b>{purchase.invoice_no}</b><br/><font size=6.5 color='#64748b'>{purchase.purchase_ref or ''}</font>", tight),
            Paragraph(description, tight),
            str(bags),
            money(kg),
            " / ".join(sorted(rates)) if rates else "-",
            money(row["total"]),
            money(row["paid"]),
            money(row["due"]),
        ])

    rows.append([
        "", Paragraph("<b>Total</b>", tight), "",
        str(data["total_bags"]), money(data["total_kg"]), "",
        money(data["total_purchased"]),
        money(data["total_paid_on_bills"]),
        money(sum(r["due"] for r in data["rows"])),
    ])

    bills = Table(
        rows,
        colWidths=[19*mm, 21*mm, 41*mm, 10*mm, 16*mm, 13*mm, 21*mm, 21*mm, 20*mm],   # = 182mm
        repeatRows=1,
    )
    bills.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), INDIGO),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 7.5),
        ("ALIGN", (3, 0), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.4, LINE),
        ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, BAND]),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#eef2ff")),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(bills)

    # ---------------- payments ----------------
    story.append(Paragraph("Payments made", section))

    if data["payments"]:
        pay_rows = [["Date", "Mode", "Against bill", "Note", "Amount"]]
        for payment in data["payments"]:
            pay_rows.append([
                f"{payment.payment_date:%d-%m-%Y}",
                payment.payment_mode or "-",
                payment.purchase.invoice_no if payment.purchase_id else "On account",
                Paragraph(payment.notes or "-", cell),
                money(payment.amount),
            ])
        pay_rows.append(["", "", "", Paragraph("<b>Total paid</b>", cell), money(data["total_paid"])])

        payments = Table(
            pay_rows,
            colWidths=[21*mm, 23*mm, 30*mm, 84*mm, 24*mm],   # = 182mm
            repeatRows=1,
        )
        payments.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f766e")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 7.5),
            ("ALIGN", (4, 0), (4, -1), "RIGHT"),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("GRID", (0, 0), (-1, -1), 0.4, LINE),
            ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, BAND]),
            ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#ecfdf5")),
            ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        story.append(payments)
    else:
        story.append(Paragraph("No payments recorded yet.", small))

    # ---------------- account history, the way a khata reads ----------------
    story.append(Paragraph("Account history", section))

    hist_rows = [["Date", "Particulars", "Bill", "Paid", "Balance"]]
    for entry in data["history"]:
        balance = entry["balance"]
        if balance < 0:
            balance_text = f"{money(-balance)} adv"
        elif balance > 0:
            balance_text = money(balance)
        else:
            balance_text = "Nil"

        hist_rows.append([
            f"{entry['date']:%d-%m-%Y}" if entry["date"] else "-",
            Paragraph(entry["particulars"], tight),
            money(entry["debit"]) if entry["debit"] else "",
            money(entry["credit"]) if entry["credit"] else "",
            balance_text,
        ])

    history = Table(
        hist_rows,
        colWidths=[21*mm, 85*mm, 25*mm, 25*mm, 26*mm],   # = 182mm
        repeatRows=1,
    )
    history.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), INK),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 7.5),
        ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.4, LINE),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, BAND]),
        ("TEXTCOLOR", (3, 1), (3, -1), GREEN),
        ("FONTNAME", (4, 1), (4, -1), "Helvetica-Bold"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(history)

    # ---------------- the closing line ----------------
    closing = [
        ["Total purchased", f"Rs {money(data['total_purchased'])}"],
        ["Opening balance", f"Rs {money(data['opening'])}"],
        ["Total paid", f"- Rs {money(data['total_paid'])}"],
        ["BALANCE DUE", f"Rs {money(data['total_due'])}"],
    ]
    if data["advance"]:
        closing[-1] = ["ADVANCE WITH MILL", f"Rs {money(data['advance'])}"]

    summary = Table(closing, colWidths=[45 * mm, 40 * mm], hAlign="RIGHT")
    summary.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("LINEABOVE", (0, -1), (-1, -1), 0.8, INK),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("TEXTCOLOR", (0, -1), (-1, -1), RED if data["total_due"] > 0 and not data["advance"] else GREEN),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(Spacer(1, 10))
    story.append(KeepTogether(summary))

    story.append(Spacer(1, 12))
    story.append(Paragraph(
        "Please check this statement against your books and tell us about any difference. "
        "Computer generated - no signature required.",
        small,
    ))

    def footer(canvas_obj, document):
        canvas_obj.saveState()
        canvas_obj.setFont("Helvetica", 7.5)
        canvas_obj.setFillColor(MUTED)
        canvas_obj.drawString(14 * mm, 10 * mm, f"{company.company_name} · statement for {mill.mill_name}")
        canvas_obj.drawRightString(A4[0] - 14 * mm, 10 * mm, f"Page {document.page}")
        canvas_obj.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)

    pdf = buffer.getvalue()
    buffer.close()

    response = HttpResponse(pdf, content_type="application/pdf")
    filename = f"statement-{mill.mill_name.replace(' ', '-').lower()}-{data['generated_at']:%Y%m%d}.pdf"
    response["Content-Disposition"] = f'inline; filename="{filename}"'
    return response


# ---------------------------------------------------------------------------
# Excel
# ---------------------------------------------------------------------------

HEADER_FILL = PatternFill("solid", fgColor="4F46E5")
TOTAL_FILL = PatternFill("solid", fgColor="EEF2FF")
BAND_FILL = PatternFill("solid", fgColor="F8FAFC")
THIN = Side(style="thin", color="E2E8F0")
BOX = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)

RUPEES = '#,##,##0.00'          # Indian digit grouping
DATE_FMT = "DD-MM-YYYY"


def _write_header(sheet, headers, row=1):
    for column, title in enumerate(headers, start=1):
        cell = sheet.cell(row=row, column=column, value=title)
        cell.font = Font(bold=True, color="FFFFFF", size=10)
        cell.fill = HEADER_FILL
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = BOX
    sheet.row_dimensions[row].height = 26


def _fit_columns(sheet, widths):
    for index, width in enumerate(widths, start=1):
        sheet.column_dimensions[get_column_letter(index)].width = width


def build_excel(company, mill):
    data = statement_context(company, mill)
    workbook = Workbook()

    # ---------------- sheet 1: the summary a person reads first -------------
    summary = workbook.active
    summary.title = "Summary"
    summary.sheet_view.showGridLines = False

    summary["A1"] = company.company_name
    summary["A1"].font = Font(bold=True, size=15, color="0F172A")
    summary["A2"] = "Supplier statement"
    summary["A2"].font = Font(size=11, color="64748B")

    facts = [
        ("Supplier", mill.mill_name),
        ("Owner", mill.owner_name or "-"),
        ("Mobile", mill.mobile or "-"),
        ("GST number", mill.gst_number or "-"),
        ("City", mill.city or "-"),
        ("", ""),
        ("Opening balance", data["opening"]),
        ("Total purchased", data["total_purchased"]),
        ("Total paid", data["total_paid"]),
        ("Balance due", data["total_due"]),
        ("Advance with mill", data["advance"]),
        ("", ""),
        ("Bills", len(data["rows"])),
        ("Bags bought", data["total_bags"]),
        ("Quantity (kg)", data["total_kg"]),
        ("", ""),
        ("Generated", data["generated_at"].strftime("%d-%m-%Y %H:%M")),
    ]

    for index, (name, value) in enumerate(facts, start=4):
        if not name:
            continue
        label = summary.cell(row=index, column=1, value=name)
        label.font = Font(bold=True, size=10, color="475569")

        cell = summary.cell(row=index, column=2, value=value)
        if isinstance(value, Decimal):
            cell.number_format = RUPEES
        cell.font = Font(size=11)

        if name == "Balance due":
            cell.font = Font(bold=True, size=13, color="B91C1C" if data["total_due"] > 0 else "15803D")
            label.font = Font(bold=True, size=11)

    _fit_columns(summary, [24, 30])

    # ---------------- sheet 2: the account in date order -------------------
    ledger = workbook.create_sheet("Ledger")
    ledger.sheet_view.showGridLines = False

    _write_header(ledger, ["Date", "Particulars", "Reference", "Bill (you owe)", "Paid", "Balance", "Note"])

    line = 2
    for entry in data["history"]:
        balance = entry["balance"]
        values = [
            entry["date"],
            entry["particulars"],
            entry["reference"] or "",
            entry["debit"] or None,
            entry["credit"] or None,
            balance,
            "advance with mill" if balance < 0 else ("settled" if balance == 0 else ""),
        ]
        for column, value in enumerate(values, start=1):
            cell = ledger.cell(row=line, column=column, value=value)
            cell.border = BOX
            if line % 2 == 0:
                cell.fill = BAND_FILL
            if column == 1:
                cell.number_format = DATE_FMT
            if column in (4, 5, 6):
                cell.number_format = RUPEES
            if column == 5 and value:
                cell.font = Font(color="15803D")
            if column == 6:
                cell.font = Font(bold=True, color="B91C1C" if balance > 0 else "15803D")
        line += 1

    ledger.freeze_panes = "A2"
    ledger.auto_filter.ref = f"A1:G{max(line - 1, 1)}"
    _fit_columns(ledger, [12, 46, 22, 16, 16, 16, 18])

    # ---------------- sheet 3: bill by bill --------------------------------
    bills = workbook.create_sheet("Purchase bills")
    bills.sheet_view.showGridLines = False

    headers = [
        "Date", "Bill no", "Our ref", "GST type", "Rice", "Bag wt (kg)", "Bags",
        "Quantity (kg)", "Rate / kg", "Taxable", "GST", "Bill total", "Paid", "Due", "Status",
    ]
    _write_header(bills, headers)

    row_number = 2
    for row in data["rows"]:
        purchase = row["purchase"]
        items = list(purchase.purchaseitem_set.all())
        first = True

        for item in items or [None]:
            values = [
                purchase.purchase_date,
                purchase.invoice_no,
                purchase.purchase_ref or "",
                purchase.get_tax_type_display(),
                item.product.rice_name if item else "-",
                item.bag_weight if item else None,
                item.bag_count if item else None,
                Decimal(item.total_kg or 0) if item else None,
                Decimal(item.purchase_price or 0) if item else None,
                Decimal(item.taxable_amount or 0) if item else None,
                Decimal(item.gst_amount or 0) if item else None,
                row["total"] if first else None,
                row["paid"] if first else None,
                row["due"] if first else None,
                row["status"].title() if first else None,
            ]

            for column, value in enumerate(values, start=1):
                cell = bills.cell(row=row_number, column=column, value=value)
                cell.border = BOX
                if row_number % 2 == 0:
                    cell.fill = BAND_FILL
                if column == 1:
                    cell.number_format = DATE_FMT
                if column in (8, 9, 10, 11, 12, 13, 14):
                    cell.number_format = RUPEES
                if column in (12, 13, 14):
                    cell.font = Font(bold=first, size=10)
                if column == 14 and first and row["due"] > 0:
                    cell.font = Font(bold=True, color="B91C1C")

            row_number += 1
            first = False

    # a totals line people can trust
    totals = ["", "TOTAL", "", "", "", "", data["total_bags"], data["total_kg"], "", "", "",
              data["total_purchased"], data["total_paid_on_bills"],
              sum(r["due"] for r in data["rows"]), ""]
    for column, value in enumerate(totals, start=1):
        cell = bills.cell(row=row_number, column=column, value=value)
        cell.font = Font(bold=True, size=10)
        cell.fill = TOTAL_FILL
        cell.border = BOX
        if column in (8, 12, 13, 14):
            cell.number_format = RUPEES

    bills.freeze_panes = "A2"
    bills.auto_filter.ref = f"A1:O{row_number}"
    _fit_columns(bills, [12, 14, 20, 18, 22, 11, 8, 14, 11, 14, 12, 14, 14, 14, 10])

    # ---------------- sheet 4: payments ------------------------------------
    payments = workbook.create_sheet("Payments")
    payments.sheet_view.showGridLines = False

    _write_header(payments, ["Date", "Mode", "Against bill", "Note", "Amount"])

    line = 2
    for payment in data["payments"]:
        values = [
            payment.payment_date,
            payment.payment_mode or "-",
            payment.purchase.invoice_no if payment.purchase_id else "On account",
            payment.notes or "",
            Decimal(payment.amount or 0),
        ]
        for column, value in enumerate(values, start=1):
            cell = payments.cell(row=line, column=column, value=value)
            cell.border = BOX
            if line % 2 == 0:
                cell.fill = BAND_FILL
            if column == 1:
                cell.number_format = DATE_FMT
            if column == 5:
                cell.number_format = RUPEES
        line += 1

    for column, value in enumerate(["", "", "", "TOTAL PAID", data["total_paid"]], start=1):
        cell = payments.cell(row=line, column=column, value=value)
        cell.font = Font(bold=True)
        cell.fill = TOTAL_FILL
        cell.border = BOX
        if column == 5:
            cell.number_format = RUPEES

    payments.freeze_panes = "A2"
    _fit_columns(payments, [12, 16, 20, 46, 16])

    buffer = BytesIO()
    workbook.save(buffer)
    buffer.seek(0)

    response = HttpResponse(
        buffer.read(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    filename = f"statement-{mill.mill_name.replace(' ', '-').lower()}-{data['generated_at']:%Y%m%d}.xlsx"
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response
