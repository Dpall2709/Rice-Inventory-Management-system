from datetime import timedelta
from decimal import Decimal

from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from core.models import Customer, Mill, Product, Purchase, PurchaseItem, Sale, TaxAdjustment, Unit
from core.services.catalog import seed_company_catalog
from core.tests import make_company


class ApiTests(APITestCase):

    def setUp(self):
        self.company, self.user = make_company("Biscuit Depot", "depot_user")
        units = seed_company_catalog(self.company)
        self.carton, self.piece = units["Carton"], units["Piece"]
        self.product = Product.objects.create(
            company=self.company, name="Glucose 100g", unit=self.carton, rate_unit=self.piece,
            default_pack_size=24, gst_percent=18, hsn_code="1905",
        )
        self.supplier = Mill.objects.create(company=self.company, mill_name="Parle Agency", mobile="9876543210")
        self.customer = Customer.objects.create(company=self.company, customer_name="Sharma Stores", state="")

        token = self.client.post(reverse("api:token"), {"username": "depot_user", "password": "TestPass#2026"})
        self.assertEqual(token.status_code, 200, token.content)
        self.client.credentials(HTTP_AUTHORIZATION="Bearer " + token.data["access"])

    def buy(self, cartons="10"):
        return self.client.post(reverse("api:purchase-list"), {
            "supplier": self.supplier.id,
            "invoice_no": "PA-1",
            "purchase_date": str(timezone.localdate() - timedelta(days=2)),
            "tax_type": "cgst_sgst",
            "items": [{"product": self.product.id, "pack_size": "24", "quantity": cartons, "rate": "4.125"}],
        }, format="json")

    def test_requires_a_token(self):
        self.client.credentials()
        self.assertEqual(self.client.get(reverse("api:me")).status_code, 401)

    def test_me_returns_company_and_choices(self):
        response = self.client.get(reverse("api:me"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["company"]["name"], "Biscuit Depot")
        self.assertIn("shared", [c["value"] for c in response.data["choices"]["freight_modes"]])

    def test_purchase_with_three_decimal_rate(self):
        response = self.buy()
        self.assertEqual(response.status_code, 201, response.content)
        purchase = Purchase.objects.get(pk=response.data["id"])
        item = purchase.purchaseitem_set.get()
        self.assertEqual(item.purchase_price, Decimal("4.125"))
        # 10 cartons x 24 pcs x 4.125 = 990.00, GST 18% = 178.20
        self.assertEqual(purchase.taxable_amount, Decimal("990.00"))
        self.assertEqual(purchase.cgst_amount + purchase.sgst_amount, Decimal("178.20"))

    def test_sale_checks_stock_and_adds_buyer_freight(self):
        self.buy()
        response = self.client.post(reverse("api:sale-list"), {
            "customer": self.customer.id,
            "sale_date": str(timezone.localdate()),
            "tax_type": "cgst_sgst",
            "freight_mode": "customer",
            "freight_amount": "500",
            "items": [{"product": self.product.id, "pack_size": "24", "quantity": "4", "rate": "5"}],
        }, format="json")
        self.assertEqual(response.status_code, 201, response.content)
        sale = Sale.objects.get(pk=response.data["id"])
        # 4 x 24 x 5 = 480 + 18% = 566.40, + 500 freight = 1066.40 -> 1066
        self.assertEqual(sale.freight_on_invoice, Decimal("500.00"))
        self.assertEqual(sale.total_amount, Decimal("1066.00"))

        too_many = self.client.post(reverse("api:sale-list"), {
            "customer": self.customer.id, "sale_date": str(timezone.localdate()), "tax_type": "none",
            "items": [{"product": self.product.id, "pack_size": "24", "quantity": "50", "rate": "5"}],
        }, format="json")
        self.assertEqual(too_many.status_code, 400)
        self.assertIn("in stock", str(too_many.data))

    def test_manual_gst_needs_a_reason_and_is_audited(self):
        payload = {
            "supplier": self.supplier.id, "invoice_no": "PA-2",
            "purchase_date": str(timezone.localdate()), "tax_type": "cgst_sgst",
            "manual_cgst": "89.11", "manual_sgst": "89.11",
            "items": [{"product": self.product.id, "pack_size": "24", "quantity": "10", "rate": "4.125"}],
        }
        self.assertEqual(self.client.post(reverse("api:purchase-list"), payload, format="json").status_code, 400)

        payload["gst_adjust_reason"] = "Supplier rounds per line"
        response = self.client.post(reverse("api:purchase-list"), payload, format="json")
        self.assertEqual(response.status_code, 201, response.content)
        purchase = Purchase.objects.get(pk=response.data["id"])
        self.assertEqual(purchase.cgst_amount, Decimal("89.11"))
        # 990 + 178.22 = 1168.22 -> 1168
        self.assertEqual(purchase.total_amount, Decimal("1168.00"))
        log = TaxAdjustment.objects.get(purchase=purchase)
        self.assertEqual(log.calculated_cgst, Decimal("89.10"))
        self.assertEqual(log.difference, Decimal("0.02"))

    def test_other_companys_records_are_invisible(self):
        other, _ = make_company("Other Co", "other_user")
        foreign = Customer.objects.create(company=other, customer_name="Not yours")
        self.assertEqual(self.client.get(reverse("api:customer-detail", args=[foreign.id])).status_code, 404)
        names = [c["customer_name"] for c in self.client.get(reverse("api:customer-list")).data["results"]]
        self.assertEqual(names, ["Sharma Stores"])

    def test_staff_cannot_edit_masters(self):
        profile = self.user.userprofile
        profile.role = "staff"
        profile.save()
        response = self.client.patch(reverse("api:customer-detail", args=[self.customer.id]),
                                     {"mobile": "9999999999"}, format="json")
        self.assertEqual(response.status_code, 403)

    def test_dashboard_reports_and_pdf(self):
        self.buy()
        self.assertEqual(self.client.get(reverse("api:dashboard")).status_code, 200)
        self.assertEqual(self.client.get(reverse("api:receivables_report")).status_code, 200)
        self.assertEqual(self.client.get(reverse("api:payables_report")).status_code, 200)
        stock = self.client.get(reverse("api:product-stock")).data
        self.assertEqual(stock[0]["quantity"], "10")
        sale = self.client.post(reverse("api:sale-list"), {
            "customer": self.customer.id, "sale_date": str(timezone.localdate()), "tax_type": "none",
            "items": [{"product": self.product.id, "pack_size": "24", "quantity": "1", "rate": "5"}],
        }, format="json")
        pdf = self.client.get(reverse("api:sale-invoice-pdf", args=[sale.data["id"]]))
        self.assertEqual(pdf["Content-Type"], "application/pdf")

    def test_payment_in_against_customer(self):
        response = self.client.post(reverse("api:payment-list"), {
            "related_type": "sale", "customer": self.customer.id, "amount": "250",
            "payment_mode": "UPI", "payment_date": str(timezone.localdate()),
        }, format="json")
        self.assertEqual(response.status_code, 201, response.content)

    def test_new_product_through_api(self):
        response = self.client.post(reverse("api:product-list"), {
            "name": "Cement OPC 53", "unit": Unit.objects.get(company=self.company, name="Bag").id,
            "gst_percent": "28",
        }, format="json")
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.data["rate_unit_label"], "bag")
