"""Sales, purchases and suppliers lists: filters agree with what the cards show."""

from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import Payment, Purchase
from core.services.periods import date_range, period_chips
from core import test_supplier_bills


class ListScreenTests(TestCase):
    setUp = test_supplier_bills.SupplierBillTests.setUp
    bill = test_supplier_bills.SupplierBillTests.bill

    def add_bills(self, mill, count):
        for _i in range(count):
            self.client.post(reverse("add_purchase"), self.bill(mill))

    def test_money_paid_on_account_counts_in_the_purchase_filter(self):
        self.add_bills(self.mill_a, 1)
        purchase = Purchase.objects.get(mill=self.mill_a)
        # paid to the mill in general, not against the bill
        Payment.objects.create(company=self.company, related_type="purchase", mill=self.mill_a,
                               amount=purchase.total_amount, payment_mode="Bank",
                               payment_date=timezone.localdate())
        unpaid = self.client.get(reverse("purchase_list") + "?status=due")
        self.assertEqual(list(unpaid.context["purchases"]), [])
        settled = self.client.get(reverse("purchase_list") + "?status=paid")
        self.assertEqual([p.id for p in settled.context["purchases"]], [purchase.id])
        self.assertEqual(settled.context["total_due"], Decimal("0"))

    def test_mistyped_dates_do_not_break_the_lists(self):
        for name in ("purchase_list", "sale_list"):
            response = self.client.get(reverse(name) + "?from=31-31-2026&to=abc")
            self.assertEqual(response.status_code, 200)

    def test_first_page_works_with_many_bills(self):
        self.add_bills(self.mill_a, 27)
        page = self.client.get(reverse("purchase_list"))
        self.assertEqual(page.status_code, 200)
        self.assertEqual(len(page.context["purchases"]), 25)
        self.assertEqual(self.client.get(reverse("purchase_list") + "?page=2").status_code, 200)

    def test_supplier_balance_filter(self):
        self.add_bills(self.mill_a, 1)
        owe = self.client.get(reverse("mill_list") + "?balance=owe")
        self.assertEqual([m.id for m in owe.context["mills"]], [self.mill_a.id])
        settled = self.client.get(reverse("mill_list") + "?balance=settled")
        self.assertEqual([m.id for m in settled.context["mills"]], [self.mill_b.id])
        self.assertEqual(owe.context["mills"][0].bill_count, 1)

    def test_lists_render_their_cards_and_filters(self):
        self.add_bills(self.mill_a, 1)
        for name, text in (("purchase_list", "Bill BILL-001"), ("mill_list", "Supplier A"), ("sale_list", "Sale bills")):
            page = self.client.get(reverse(name))
            self.assertContains(page, text)
            self.assertContains(page, "data-filter-form")
        self.assertContains(self.client.get(reverse("purchase_list") + "?mill=1"), "Clear filters")


class PeriodHelperTests(TestCase):

    def test_dates(self):
        from datetime import date
        self.assertEqual(date_range({"from": "2026-10-05", "to": "2026-10-01"}),
                         (date(2026, 10, 1), date(2026, 10, 5)))
        self.assertEqual(date_range({"from": "bad"}), (None, None))
        chips = period_chips(date(2026, 10, 4), None, None)
        self.assertTrue(chips[-1]["active"])   # no dates = All time
        self.assertEqual(chips[2]["from"], date(2026, 9, 1))   # last month
