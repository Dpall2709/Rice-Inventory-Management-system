"""
Tests for scanning a supplier's bill into the purchase form.

The Claude call is replaced by a fake here - these tests never use the network.
"""

import base64
import io
import json
import shutil
import tempfile
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.models import Mill, Product, Purchase
from core.services.bill_scan import build_draft, parse_qr
from core.tests import make_company

MEDIA = tempfile.mkdtemp(prefix="bill-scan-tests-")


def einvoice_qr(**data):
    """A QR string shaped like a GST portal signed e-invoice (signature not real)."""
    payload = {
        "SellerGstin": "10ABCDE1234F1Z5",
        "BuyerGstin": "10PQRSX6789K1Z2",
        "DocNo": "SRM/245",
        "DocTyp": "INV",
        "DocDt": "15/09/2026",
        "TotInvVal": 315000,
        "ItemCnt": 1,
        "MainHsnCode": "1006",
        "Irn": "a" * 64,
        "IrnDt": "2026-09-15 10:00:00",
    }
    payload.update(data)

    def part(obj):
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")

    return ".".join([part({"alg": "RS256"}), part({"data": json.dumps(payload), "iss": "NIC"}), "c2lnbmF0dXJl"])


AI_RESULT = {
    "is_bill": True,
    "supplier": {"name": "Satya Rice Mill Pvt Ltd", "gstin": "10ABCDE1234F1Z5", "mobile": "9876543210",
                 "address": "Mill Road", "city": "Lakhisarai", "state": "Bihar"},
    "buyer_name": "Sigma Rice", "buyer_gstin": "",
    "bill_number": "SRM/245", "bill_date": "2026-09-15", "tax_type": "cgst_sgst",
    "lines": [{"description": "Katarni Rice 50kg bags", "hsn": "1006", "bag_weight_kg": 50,
               "bag_count": 200, "quantity_kg": 10000, "rate_per_kg": 30, "gst_percent": 5,
               "amount": 300000}],
    "discount": None, "freight": 2000, "labour": None, "cgst": 7500, "sgst": 7500, "igst": None,
    "round_off": None, "grand_total": 317000,
    "warnings": ["Rate was Rs 3,000 per quintal, converted to 30.00 per kg"],
}


def tiny_png():
    from PIL import Image

    out = io.BytesIO()
    Image.new("RGB", (20, 20), "white").save(out, format="PNG")
    return out.getvalue()


@override_settings(MEDIA_ROOT=MEDIA)
class BillScanTests(TestCase):

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA, ignore_errors=True)

    def setUp(self):
        self.company, self.user = make_company("Sigma Rice", "sigma_user")
        self.company.state = "Bihar"
        self.company.save()
        self.client.login(username="sigma_user", password="TestPass#2026")
        self.mill = Mill.objects.create(company=self.company, mill_name="Satya Rice Mill",
                                        mobile="9876543210", gst_number="10ABCDE1234F1Z5")
        self.product = Product.objects.create(company=self.company, rice_name="Katarni",
                                              hsn_code="1006", gst_percent=5)

    # ---- QR parsing ------------------------------------------------------

    def test_einvoice_qr_is_understood(self):
        qr = parse_qr(einvoice_qr())
        self.assertEqual(qr["kind"], "einvoice")
        self.assertEqual(qr["seller_gstin"], "10ABCDE1234F1Z5")
        self.assertEqual(qr["bill_number"], "SRM/245")
        self.assertEqual(qr["bill_date"], "2026-09-15")
        self.assertEqual(qr["grand_total"], "315000")
        self.assertEqual(qr["seller_state"], "Bihar")

    def test_upi_qr_is_understood(self):
        qr = parse_qr("upi://pay?pa=satya@sbi&pn=Satya%20Rice%20Mill&am=1500.50&cu=INR")
        self.assertEqual(qr["kind"], "upi")
        self.assertEqual(qr["payee_name"], "Satya Rice Mill")
        self.assertEqual(qr["grand_total"], "1500.50")

    def test_unknown_qr_text_is_kept_as_text(self):
        self.assertEqual(parse_qr("hello world")["kind"], "text")
        self.assertIsNone(parse_qr(""))

    # ---- matching --------------------------------------------------------

    def test_supplier_matched_by_gstin_and_rice_by_name(self):
        draft = build_draft(self.company, ai=AI_RESULT)
        self.assertEqual(draft["mill_id"], self.mill.id)
        self.assertEqual(draft["lines"][0]["product_id"], self.product.id)
        self.assertEqual(draft["lines"][0]["bag_count"], 200)
        self.assertEqual(draft["lines"][0]["rate"], "30.00")

    def test_supplier_matched_by_name_without_pvt_ltd(self):
        self.mill.gst_number = ""
        self.mill.save()
        ai = dict(AI_RESULT, supplier=dict(AI_RESULT["supplier"], gstin=""))
        self.assertEqual(build_draft(self.company, ai=ai)["mill_id"], self.mill.id)

    def test_bags_worked_out_from_quintals(self):
        line = dict(AI_RESULT["lines"][0], bag_count=None, bag_weight_kg=50, quantity_kg=5000)
        draft = build_draft(self.company, ai=dict(AI_RESULT, lines=[line]))
        self.assertEqual(draft["lines"][0]["bag_count"], 100)

    def test_bill_made_out_to_someone_else_is_flagged(self):
        self.company.gst_number = "10AAAAA1111A1Z1"
        self.company.save()
        draft = build_draft(self.company, qr=parse_qr(einvoice_qr()))
        self.assertTrue(any("not your GSTIN" in w for w in draft["warnings"]))

    # ---- the screens -----------------------------------------------------

    def test_scan_page_opens(self):
        self.assertEqual(self.client.get(reverse("scan_purchase_bill")).status_code, 200)

    def test_qr_only_fills_the_header(self):
        response = self.client.post(reverse("scan_purchase_bill"), {"qr_text": einvoice_qr()})
        self.assertRedirects(response, reverse("add_purchase") + "?scan=1", fetch_redirect_response=False)

        page = self.client.get(reverse("add_purchase") + "?scan=1")
        self.assertContains(page, 'value="SRM/245"')
        self.assertContains(page, "Filled from the scanned bill")
        self.assertEqual(page.context["form"].initial["mill"], self.mill.id)
        self.assertEqual(str(page.context["form"].initial["purchase_date"]), "2026-09-15")

    @mock.patch("core.view.purchase.scan.ai_enabled", return_value=True)
    @mock.patch("core.view.purchase.scan.read_bill_with_ai", return_value=AI_RESULT)
    def test_photo_fills_lines_and_is_attached_on_save(self, _read, _enabled):
        upload = SimpleUploadedFile("bill.png", tiny_png(), content_type="image/png")
        self.client.post(reverse("scan_purchase_bill"), {"qr_text": einvoice_qr(), "bill": upload})

        page = self.client.get(reverse("add_purchase") + "?scan=1")
        formset = page.context["formset"]
        self.assertEqual(formset.forms[0].initial["product"], self.product.id)
        self.assertEqual(formset.forms[0].initial["bag_count"], 200)
        self.assertEqual(page.context["form"].initial["transport_amount"], "2000.00")

        data = {
            "scan": "1", "mill": self.mill.id, "invoice_no": "SRM/245", "purchase_date": "2026-09-15",
            "tax_type": "cgst_sgst", "discount_amount": "0", "notes": "", "amount_paid_now": "",
            "payment_mode": "", "transport_amount": "", "labour_amount": "", "expense_other": "",
            "expense_other_note": "",
            "purchaseitem_set-TOTAL_FORMS": "1", "purchaseitem_set-INITIAL_FORMS": "0",
            "purchaseitem_set-MIN_NUM_FORMS": "0", "purchaseitem_set-MAX_NUM_FORMS": "1000",
            "purchaseitem_set-0-product": self.product.id, "purchaseitem_set-0-bag_weight": "50",
            "purchaseitem_set-0-bag_count": "200", "purchaseitem_set-0-purchase_price": "30",
            "purchaseitem_set-0-gst_percent": "5",
        }
        response = self.client.post(reverse("add_purchase"), data)
        self.assertEqual(response.status_code, 302)

        purchase = Purchase.objects.get(invoice_no="SRM/245")
        self.assertTrue(purchase.bill_file)
        self.assertEqual(purchase.entry_source, "qr+ai")
        self.assertEqual(purchase.irn, "a" * 64)
        self.assertNotIn("purchase_scan_draft", self.client.session)

        # The owner can open the original bill; another company cannot.
        self.assertEqual(self.client.get(reverse("purchase_bill_file", args=[purchase.id])).status_code, 200)
        make_company("Tau Rice", "tau_user")
        self.client.logout()
        self.client.login(username="tau_user", password="TestPass#2026")
        self.assertEqual(self.client.get(reverse("purchase_bill_file", args=[purchase.id])).status_code, 404)

    def test_new_supplier_can_be_added_from_the_scan(self):
        qr = einvoice_qr(SellerGstin="10ZZZZZ9999Z1Z9")
        session = self.client.session
        session["purchase_scan_draft"] = build_draft(
            self.company, qr=parse_qr(qr),
            ai=dict(AI_RESULT, supplier=dict(AI_RESULT["supplier"], name="Naya Mill", gstin="10ZZZZZ9999Z1Z9")),
        )
        session.save()

        self.client.post(reverse("scan_add_supplier"), {"mill_name": "Naya Mill", "mobile": "9123456789"})
        mill = Mill.objects.get(company=self.company, mill_name="Naya Mill")
        self.assertEqual(mill.gst_number, "10ZZZZZ9999Z1Z9")
        self.assertEqual(self.client.session["purchase_scan_draft"]["mill_id"], mill.id)

    @mock.patch("core.view.purchase.scan.ai_enabled", return_value=False)
    def test_photo_without_ai_and_without_qr_explains_why(self, _enabled):
        upload = SimpleUploadedFile("bill.png", tiny_png(), content_type="image/png")
        response = self.client.post(reverse("scan_purchase_bill"), {"bill": upload})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "ANTHROPIC_API_KEY")

    def test_nothing_given_is_refused(self):
        response = self.client.post(reverse("scan_purchase_bill"), {})
        self.assertContains(response, "Scan the QR code or choose a photo")

    def test_unrelated_qr_is_refused(self):
        response = self.client.post(reverse("scan_purchase_bill"), {"qr_text": "https://example.com"})
        self.assertContains(response, "not a GST e-invoice")

    def test_discard_clears_the_draft(self):
        self.client.post(reverse("scan_purchase_bill"), {"qr_text": einvoice_qr()})
        self.client.get(reverse("discard_scan"))
        self.assertNotIn("purchase_scan_draft", self.client.session)
