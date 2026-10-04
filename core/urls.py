from django.urls import path
from . import views
from . import view
from .view.auth.register_view import register_view

# from core.function.register_view import register_view
# from .views.dashboard import *
# from .views.auth import register_view

# from django.urls import path
# from core import views  # This automatically reads everything inside core/views/__init__.py
# from core.function.register_view import register_view




urlpatterns = [
    path('', view.dashboard, name='dashboard'), 
    path('add_mill/', view.add_mill, name='add_mill'),
    path('mills/', view.mill_list, name='mill_list'),
    path('mills/edit/<int:mill_id>/', view.edit_mill, name='edit_mill'),
    path('mills/delete/<int:mill_id>/', view.delete_mill, name='delete_mill'),
    path('mills/restore/<int:mill_id>/', view.restore_mill, name='restore_mill'),
    
    path('products/', views.product_list, name='product_list'),
    path('products/add/', views.add_product, name='add_product'),
    path('products/edit/<int:product_id>/', views.edit_product, name='edit_product'),
    path('products/delete/<int:product_id>/', views.delete_product, name='delete_product'),
    path("products/report/<int:product_id>/", views.product_report, name="product_report"),



    path("purchase/add/", view.add_purchase, name="add_purchase"),
    path("purchase/scan/", view.scan_purchase_bill, name="scan_purchase_bill"),
    path("purchase/scan/add-supplier/", view.scan_add_supplier, name="scan_add_supplier"),
    path("purchase/scan/discard/", view.discard_scan, name="discard_scan"),
    path("purchase/<int:purchase_id>/bill/", view.purchase_bill_file, name="purchase_bill_file"),
    path("purchase/list/", view.purchase_list, name="purchase_list"),
    path("purchase/<int:purchase_id>/", view.purchase_detail, name="purchase_detail"),
    path("purchase/edit/<int:purchase_id>/", view.edit_purchase, name="edit_purchase"),
    path("purchase/delete/<int:purchase_id>/", view.delete_purchase, name="delete_purchase"),
    path("purchase/<int:purchase_id>/expense/add/", view.add_purchase_expense, name="add_purchase_expense"),
    path("purchase/<int:purchase_id>/expense/<int:expense_id>/delete/", view.delete_purchase_expense, name="delete_purchase_expense"),
    path("payment/purchase/add/<int:purchase_id>/", view.add_purchase_payment, name="add_purchase_payment"),


    path("mills/report/<int:mill_id>/", views.mill_report_detail, name="mill_report_detail"),
    path("payment/mill/add/<int:mill_id>/", view.add_mill_payment, name="add_mill_payment"),
    path("mills/<int:mill_id>/export/excel/", views.mill_report_excel, name="mill_report_excel"),
    path("mills/<int:mill_id>/export/pdf/", views.mill_report_pdf, name="mill_report_pdf"),

    path("sales/", view.sale_list, name="sale_list"),
    path("sales/add/", view.add_sale, name="add_sale"),
    path("sales/<int:sale_id>/", view.sale_detail, name="sale_detail"),
    path("sales/<int:sale_id>/edit/", view.edit_sale, name="edit_sale"),
    path("sales/<int:sale_id>/delete/", view.delete_sale, name="delete_sale"),
    path("sales/<int:sale_id>/settle/", view.settle_sale, name="settle_sale"),
    path("sales/<int:sale_id>/print/", view.sale_print, name="sale_print"),
    path("sales/<int:sale_id>/payment/add/", view.add_sale_payment, name="add_sale_payment"),
    path("sales/<int:sale_id>/invoice.pdf", views.sale_invoice_pdf, name="sale_invoice_pdf"),
    path("sales/<int:sale_id>/statement.pdf", views.sale_statement_pdf, name="sale_statement_pdf"),
    path("reports/trucks/", view.trade_register, name="trade_register"),
    path("customers/<int:customer_id>/statement.<str:fmt>", view.customer_statement_export, name="customer_statement_export"),
    path("brokers/<int:broker_id>/statement.<str:fmt>", view.broker_statement_export, name="broker_statement_export"),
    path("payments/<int:payment_id>/delete/", view.delete_payment, name="delete_payment"),

    path("brokers/", view.broker_list, name="broker_list"),
    path("brokers/add/", view.add_broker, name="add_broker"),
    path("brokers/<int:broker_id>/edit/", view.edit_broker, name="edit_broker"),
    path("brokers/<int:broker_id>/toggle/", view.toggle_broker, name="toggle_broker"),
    path("brokers/report/<int:broker_id>/", view.broker_report_detail, name="broker_report_detail"),
    path("brokers/<int:broker_id>/payment/add/", view.add_broker_payment, name="add_broker_payment"),
    path("brokers/<int:broker_id>/receipt/add/", view.add_broker_receipt, name="add_broker_receipt"),

    path('register/', register_view, name='register'),
    path('login/', view.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),


    path(
    "customers/",
    view.customer_list,
    name="customer_list"
),

path(
    "customers/add/",
    view.add_customer,
    name="add_customer"
),

path(
    "customers/<int:customer_id>/",
    view.customer_ledger,
    name="customer_ledger"
),

path(
    "customers/<int:customer_id>/payment/add/",
    view.add_customer_payment,
    name="add_customer_payment"
),

path(
    "customers/edit/<int:customer_id>/",
    view.edit_customer,
    name="edit_customer"
),

path(
    "customers/delete/<int:customer_id>/",
    view.delete_customer,
    name="delete_customer"
),



]