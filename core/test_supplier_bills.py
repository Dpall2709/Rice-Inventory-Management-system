"""Mill / Supplier -> Add purchase bill -> bill history, with per-supplier bill numbers."""

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import Mill, Product, Purchase
from core.services.invoice_number import next_supplier_bill_no
from core.tests import make_company


class SupplierBillTests(TestCase):

    def setUp(self):
        self.company, self.user = make_company("Phi Rice", "phi_user")
        self.client.login(username="phi_user", password="TestPass#2026")
        self.mill_a = Mill.objects.create(company=self.company, mill_name="Supplier A", mobile="9876543210")
        self.mill_b = Mill.objects.create(company=self.company, mill_name="Supplier B", mobile="9876543211")
        self.product = Product.objects.create(company=self.company, rice_name="Katarni", gst_percent=5)

    def bill(self, mill, invoice_no="", **extra):
        data = {
            "mill": mill.id, "invoice_no": invoice_no,
            "purchase_date": timezone.localdate().isoformat(), "tax_type": "cgst_sgst",
            "discount_amount": "0", "transport_amount": "", "labour_amount": "", "expense_other": "",
            "expense_other_note": "", "notes": "", "amount_paid_now": "", "payment_mode": "",
            "purchaseitem_set-TOTAL_FORMS": "1", "purchaseitem_set-INITIAL_FORMS": "0",
            "purchaseitem_set-MIN_NUM_FORMS": "0", "purchaseitem_set-MAX_NUM_FORMS": "1000",
            "purchaseitem_set-0-product": self.product.id, "purchaseitem_set-0-bag_weight": "50",
            "purchaseitem_set-0-bag_count": "10", "purchaseitem_set-0-purchase_price": "30",
            "purchaseitem_set-0-gst_percent": "5",
        }
        data.update(extra)
        return data

    def test_each_supplier_has_its_own_series(self):
        for mill in (self.mill_a, self.mill_a, self.mill_b, self.mill_a, self.mill_b):
            self.client.post(reverse("add_purchase"), self.bill(mill))
        numbers_a = list(Purchase.objects.filter(mill=self.mill_a).order_by("id").values_list("invoice_no", flat=True))
        numbers_b = list(Purchase.objects.filter(mill=self.mill_b).order_by("id").values_list("invoice_no", flat=True))
        self.assertEqual(numbers_a, ["BILL-001", "BILL-002", "BILL-003"])
        self.assertEqual(numbers_b, ["BILL-001", "BILL-002"])

    def test_typed_bill_number_is_kept_and_skipped_by_the_series(self):
        self.client.post(reverse("add_purchase"), self.bill(self.mill_a, invoice_no="BILL-001"))
        self.client.post(reverse("add_purchase"), self.bill(self.mill_a, invoice_no="SRM/245"))
        self.assertEqual(next_supplier_bill_no(self.mill_a), "BILL-002")
        self.assertTrue(Purchase.objects.filter(mill=self.mill_a, invoice_no="SRM/245").exists())

    def test_same_number_twice_for_one_supplier_is_refused(self):
        self.client.post(reverse("add_purchase"), self.bill(self.mill_a, invoice_no="SRM/1"))
        response = self.client.post(reverse("add_purchase"), self.bill(self.mill_a, invoice_no="SRM/1"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Purchase.objects.filter(mill=self.mill_a).count(), 1)

    def test_bill_from_the_supplier_page_is_tied_to_that_supplier(self):
        page = self.client.get(reverse("add_purchase") + f"?mill={self.mill_a.id}")
        self.assertContains(page, "Supplier A")
        self.assertContains(page, 'name="locked_mill"')

        # Even if another supplier is posted, the bill belongs to the locked one.
        data = self.bill(self.mill_b, locked_mill=str(self.mill_a.id))
        response = self.client.post(reverse("add_purchase") + f"?mill={self.mill_a.id}", data)
        self.assertRedirects(response, reverse("mill_report_detail", args=[self.mill_a.id]), fetch_redirect_response=False)
        self.assertEqual(Purchase.objects.get().mill, self.mill_a)

    def test_another_companys_supplier_cannot_be_locked(self):
        other, _user = make_company("Chi Rice", "chi_user")
        foreign = Mill.objects.create(company=other, mill_name="Foreign Mill", mobile="9876543212")
        page = self.client.get(reverse("add_purchase") + f"?mill={foreign.id}")
        self.assertNotContains(page, "Foreign Mill")

    def test_supplier_page_offers_bill_entry_and_history(self):
        self.client.post(reverse("add_purchase"), self.bill(self.mill_a))
        page = self.client.get(reverse("mill_report_detail", args=[self.mill_a.id]))
        self.assertContains(page, f"{reverse('add_purchase')}?mill={self.mill_a.id}")
        self.assertContains(page, "Bill history")
        self.assertContains(page, "BILL-001")

    def test_back_link_goes_one_level_up_and_not_on_dashboard(self):
        page = self.client.get(reverse("mill_report_detail", args=[self.mill_a.id]))
        self.assertContains(page, "data-back")
        self.assertNotContains(self.client.get(reverse("dashboard")), "data-back")
