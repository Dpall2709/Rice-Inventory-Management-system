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
)

from .purchase.purchase_form import add_purchase, edit_purchase
from .purchase.purchase_list import (
    add_purchase_expense,
    delete_purchase,
    delete_purchase_expense,
    purchase_detail,
    purchase_list,
)
