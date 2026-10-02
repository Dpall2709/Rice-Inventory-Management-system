"""PDF / Excel statements for one customer or one broker, for a month or a date range."""

from core.models import Broker, Customer
from core.services.party_reports import broker_report, customer_report, parse_period, report_excel, report_pdf
from core.tenancy import company_of, tenant_object_or_404

from ..base_imports import *


def _export(request, report, label, fmt):
    company = company_of(request)
    # The copy you send leaves out your profit; ?internal=1 is your own copy.
    internal = request.GET.get("internal") == "1"
    if fmt == "xlsx":
        return report_excel(company, report, label, internal=internal)
    return report_pdf(company, report, label, internal=internal)


@login_required
def customer_statement_export(request, customer_id, fmt):
    company = company_of(request)
    customer = tenant_object_or_404(Customer, request, customer_id)
    start, end, label = parse_period(request.GET)
    return _export(request, customer_report(company, customer, start, end), label, fmt)


@login_required
def broker_statement_export(request, broker_id, fmt):
    company = company_of(request)
    broker = tenant_object_or_404(Broker, request, broker_id)
    start, end, label = parse_period(request.GET)
    return _export(request, broker_report(company, broker, start, end), label, fmt)
