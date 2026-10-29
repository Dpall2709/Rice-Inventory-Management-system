"""
The app beyond rice: any unit, 3-decimal quantities and rates, every freight
arrangement, manual GST with an audit trail, and creating customers,
suppliers and products from inside a sale or purchase.
"""

from datetime import timedelta
from decimal import Decimal

from django.urls import reverse
from django.utils import timezone

from django.test import TestCase

from core.models import (
    Customer, Mill, Product, Purchase, PurchaseItem, Sale, TaxAdjustment, Unit,
)
from core.services.catalog import seed_company_catalog
from core.services.sale_service import freight_figures, sale_profit, settlement
from core.tests import make_company


class GenericTradeTests(TestCase):

    def setUp(self):
        self.company, self.user = make_company("Sharma Distributors", "sharma_user")
        self.client.login(username="sharma_user", password="TestPass#2026")
        units = seed_company_catalog(self.company)
        self.biscuit = Product.objects.create(
            company=self.company, name="Marie 200g", unit=units["Carton"], rate_unit=units["Piece"],
            default_pack_size=24, gst_percent=18, hsn_code="1905",
        )
        self.supplier = Mill.objects.create(company=self.company, mill_name="Britannia Agency", mobile="9876543210")
        self.customer = Customer.objects.create(company=self.company, customer_name="Gupta Kirana")

        purchase = Purchase.objects.create(
            company=self.company, mill=self.supplier, invoice_no="BA-1", total_amount=0, tax_type="none",
            purchase_date=timezone.localdate() - timedelta(days=3),
        )
        item = PurchaseItem(purchase=purchase, product=self.biscuit, bag_weight=24, bag_count=100,
                            purchase_price=Decimal("8.125"))
        item.compute()
        item.save()

    def sale_post(self, **overrides):
        data = {
            "customer": self.customer.id, "sale_date": timezone.localdate().isoformat(), "due_date": "",
            "tax_type": "none", "broker": "", "broker_commission_type": "", "broker_commission_rate": "",
            "broker_paid_by": "us", "vehicle_number": "", "driver_name": "", "driver_mobile": "",
            "transporter_name": "", "freight_borne_by": "us", "freight_amount": "",
            "freight_customer_share": "", "transport_rate_per_ton": "", "transport_paid_by_dealer": "",
            "transport_paid_by_customer": "", "loading_charge": "0", "cash_discount_percent": "0",
            "advance_received": "", "advance_mode": "", "notes": "",
            "manual_cgst": "", "manual_sgst": "", "manual_igst": "", "gst_adjust_reason": "",
            "items-TOTAL_FORMS": "1", "items-INITIAL_FORMS": "0",
            "items-MIN_NUM_FORMS": "0", "items-MAX_NUM_FORMS": "1000",
            "items-0-product": self.biscuit.id, "items-0-bag_weight": "24", "items-0-bag_count": "10",
            "items-0-rate_per_kg": "10", "items-0-gst_percent": "0", "items-0-purchase_item": "",
        }
        data.update(overrides)
        return data

    def make_sale(self, **overrides):
        response = self.client.post(reverse("add_sale"), self.sale_post(**overrides))
        if response.status_code != 302:
            form = response.context["form"]
            self.fail(f"sale not saved: {form.errors} {response.context.get('stock_errors')}")
        return Sale.objects.for_company(self.company).order_by("-id").first()

    # ------------------------------------------------------------------ units & decimals

    def test_three_decimal_quantity_and_rate(self):
        # 2.5 cartons x 24 = 60 pieces x 10.125 = 607.50
        sale = self.make_sale(**{"items-0-bag_count": "2.5", "items-0-rate_per_kg": "10.125"})
        item = sale.items.get()
        self.assertEqual(item.bag_count, Decimal("2.500"))
        self.assertEqual(item.rate_per_kg, Decimal("10.125"))
        self.assertEqual(item.total_weight, Decimal("60.000"))
        self.assertEqual(sale.taxable_amount, Decimal("607.50"))

    def test_stock_counts_fractional_packs(self):
        self.make_sale(**{"items-0-bag_count": "99.5"})
        response = self.client.post(reverse("add_sale"), self.sale_post(**{"items-0-bag_count": "1"}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "only 0.5 ctn in stock")

    # ------------------------------------------------------------------ freight A-E

    def test_a_seller_pays_freight_is_an_expense(self):
        sale = self.make_sale(freight_borne_by="us", freight_amount="300")
        self.assertEqual(sale.total_amount, Decimal("2400.00"))
        self.assertEqual(sale.net_receivable, Decimal("2400.00"))
        self.assertEqual(settlement(sale)["freight_cost"], Decimal("300.00"))

    def test_b_buyer_pays_freight_on_the_invoice(self):
        sale = self.make_sale(freight_borne_by="customer", freight_amount="300")
        self.assertEqual(sale.freight_on_invoice, Decimal("300.00"))
        self.assertEqual(sale.total_amount, Decimal("2700.00"))
        self.assertEqual(sale.net_receivable, Decimal("2700.00"))
        self.assertEqual(settlement(sale)["freight_cost"], Decimal("0.00"))

    def test_b_buyer_paid_the_transporter_himself(self):
        sale = self.make_sale(freight_borne_by="customer", freight_amount="300", transport_paid_by_customer="300")
        self.assertEqual(sale.total_amount, Decimal("2700.00"))
        self.assertEqual(sale.net_receivable, Decimal("2400.00"))

    def test_c_shared_freight(self):
        sale = self.make_sale(freight_borne_by="shared", freight_amount="300", freight_customer_share="100")
        self.assertEqual(sale.freight_on_invoice, Decimal("100.00"))
        self.assertEqual(sale.total_amount, Decimal("2500.00"))
        self.assertEqual(settlement(sale)["freight_cost"], Decimal("200.00"))
        self.assertEqual(sale_profit(sale)["freight_cost"], Decimal("200.00"))

    def test_c_share_cannot_exceed_the_freight(self):
        sale = self.make_sale(freight_borne_by="shared", freight_amount="300", freight_customer_share="900")
        self.assertEqual(sale.freight_on_invoice, Decimal("300.00"))

    def test_d_separate_transport_invoice(self):
        sale = self.make_sale(freight_borne_by="bill", freight_amount="300")
        self.assertEqual(sale.total_amount, Decimal("2400.00"))           # goods invoice only
        self.assertTrue(sale.transport_invoice_no.startswith("TRN-"))
        self.assertEqual(sale.net_receivable, Decimal("2700.00"))         # buyer still owes the freight
        pdf = self.client.get(reverse("sale_transport_invoice_pdf", args=[sale.id]))
        self.assertEqual(pdf["Content-Type"], "application/pdf")

    def test_e_freight_in_the_rate(self):
        sale = self.make_sale(freight_borne_by="included", freight_amount="300")
        self.assertEqual(sale.total_amount, Decimal("2400.00"))
        self.assertEqual(freight_figures(sale)["cost"], Decimal("300.00"))
        self.assertEqual(self.client.get(reverse("sale_invoice_pdf", args=[sale.id])).status_code, 200)

    def test_direct_freight_is_outside_the_books(self):
        sale = self.make_sale(freight_borne_by="separate", freight_amount="300")
        figures = settlement(sale)
        self.assertEqual(figures["freight_cost"], Decimal("0.00"))
        self.assertEqual(sale.net_receivable, Decimal("2400.00"))

    def test_shared_share_is_ignored_for_other_modes(self):
        sale = self.make_sale(freight_borne_by="us", freight_amount="300", freight_customer_share="100")
        self.assertEqual(sale.freight_customer_share, Decimal("0.00"))

    # ------------------------------------------------------------------ manual GST

    def test_manual_gst_needs_a_reason(self):
        response = self.client.post(reverse("add_sale"), self.sale_post(
            tax_type="cgst_sgst", **{"items-0-gst_percent": "18", "manual_cgst": "21.61"}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "audit trail")

    def test_manual_gst_changes_the_total_and_is_logged(self):
        # 2400 taxable, 18% = 432 -> 216 + 216. The bill says 216.01 + 216.01.
        sale = self.make_sale(tax_type="cgst_sgst", manual_cgst="216.01", manual_sgst="216.01",
                              gst_adjust_reason="Matches customer's PO", **{"items-0-gst_percent": "18"})
        self.assertEqual(sale.cgst_amount, Decimal("216.01"))
        self.assertEqual(sale.gst_amount, Decimal("432.02"))
        self.assertEqual(sale.total_amount, Decimal("2832.00"))
        log = TaxAdjustment.objects.get(sale=sale)
        self.assertEqual(log.calculated_cgst, Decimal("216.00"))
        self.assertEqual(log.user, self.user)
        self.assertEqual(log.reason, "Matches customer's PO")

        page = self.client.get(reverse("sale_detail", args=[sale.id]))
        self.assertContains(page, "GST adjustments")

    def test_purchase_manual_gst(self):
        response = self.client.post(reverse("add_purchase"), {
            "mill": self.supplier.id, "invoice_no": "BA-2", "purchase_date": timezone.localdate().isoformat(),
            "tax_type": "igst", "discount_amount": "", "notes": "",
            "manual_igst": "180.04", "manual_cgst": "", "manual_sgst": "", "gst_adjust_reason": "Supplier rounding",
            "amount_paid_now": "", "payment_mode": "", "transport_amount": "", "labour_amount": "",
            "expense_other": "", "expense_other_note": "", "margin_percent": "8",
            "purchaseitem_set-TOTAL_FORMS": "1", "purchaseitem_set-INITIAL_FORMS": "0",
            "purchaseitem_set-MIN_NUM_FORMS": "0", "purchaseitem_set-MAX_NUM_FORMS": "1000",
            "purchaseitem_set-0-product": self.biscuit.id, "purchaseitem_set-0-bag_weight": "24",
            "purchaseitem_set-0-bag_count": "5", "purchaseitem_set-0-purchase_price": "8.335",
            "purchaseitem_set-0-gst_percent": "18",
        })
        self.assertEqual(response.status_code, 302, response.context and response.context["form"].errors)
        purchase = Purchase.objects.get(invoice_no="BA-2")
        # 5 x 24 x 8.335 = 1000.20; 18% = 180.04 (calculated 180.036 -> 180.04)
        self.assertEqual(purchase.igst_amount, Decimal("180.04"))
        self.assertEqual(TaxAdjustment.objects.filter(purchase=purchase).count(), 1)

    # ------------------------------------------------------------------ quick create

    def test_quick_customer_returns_json_for_the_sale_screen(self):
        self.assertEqual(self.client.get(reverse("quick_customer")).status_code, 200)
        response = self.client.post(reverse("quick_customer"), {"customer_name": "New Mart", "mobile": "9123456789",
                                                                "state": "Bihar"})
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data["label"], "New Mart")
        self.assertIn("tax_type", data["data"])
        self.assertTrue(Customer.objects.filter(company=self.company, customer_name="New Mart").exists())

    def test_quick_supplier_validation_errors_come_back_as_the_form(self):
        response = self.client.post(reverse("quick_supplier"), {"mill_name": "", "mobile": ""})
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "data-quick-form", status_code=400)

    def test_quick_product_is_usable_at_once(self):
        unit = Unit.objects.get(company=self.company, name="Box")
        response = self.client.post(reverse("quick_product"), {"name": "Rusk 300g", "unit": unit.id,
                                                               "gst_percent": "5", "default_pack_size": ""})
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()["data"]["unit"], "box")
        self.assertEqual(response.json()["data"]["pack_size"], 1.0)

    # ------------------------------------------------------------------ products & units pages

    def test_product_and_units_pages(self):
        self.assertEqual(self.client.get(reverse("product_list")).status_code, 200)
        self.assertEqual(self.client.get(reverse("add_product")).status_code, 200)
        self.assertEqual(self.client.get(reverse("units_and_categories")).status_code, 200)
        self.client.post(reverse("units_and_categories"), {"add_unit": "1", "unit-name": "Dozen", "unit-symbol": "dz"})
        self.assertTrue(Unit.objects.filter(company=self.company, name="Dozen").exists())
        response = self.client.post(reverse("add_product"), {
            "name": "Eggs", "unit": Unit.objects.get(company=self.company, name="Dozen").id,
            "rate_unit": "", "default_pack_size": "12", "gst_percent": "0", "is_active": "on",
        })
        self.assertEqual(response.status_code, 302)
        eggs = Product.objects.get(company=self.company, name="Eggs")
        self.assertEqual(eggs.rate_unit, eggs.unit)
        self.assertEqual(eggs.default_pack_size, Decimal("1"))

    def test_new_company_gets_default_units(self):
        from core.services.registration_service import register_company

        company = register_company({
            "company_name": "Cement House", "owner_name": "Raj", "email": "raj@example.com",
            "mobile": "9000000000", "username": "cement_raj", "password1": "TestPass#2026",
            "industry": "building",
        })
        self.assertTrue(company.units.filter(name="Bag").exists())
        self.assertTrue(company.product_categories.filter(name="Cement").exists())
