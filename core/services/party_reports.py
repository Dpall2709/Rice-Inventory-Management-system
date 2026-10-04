"""
Customer and broker statements for a period, as PDF and Excel.

    period      ?month=2026-09            a whole month
                ?from=2026-09-01&to=...   any range (default: this month)

A statement for a period opens with the balance carried forward from before
it, lists every entry inside it with a running balance, and closes with the
balance at its end - the way a party's khata is copied out for them.

By default a statement is the copy you SEND to the party: it never shows
your profit. Pass internal=True for your own copy with the profit column.

Customer statement   invoices the customer pays you for, receipts, balance;
                     trucks bought through a broker are listed for reference.
Broker statement     trucks he brought in the period with CD, brokerage and
                     your profit; what he owes you for trucks he collects on
                     (with receipts); and the commission account.
"""

import calendar
from datetime import date
from decimal import Decimal
from io import BytesIO

from django.http import HttpResponse
from django.utils import timezone
from django.utils.translation import gettext as _

from core.services.customer_ledger import broker_collections, broker_statement, customer_statement
from core.services.sale_service import money, sale_profit, settlement

ZERO = Decimal("0")


# --------------------------------------------------------------------------
# Period
# --------------------------------------------------------------------------

def parse_period(params, today=None):
    """(start, end, label) from ?month=YYYY-MM or ?from=&to=; default every date so far."""
    today = today or timezone.localdate()

    month = (params.get("month") or "").strip()
    if month:
        try:
            year, mon = (int(x) for x in month.split("-")[:2])
            last = calendar.monthrange(year, mon)[1]
            start, end = date(year, mon, 1), date(year, mon, last)
            return start, end, start.strftime("%B %Y")
        except (ValueError, TypeError):
            pass

    def _date(value):
        try:
            return date.fromisoformat(value) if value else None
        except ValueError:
            return None

    start = _date(params.get("from"))
    end = _date(params.get("to"))
    if not start and not end:
        # Nothing chosen: the whole account. Defaulting to this month made
        # downloads look empty whenever the trucks were from earlier months.
        return date(2000, 1, 1), today, str(_("All dates up to %(day)s") % {"day": f"{today:%d %b %Y}"})
    start = start or date(2000, 1, 1)
    end = end or today
    if start > end:
        start, end = end, start
    return start, end, f"{start:%d %b %Y} - {end:%d %b %Y}"


def _slice(history, start, end):
    """Opening balance before `start`, the entries in the period, closing balance."""
    opening = ZERO
    entries = []
    closing = ZERO
    for entry in history:
        when = entry.get("date")
        if when is None or when < start:
            opening = entry["balance"]
            closing = entry["balance"]
            continue
        if when > end:
            break
        entries.append(entry)
        closing = entry["balance"]
    return opening, entries, closing


# --------------------------------------------------------------------------
# Data
# --------------------------------------------------------------------------

def customer_report(company, customer, start, end):
    statement = customer_statement(company, customer)
    opening, entries, closing = _slice(statement["history"], start, end)

    invoices = []
    for row in statement["rows"]:
        sale = row["sale"]
        if start <= sale.sale_date <= end:
            figures = settlement(sale)
            invoices.append({
                "sale": sale,
                "figures": figures,
                "total": row["total"],
                "paid": row["paid"],
                "due": row["due"],
                "profit": sale_profit(sale)["profit"],
            })

    broker_sales = []
    for sale in statement["broker_sales"]:
        if start <= sale.sale_date <= end:
            broker_sales.append({"sale": sale, "figures": settlement(sale), "profit": sale_profit(sale)["profit"]})

    return {
        "kind": "customer",
        "party": customer,
        "name": customer.customer_name,
        "opening": opening,
        "entries": entries,
        "closing": closing,
        "billed": sum((e["debit"] for e in entries), ZERO),
        "received": sum((e["credit"] for e in entries), ZERO),
        "invoices": invoices,
        "broker_sales": broker_sales,
        "profit": sum((i["profit"] for i in invoices + broker_sales if i["profit"] is not None), ZERO),
    }


def broker_report(company, broker, start, end):
    statement = broker_statement(company, broker)
    collections = statement["collections"]
    opening, entries, closing = _slice(collections["history"], start, end)
    c_opening, c_entries, c_closing = _slice(statement["history"], start, end)

    trucks = []
    for sale in sorted(statement["sales"], key=lambda s: (s.sale_date, s.id)):
        if not (start <= sale.sale_date <= end):
            continue
        figures = settlement(sale)
        trucks.append({
            "sale": sale,
            "figures": figures,
            "profit": sale_profit(sale)["profit"],
        })

    return {
        "kind": "broker",
        "party": broker,
        "name": broker.broker_name,
        # money he owes you for trucks he collects on
        "opening": opening,
        "entries": entries,
        "closing": closing,
        "billed": sum((e["debit"] for e in entries), ZERO),
        "received": sum((e["credit"] for e in entries), ZERO),
        # commission you owe him (when you pay him yourself)
        "commission_opening": c_opening,
        "commission_entries": c_entries,
        "commission_closing": c_closing,
        "trucks": trucks,
        "weight_kg": money(sum((t["figures"]["received_kg"] for t in trucks), ZERO)),
        "cash_discount": money(sum((t["figures"]["cash_discount"] for t in trucks), ZERO)),
        "brokerage": money(sum((t["figures"]["commission"] for t in trucks), ZERO)),
        "profit": money(sum((t["profit"] for t in trucks if t["profit"] is not None), ZERO)),
    }


# --------------------------------------------------------------------------
# Excel
# --------------------------------------------------------------------------

def _xlsx_response(wb, filename):
    response = HttpResponse(content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    wb.save(response)
    return response


def report_excel(company, report, label, internal=False):
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    from openpyxl.utils import get_column_letter

    head_fill = PatternFill("solid", fgColor="1F4E3D")
    wb = Workbook()

    def sheet(title, first=False):
        ws = wb.active if first else wb.create_sheet()
        ws.title = title[:31]
        ws.append([company.company_name])
        ws["A1"].font = Font(bold=True, size=14)
        heading = _("Customer statement") if report["kind"] == "customer" else _("Broker statement")
        ws.append([f"{heading}: {report['name']}"])
        ws.append([_("Period") + ": " + label])
        ws.append([])
        return ws

    def header(ws, cells):
        ws.append(cells)
        for cell in ws[ws.max_row]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = head_fill

    def num(value):
        return float(value) if value is not None else None

    def finish(ws, widths):
        for index, width in enumerate(widths, start=1):
            ws.column_dimensions[get_column_letter(index)].width = width
        for row in ws.iter_rows(min_row=5):
            for cell in row:
                if isinstance(cell.value, float):
                    cell.number_format = "#,##0.00"
                elif hasattr(cell.value, "year"):
                    cell.number_format = "DD-MMM-YYYY"

    # ---- account statement (running balance) ----
    title = _("Account") if report["kind"] == "customer" else _("He owes you")
    ws = sheet(title, first=True)
    header(ws, [_("Date"), _("Particulars"), _("Billed"), _("Received"), _("Balance")])
    ws.append([None, _("Balance brought forward"), None, None, num(report["opening"])])
    for entry in report["entries"]:
        ws.append([entry["date"], str(entry["particulars"]), num(entry["debit"]) or None,
                   num(entry["credit"]) or None, num(entry["balance"])])
    if not report["entries"]:
        ws.append([None, _("No bills or payments in this period.")])
    ws.append([None, _("Closing balance"), num(report["billed"]), num(report["received"]), num(report["closing"])])
    for cell in ws[ws.max_row]:
        cell.font = Font(bold=True)
    if report["kind"] == "customer" and report["broker_sales"]:
        # These trucks are paid to us through the broker, so they are on his
        # account, not this one - list them so the sheet is never blank.
        ws.append([])
        ws.append([None, _("Trucks paid through the broker (on the broker's account)")])
        ws.cell(row=ws.max_row, column=2).font = Font(bold=True)
        for row in report["broker_sales"]:
            sale = row["sale"]
            ws.append([sale.sale_date, f"{sale.invoice_no} · {sale.vehicle_number or ''} · "
                       f"{_('Broker')}: {sale.broker.broker_name if sale.broker else ''}",
                       num(row["figures"]["net_receivable"])])
    finish(ws, [14, 52, 16, 16, 16])

    # ---- trucks / invoices ----
    rows = report["invoices"] + report["broker_sales"] if report["kind"] == "customer" else report["trucks"]
    ws = sheet(_("Trucks"))
    columns = [_("Date"), _("Invoice"), _("Truck no"), _("Customer"), _("Broker"), _("Bags"),
               _("Weight sent (kg)"), _("Unloaded on"), _("Weight received (kg)"), _("Shortage (kg)"),
               _("Invoice total"), _("Cash discount"), _("Brokerage"), _("Party owes")]
    if internal:
        columns.append(_("Profit / loss"))
    header(ws, columns)
    for row in rows:
        sale, f = row["sale"], row["figures"]
        line = [
            sale.sale_date, sale.invoice_no, sale.vehicle_number, sale.customer_name,
            sale.broker.broker_name if sale.broker else "", sale.total_bags,
            num(f["dispatched_kg"]), sale.unload_date, num(f["received_kg"]) if f["unloaded"] else None,
            num(f["weight_loss_kg"]) if f["unloaded"] else None, num(sale.total_amount),
            num(f["cash_discount"]), num(f["commission"]), num(f["net_receivable"]),
        ]
        if internal:
            line.append(num(row["profit"]))
        ws.append(line)
    if internal:
        ws.append([])
        ws.append([_("Total profit")] + [None] * 13 + [num(report["profit"])])
        ws.cell(row=ws.max_row, column=1).font = Font(bold=True)
    finish(ws, [13, 20, 14, 26, 18, 8, 14, 13, 14, 12, 15, 13, 12, 15, 14])

    # ---- broker commission account ----
    if report["kind"] == "broker" and (report["commission_entries"] or report["commission_opening"]):
        ws = sheet(_("Commission"))
        header(ws, [_("Date"), _("Particulars"), _("Earned"), _("Paid"), _("You owe")])
        ws.append([None, _("Balance brought forward"), None, None, num(report["commission_opening"])])
        for entry in report["commission_entries"]:
            ws.append([entry["date"], str(entry["particulars"]), num(entry["credit"]) or None,
                       num(entry["debit"]) or None, num(entry["balance"])])
        ws.append([None, _("Closing balance"), None, None, num(report["commission_closing"])])
        finish(ws, [14, 52, 16, 16, 16])

    safe = "".join(ch for ch in report["name"] if ch.isalnum() or ch in " -_").strip().replace(" ", "_")
    copy = "_internal" if internal else ""
    period = "".join(ch for ch in label if ch.isalnum() or ch == "-")
    return _xlsx_response(wb, f"{report['kind']}_{safe}_{period}{copy}.xlsx")


# --------------------------------------------------------------------------
# PDF
# --------------------------------------------------------------------------

def report_pdf(company, report, label, internal=False):
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    from core.function.sale_invoice_pdf import BORDER, GRID, SHADE, _p, _rs, _styles

    st = _styles()
    page = landscape(A4)
    margin = 12 * mm
    width = page[0] - 2 * margin
    story = []

    heading = "CUSTOMER STATEMENT" if report["kind"] == "customer" else "BROKER STATEMENT"
    story.append(_p(company.company_name, st["company"]))
    address = ", ".join(x.strip() for x in [company.address, company.city, company.state] if x and x.strip())
    if address:
        story.append(_p(address, st["center"]))
    story.append(Spacer(1, 4))
    story.append(Paragraph(f"<b>{heading}</b> - {report['name']}",
                           ParagraphStyle("h", parent=st["title"], alignment=TA_CENTER)))
    story.append(_p(f"Period: {label}" + ("   ·   INTERNAL COPY - NOT FOR SENDING" if internal else ""), st["center"]))
    story.append(Spacer(1, 8))

    def grid(rows, widths, money_cols=(), bold_last=False):
        table = Table(rows, colWidths=widths, repeatRows=1)
        style = [
            ("BOX", (0, 0), (-1, -1), 0.8, BORDER),
            ("INNERGRID", (0, 0), (-1, -1), 0.25, GRID),
            ("BACKGROUND", (0, 0), (-1, 0), SHADE),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 7.5),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ]
        for col in money_cols:
            style.append(("ALIGN", (col, 0), (col, -1), "RIGHT"))
        if bold_last:
            style.append(("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"))
            style.append(("BACKGROUND", (0, -1), (-1, -1), SHADE))
        table.setStyle(TableStyle(style))
        return table

    def amount(value):
        return _rs(value) if value else ""

    # ---- account with running balance ----
    title = "Account" if report["kind"] == "customer" else "Money he owes you (trucks he collects on)"
    story.append(_p(title, st["bold"]))
    rows = [["Date", "Particulars", "Billed", "Received", "Balance"],
            ["", "Balance brought forward", "", "", _rs(report["opening"])]]
    for entry in report["entries"]:
        rows.append([f"{entry['date']:%d-%m-%Y}", Paragraph(str(entry["particulars"]), st["small"]),
                     amount(entry["debit"]), amount(entry["credit"]), _rs(entry["balance"])])
    rows.append(["", "Closing balance", _rs(report["billed"]), _rs(report["received"]), _rs(report["closing"])])
    story.append(grid(rows, [24 * mm, width - 24 * mm - 3 * 34 * mm, 34 * mm, 34 * mm, 34 * mm],
                      money_cols=(2, 3, 4), bold_last=True))
    story.append(Spacer(1, 10))

    # ---- trucks ----
    trucks = report["invoices"] + report["broker_sales"] if report["kind"] == "customer" else report["trucks"]
    if trucks:
        story.append(_p("Trucks in this period", st["bold"]))
        rows = [["Date", "Invoice", "Truck", "Customer" if report["kind"] == "broker" else "Broker",
                 "Bags", "Sent kg", "Unloaded", "Recd kg", "Short kg", "Invoice", "CD", "Brokerage",
                 "Party owes"] + (["Profit"] if internal else [])]
        for row in trucks:
            sale, f = row["sale"], row["figures"]
            other = sale.customer_name if report["kind"] == "broker" else (sale.broker.broker_name if sale.broker else "Direct")
            rows.append([
                f"{sale.sale_date:%d-%m-%Y}", sale.invoice_no, sale.vehicle_number or "-",
                Paragraph(other, st["small"]), str(sale.total_bags), f"{f['dispatched_kg']:.0f}",
                f"{sale.unload_date:%d-%m-%Y}" if sale.unload_date else "-",
                f"{f['received_kg']:.0f}" if f["unloaded"] else "-",
                f"{f['weight_loss_kg']:.0f}" if f["unloaded"] else "-",
                _rs(sale.total_amount), amount(f["cash_discount"]), amount(f["commission"]),
                _rs(f["net_receivable"]),
            ] + ([_rs(row["profit"]) if row["profit"] is not None else "-"] if internal else []))
        rows.append(["Total", "", "", "", str(sum(int(r["sale"].total_bags or 0) for r in trucks)), "", "", "", "", "",
                     _rs(sum((r["figures"]["cash_discount"] for r in trucks), ZERO)),
                     _rs(sum((r["figures"]["commission"] for r in trucks), ZERO)),
                     _rs(sum((r["figures"]["net_receivable"] for r in trucks), ZERO))]
                    + ([_rs(report["profit"])] if internal else []))
        widths = [20, 30, 24, 38, 12, 17, 20, 17, 15, 26, 20, 20, 26] + ([22] if internal else [])
        scale = width / (sum(widths) * mm)
        story.append(grid(rows, [w * mm * scale for w in widths],
                          money_cols=tuple(range(4, len(widths))), bold_last=True))
        story.append(Spacer(1, 10))

    # ---- commission account (broker) ----
    if report["kind"] == "broker" and (report["commission_entries"] or report["commission_opening"]):
        story.append(_p("Commission you owe him", st["bold"]))
        rows = [["Date", "Particulars", "Earned", "Paid", "You owe"],
                ["", "Balance brought forward", "", "", _rs(report["commission_opening"])]]
        for entry in report["commission_entries"]:
            rows.append([f"{entry['date']:%d-%m-%Y}", Paragraph(str(entry["particulars"]), st["small"]),
                         amount(entry["credit"]), amount(entry["debit"]), _rs(entry["balance"])])
        rows.append(["", "Closing balance", "", "", _rs(report["commission_closing"])])
        story.append(grid(rows, [24 * mm, width - 24 * mm - 3 * 34 * mm, 34 * mm, 34 * mm, 34 * mm],
                          money_cols=(2, 3, 4), bold_last=True))

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.drawString(margin, margin / 2, f"{company.company_name} · {report['name']} · {label}")
        canvas.drawRightString(page[0] - margin, margin / 2, f"Page {doc.page}")
        canvas.restoreState()

    out = BytesIO()
    SimpleDocTemplate(out, pagesize=page, leftMargin=margin, rightMargin=margin, topMargin=margin,
                      bottomMargin=margin, title=f"{heading} {report['name']}").build(
        story, onFirstPage=footer, onLaterPages=footer)

    safe = "".join(ch for ch in report["name"] if ch.isalnum() or ch in " -_").strip().replace(" ", "_")
    response = HttpResponse(out.getvalue(), content_type="application/pdf")
    copy = "_internal" if internal else ""
    response["Content-Disposition"] = f'inline; filename="{report["kind"]}_{safe}_{"".join(ch for ch in label if ch.isalnum() or ch == "-")}{copy}.pdf"'
    return response
