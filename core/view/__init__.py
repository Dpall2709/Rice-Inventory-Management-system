from .dashboard import dashboard
from .auth.register_view import register_view
from .auth.login_view import login_view
from .auth.logout_view import logout_view
from .mill.mill_form import add_mill, edit_mill
from .mill.mill_list import mill_list
from .mill.delete_mill import delete_mill, restore_mill
from core.view.customer.customer_view import (
    customer_list,
    add_customer,
    edit_customer,
    delete_customer,
    customer_ledger,
)

from .purchase.purchase_form import add_purchase, edit_purchase
from .purchase.purchase_list import (
    add_purchase_expense,
    delete_purchase,
    delete_purchase_expense,
    purchase_detail,
    purchase_list,
)
from .purchase.payments import add_mill_payment, add_purchase_payment
from .purchase.scan import discard_scan, purchase_bill_file, scan_add_supplier, scan_purchase_bill
from .sale.sale_views import (
    add_customer_payment,
    add_sale,
    add_sale_payment,
    delete_payment,
    delete_sale,
    edit_sale,
    sale_detail,
    sale_list,
    sale_print,
    settle_sale,
)
from .broker.broker_views import (
    add_broker,
    add_broker_payment,
    add_broker_receipt,
    broker_list,
    broker_report_detail,
    edit_broker,
    toggle_broker,
)
from .reports.trade_register import trade_register
