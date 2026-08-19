from .dashboard import dashboard
from .auth.register_view import register_view
from .auth.login_view import login_view
from .auth.logout_view import logout_view
from .mill.add_mill import add_mill
from .mill.mill_list import mill_list
from .mill.edit_mill import edit_mill
from .mill.delete_mill import delete_mill
from .product.add_purchase import add_purchase
from core.view.customer.customer_view import (
    customer_list,
    add_customer,
    edit_customer,
    delete_customer,
)