"""
/api/v1/ - the mobile app API.

    POST auth/token/            {username, password} -> {access, refresh}
    POST auth/token/refresh/    {refresh} -> {access}
    GET  me/                    user, role, company, choices for dropdowns
    GET  dashboard/             this period's figures, dues, recent sales

    customers/  suppliers/  products/  units/  categories/   (CRUD; delete = deactivate)
    customers/<id>/statement/   suppliers/<id>/statement/
    products/stock/
    purchases/                  list, detail, create
    sales/                      list, detail, create
    sales/<id>/invoice-pdf/     sales/<id>/transport-invoice-pdf/
    sales/lots/?product=<id>
    payments/                   list, create (money in: related_type=sale; out: purchase), delete
    reports/summary/  reports/receivables/  reports/payables/
"""

from django.urls import include, path
from rest_framework.routers import DefaultRouter
from rest_framework.throttling import AnonRateThrottle
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from . import views

router = DefaultRouter()
router.register("customers", views.CustomerViewSet, basename="customer")
router.register("suppliers", views.SupplierViewSet, basename="supplier")
router.register("products", views.ProductViewSet, basename="product")
router.register("units", views.UnitViewSet, basename="unit")
router.register("categories", views.CategoryViewSet, basename="category")
router.register("purchases", views.PurchaseViewSet, basename="purchase")
router.register("sales", views.SaleViewSet, basename="sale")
router.register("payments", views.PaymentViewSet, basename="payment")

app_name = "api"

class LoginThrottledTokenView(TokenObtainPairView):
    """Logging in from the app is limited per IP, like the web login."""

    throttle_classes = [AnonRateThrottle]


urlpatterns = [
    path("auth/token/", LoginThrottledTokenView.as_view(), name="token"),
    path("auth/token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("me/", views.me, name="me"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("reports/summary/", views.summary_report, name="summary_report"),
    path("reports/receivables/", views.receivables_report, name="receivables_report"),
    path("reports/payables/", views.payables_report, name="payables_report"),
    path("", include(router.urls)),
]
