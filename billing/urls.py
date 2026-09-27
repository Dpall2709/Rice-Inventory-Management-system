from django.urls import path

from . import views

app_name = "billing"

urlpatterns = [
    path("", views.home, name="home"),
    path("checkout/<slug:code>/", views.checkout, name="checkout"),
    path("payment/success/", views.payment_success, name="payment_success"),
    path("webhook/razorpay/", views.razorpay_webhook, name="razorpay_webhook"),

    # Staff-only screens
    path("manage/", views.manage_companies, name="manage_companies"),
    path("manage/<int:company_id>/extend/", views.extend_subscription, name="extend_subscription"),
]
