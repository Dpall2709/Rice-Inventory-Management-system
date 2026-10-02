"""
Truck settlement, checked against a real trader's register (row 1 of the
"Maa Bagwati Bhandar" sheet):

    1-Dec-2025  CG04PX-5695  GOYAL AGRO RAIPUR
    700 bags x 50 kg = 35,000 kg bought @ 25.50     -> 8,92,500
    loading 3,500 · freight advance 40,000 · balance (party pays driver) 21,947
    sold @ 28.50 · party received 34,920 kg (80 kg short) -> 9,95,220
    CD 1.5% = 14,928.30 · brokerage 0.10/kg paid by party = 3,492
    total party price 9,76,799.70
"""

from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import Broker, Customer, Mill, Payment, Product, Purchase, PurchaseItem, Sale
from core.services.customer_ledger import broker_collections, broker_statement, customer_statement
from core.services.sale_service import sale_profit, settlement
from core.services.trade_register import register_rows, register_totals
from core.tests import make_company


class TruckSettlementTests(TestCase):

    def setUp(self):
        self.company, self.user = make_company("Bhagwati Bhandar", "bhandar_user")
        self.client.login(username="bhandar_user", password="TestPass#2026")
        today = timezone.localdate()

        mill = Mill.objects.create(company=self.company, mill_name="Goyal Agro Raipur", mobile="9876543210")
        self.rice = Product.objects.create(company=self.company, rice_name="Parboiled", gst_percent=0)
        purchase = Purchase.objects.create(
            company=self.company, mill=mill, invoice_no="GA-1", purchase_date=today - timedelta(days=5),
            total_amount=0, tax_type="none",
        )
        item = PurchaseItem(purchase=purchase, product=self.rice, bag_weight=50, bag_count=700,
                            purchase_price=Decimal("25.50"))
        item.compute()
        item.save()
        purchase.taxable_amount = item.taxable_amount
        purchase.total_amount = item.line_total
        purchase.save()

        self.customer = Customer.objects.create(company=self.company, customer_name="Party One",
                                                default_cash_discount_percent=Decimal("1.5"))
        self.broker = Broker.objects.create(company=self.company, broker_name="Gopal Bajaj",
                                            commission_type="per_quintal", commission_rate=10)

    def truck_post(self, **overrides):
        data = {
            "customer": self.customer.id,
            "sale_date": (timezone.localdate() - timedelta(days=4)).isoformat(),
            "due_date": "", "tax_type": "none",
            "broker": self.broker.id, "broker_commission_type": "per_quintal",
            "broker_commission_rate": "10", "broker_paid_by": "customer",
            "vehicle_number": "CG04PX-5695", "driver_name": "", "driver_mobile": "", "transporter_name": "",
            "freight_borne_by": "us", "transport_rate_per_ton": "0",
            "transport_paid_by_dealer": "40000", "transport_paid_by_customer": "21947",
            "loading_charge": "3500", "cash_discount_percent": "1.5",
            "advance_received": "", "advance_mode": "", "notes": "",
            "items-TOTAL_FORMS": "1", "items-INITIAL_FORMS": "0",
            "items-MIN_NUM_FORMS": "0", "items-MAX_NUM_FORMS": "1000",
            "items-0-product": self.rice.id, "items-0-bag_weight": "50", "items-0-bag_count": "700",
            "items-0-rate_per_kg": "28.50", "items-0-gst_percent": "0", "items-0-purchase_item": "",
        }
        data.update(overrides)
        return data

    def make_truck(self, **overrides):
        response = self.client.post(reverse("add_sale"), self.truck_post(**overrides))
        self.assertEqual(response.status_code, 302, getattr(response, "context", None) and response.context["form"].errors)
        return Sale.objects.for_company(self.company).order_by("-id").first()

    def make_truck_direct(self):
        return self.make_truck(broker="", broker_commission_rate="", cash_discount_percent="0")

    def settle(self, sale, **extra):
        data = {
            "unload_date": (timezone.localdate() - timedelta(days=1)).isoformat(),
            "received_weight_kg": "34920", "cash_discount_percent": "1.5",
            "broker_paid_by": "customer", "transport_paid_by_customer": "21947",
            "other_deductions": "0", "other_deductions_note": "",
        }
        data.update(extra)
        response = self.client.post(reverse("settle_sale", args=[sale.id]), data)
        self.assertEqual(response.status_code, 302)
        sale.refresh_from_db()
        return sale

    def test_matches_the_traders_register(self):
        sale = self.settle(self.make_truck())
        figures = settlement(sale)

        self.assertEqual(figures["weight_loss_kg"], Decimal("80.00"))
        self.assertEqual(figures["party_value"], Decimal("995220.00"))
        self.assertEqual(figures["cash_discount"], Decimal("14928.30"))
        self.assertEqual(figures["brokerage_cut"], Decimal("3492.00"))
        self.assertEqual(figures["goods_payable"], Decimal("976799.70"))   # "Total Party Price"
        # The party also cuts the 21,947 they paid the driver.
        self.assertEqual(figures["net_receivable"], Decimal("954852.70"))
        self.assertEqual(sale.net_receivable, Decimal("954852.70"))

        profit = sale_profit(sale)
        # 8,92,500 rice + 3,500 loading + 61,947 freight = 9,57,947 ("Total Price")
        self.assertEqual(profit["cost"], Decimal("957947.00"))
        # The sheet showed a loss of 1,925 because it counted the 21,947 freight twice.
        self.assertEqual(profit["profit"], Decimal("18852.70"))

    def test_broker_truck_is_owed_by_the_broker_not_the_party(self):
        sale = self.settle(self.make_truck())
        self.assertEqual(sale.collect_from, Sale.COLLECT_FROM_BROKER)

        collections = broker_collections(self.company, self.broker)
        self.assertEqual(collections["total_due"], Decimal("954852.70"))
        self.assertEqual(collections["rows"][0]["total"], sale.net_receivable)

        statement = customer_statement(self.company, self.customer)
        self.assertEqual(statement["total_due"], Decimal("0"))
        self.assertEqual(statement["broker_sales"], [sale])

    def test_payment_on_a_broker_truck_goes_to_the_broker(self):
        sale = self.settle(self.make_truck())
        self.client.post(reverse("add_sale_payment", args=[sale.id]), {
            "amount": "954852.70", "payment_mode": "Bank", "payment_date": timezone.localdate().isoformat(),
        })
        payment = Payment.objects.get(sale=sale)
        self.assertEqual(payment.broker, self.broker)
        self.assertIsNone(payment.customer)
        self.assertEqual(broker_collections(self.company, self.broker)["total_due"], Decimal("0"))

    def test_broker_pays_on_account_oldest_truck_first(self):
        first = self.settle(self.make_truck())
        self.client.post(reverse("add_broker_receipt", args=[self.broker.id]), {
            "amount": "900000", "payment_mode": "Bank", "payment_date": timezone.localdate().isoformat(),
        })
        rows = broker_collections(self.company, self.broker)["rows"]
        self.assertEqual(rows[0]["sale"], first)
        self.assertEqual(rows[0]["due"], Decimal("54852.70"))
        self.assertEqual(broker_statement(self.company, self.broker)["broker_owes_us"], Decimal("54852.70"))

    def test_direct_sale_has_no_brokerage_and_the_customer_pays(self):
        sale = self.make_truck_direct()
        self.assertEqual(sale.collect_from, Sale.COLLECT_FROM_CUSTOMER)
        figures = settlement(sale)
        self.assertEqual(figures["commission"], Decimal("0.00"))
        self.assertEqual(figures["brokerage_cut"], Decimal("0.00"))
        self.assertEqual(customer_statement(self.company, self.customer)["total_due"], sale.net_receivable)

    def test_one_truck_from_two_mills_prints_one_invoice_line(self):
        from core.services.sale_service import invoice_lines

        second_mill = Mill.objects.create(company=self.company, mill_name="Shraddha Traders Durg", mobile="9876543211")
        purchase = Purchase.objects.create(company=self.company, mill=second_mill, invoice_no="ST-1",
                                           purchase_date=timezone.localdate() - timedelta(days=5),
                                           total_amount=0, tax_type="none")
        lot2 = PurchaseItem(purchase=purchase, product=self.rice, bag_weight=50, bag_count=300,
                            purchase_price=Decimal("24.00"))
        lot2.compute()
        lot2.save()
        lot1 = PurchaseItem.objects.get(purchase__invoice_no="GA-1")

        data = self.truck_post(**{
            "items-TOTAL_FORMS": "2",
            "items-0-bag_count": "400", "items-0-purchase_item": lot1.id,
            "items-1-product": self.rice.id, "items-1-bag_weight": "50", "items-1-bag_count": "300",
            "items-1-rate_per_kg": "28.50", "items-1-gst_percent": "0", "items-1-purchase_item": lot2.id,
        })
        self.assertEqual(self.client.post(reverse("add_sale"), data).status_code, 302)
        sale = Sale.objects.get(vehicle_number="CG04PX-5695")
        self.assertEqual(sorted(sale.lots.values_list("mill__mill_name", flat=True)),
                         ["Goyal Agro Raipur", "Shraddha Traders Durg"])
        lines = invoice_lines(sale)
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0].bag_count, 700)

    def test_commission_per_kg(self):
        from core.services.sale_service import broker_commission

        self.assertEqual(broker_commission("per_kg", Decimal("0.10"), 700, Decimal("34920"), 0), Decimal("3492.00"))

    def test_weighbridge_weight_sets_the_shortage(self):
        sale = self.make_truck()
        sale.loading_weight_kg = Decimal("35050")
        sale.save()
        sale = self.settle(sale)
        figures = settlement(sale)
        self.assertEqual(figures["weight_loss_kg"], Decimal("130.00"))
        # The party still pays the rate on the weight they received.
        self.assertEqual(figures["party_value"], Decimal("995220.00"))

    def test_broker_paid_by_party_is_not_owed_by_us(self):
        self.settle(self.make_truck())
        statement = broker_statement(self.company, self.broker)
        self.assertEqual(statement["earned"], Decimal("0"))
        self.assertEqual(statement["paid_by_parties"], Decimal("3492.00"))

    def test_before_unloading_profit_is_an_estimate_on_the_weight_sent(self):
        sale = self.make_truck()
        figures = settlement(sale)
        self.assertFalse(figures["unloaded"])
        self.assertEqual(figures["party_value"], Decimal("997500.00"))   # 35,000 x 28.50
        self.assertEqual(figures["cash_discount"], Decimal("14962.50"))

    def test_party_carries_the_freight(self):
        sale = self.make_truck()
        sale.freight_borne_by = Sale.FREIGHT_CUSTOMER
        sale.save()
        sale = self.settle(sale)
        figures = settlement(sale)
        # Our 40,000 advance to the driver is added to the party's bill; no freight cost.
        self.assertEqual(figures["net_receivable"], Decimal("976799.70") + Decimal("40000"))
        self.assertEqual(sale_profit(sale)["freight_cost"], Decimal("0.00"))

    def test_register_marks_unpaid_trucks_as_awaiting_not_loss(self):
        self.settle(self.make_truck())
        rows = register_rows(self.company, Sale.objects.for_company(self.company))
        self.assertEqual(rows[0]["status"], "awaiting_payment")
        totals = register_totals(rows)
        self.assertEqual(totals["profit_expected"], Decimal("18852.70"))
        self.assertEqual(totals["profit_settled"], Decimal("0"))

    def test_register_page_and_excel(self):
        self.settle(self.make_truck())
        page = self.client.get(reverse("trade_register"))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "CG04PX-5695")
        excel = self.client.get(reverse("trade_register") + "?export=xlsx")
        self.assertEqual(excel.status_code, 200)
        self.assertIn("spreadsheetml", excel["Content-Type"])

    def test_settlement_validation(self):
        sale = self.make_truck()
        response = self.client.post(reverse("settle_sale", args=[sale.id]), {
            "unload_date": (timezone.localdate() + timedelta(days=2)).isoformat(),
            "received_weight_kg": "50000", "cash_discount_percent": "150",
        })
        self.assertEqual(response.status_code, 200)
        form = response.context["form"]
        self.assertIn("unload_date", form.errors)
        self.assertIn("received_weight_kg", form.errors)
        self.assertIn("cash_discount_percent", form.errors)

    def test_settlement_page_opens(self):
        sale = self.make_truck()
        self.assertEqual(self.client.get(reverse("settle_sale", args=[sale.id])).status_code, 200)
        self.assertEqual(self.client.get(reverse("sale_detail", args=[sale.id])).status_code, 200)

    def test_statement_pdf(self):
        sale = self.settle(self.make_truck())
        response = self.client.get(reverse("sale_statement_pdf", args=[sale.id]))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.content.startswith(b"%PDF"))

    def test_cd_and_brokerage_can_change_at_unloading(self):
        sale = self.make_truck()
        sale = self.settle(sale, cash_discount_percent="1", broker_commission_type="per_kg",
                           broker_commission_rate="0.08")
        figures = settlement(sale)
        self.assertEqual(figures["cash_discount"], Decimal("9952.20"))   # 1% of 9,95,220
        self.assertEqual(figures["commission"], Decimal("2793.60"))      # 34,920 kg x 0.08
        # The broker's usual rate on his own page is untouched.
        self.broker.refresh_from_db()
        self.assertEqual(self.broker.commission_rate, Decimal("10.00"))

    # ---- customer / broker statements (PDF + Excel, by month or range) ----

    def test_period_parsing(self):
        from datetime import date

        from core.services.party_reports import parse_period

        start, end, label = parse_period({"month": "2026-02"})
        self.assertEqual((start, end), (date(2026, 2, 1), date(2026, 2, 28)))
        start, end, _label = parse_period({"from": "2026-09-10", "to": "2026-09-01"})
        self.assertEqual((start, end), (date(2026, 9, 1), date(2026, 9, 10)))   # swapped into order
        start, end, _label = parse_period({}, today=date(2026, 10, 2))
        self.assertEqual((start, end), (date(2026, 10, 1), date(2026, 10, 2)))

    def test_broker_statement_downloads(self):
        sale = self.settle(self.make_truck())
        month = sale.sale_date.strftime("%Y-%m")
        for fmt, marker in (("pdf", b"%PDF"), ("xlsx", b"PK")):
            with self.subTest(fmt=fmt):
                response = self.client.get(
                    reverse("broker_statement_export", args=[self.broker.id, fmt]) + f"?month={month}"
                )
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.content.startswith(marker))

    def test_customer_statement_downloads_and_carries_the_balance_forward(self):
        from core.services.party_reports import customer_report

        sale = self.settle(self.make_truck_direct())
        later = sale.sale_date + timedelta(days=1)
        report = customer_report(self.company, self.customer, later, later + timedelta(days=30))
        # Nothing happened in that window: the invoice is in the balance brought forward.
        self.assertEqual(report["entries"], [])
        self.assertEqual(report["opening"], sale.net_receivable)
        self.assertEqual(report["closing"], sale.net_receivable)

        for fmt in ("pdf", "xlsx"):
            response = self.client.get(
                reverse("customer_statement_export", args=[self.customer.id, fmt])
                + f"?from={sale.sale_date}&to={sale.sale_date}"
            )
            self.assertEqual(response.status_code, 200)

    def test_another_company_cannot_download_statements(self):
        make_company("Other Rice", "other_rice_user")
        self.client.logout()
        self.client.login(username="other_rice_user", password="TestPass#2026")
        self.assertEqual(self.client.get(reverse("broker_statement_export", args=[self.broker.id, "pdf"])).status_code, 404)
        self.assertEqual(self.client.get(reverse("customer_statement_export", args=[self.customer.id, "xlsx"])).status_code, 404)

    def test_print_page_shows_the_invoice_pdf(self):
        sale = self.make_truck()
        page = self.client.get(reverse("sale_print", args=[sale.id]))
        self.assertContains(page, reverse("sale_invoice_pdf", args=[sale.id]))

    def test_statement_sent_to_the_party_never_shows_profit(self):
        from io import BytesIO

        from openpyxl import load_workbook

        sale = self.settle(self.make_truck())
        url = reverse("broker_statement_export", args=[self.broker.id, "xlsx"]) + f"?month={sale.sale_date:%Y-%m}"

        def headers(response):
            sheet = load_workbook(BytesIO(response.content))["Trucks"]
            return [cell.value for cell in sheet[5]]

        self.assertNotIn("Profit / loss", headers(self.client.get(url)))
        self.assertIn("Profit / loss", headers(self.client.get(url + "&internal=1")))

    def test_invoice_pdf_shows_what_the_party_pays_after_freight(self):
        sale = self.make_truck()
        response = self.client.get(reverse("sale_invoice_pdf", args=[sale.id]))
        self.assertEqual(response.status_code, 200)

    # ---- dashboard advice ----

    def test_dashboard_reminds_to_record_an_old_unloading(self):
        from core.services.dashboard import mill_dues, receivables
        from core.services.insights import reminders

        today = timezone.localdate()
        sale = self.make_truck(sale_date=(today - timedelta(days=4)).isoformat())
        Sale.objects.filter(pk=sale.pk).update(sale_date=today - timedelta(days=9))
        items = reminders(self.company, today, receivables(self.company, today), mill_dues(self.company))
        self.assertIn(f"unload-{sale.id}", [item["id"] for item in items])

    def test_dashboard_compares_brokers_per_kg(self):
        from core.services.insights import profit_tips

        cheap = Broker.objects.create(company=self.company, broker_name="Ravi Chopra",
                                      commission_type="per_kg", commission_rate=Decimal("0.10"))
        for rate, broker in (("29.00", self.broker), ("29.00", self.broker), ("27.00", cheap), ("27.00", cheap)):
            self.make_truck(**{"broker": broker.id, "items-0-bag_count": "100", "items-0-rate_per_kg": rate,
                               "vehicle_number": f"T-{broker.id}-{rate}-{Sale.objects.count()}"})
        today = timezone.localdate()
        tips = profit_tips(self.company, today - timedelta(days=30), today, today)
        broker_tip = next(t for t in tips if t["icon"] == "🤝")
        self.assertIn("Gopal Bajaj", broker_tip["title"])     # better per kg
        self.assertIn("Ravi Chopra", broker_tip["title"])

    def test_pulse_has_four_lights_and_dashboard_renders(self):
        from core.services.insights import pulse

        self.settle(self.make_truck())
        today = timezone.localdate()
        lights = pulse(self.company, today.replace(day=1), today, today)
        self.assertEqual([light["key"] for light in lights], ["margin", "collect", "overdue", "stock"])
        page = self.client.get(reverse("dashboard") + "?period=fy")
        self.assertContains(page, "Ways to increase profit")
        self.assertContains(page, "Reminders")
