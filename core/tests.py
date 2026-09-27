"""
Tests for the rules that protect the product and its customers.

Run them with:  python manage.py test

These cover the three things that must never break in a multi-company SaaS:

    1. one company can never see or touch another company's data
    2. an expired subscription can read but not write
    3. each company gets its own invoice number series
"""

from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from billing.models import Plan, Subscription, SubscriptionPayment
from billing.services import start_trial, subscription_for
from core.models import Company, Mill, Payment, Product, Purchase, PurchaseItem, UserProfile
from core.services.costing import line_costing, product_costing, purchase_costing
from core.services.invoice_number import next_sale_invoice_no
from core.services.ledger import mill_statement


MILL_POST = {
    "mill_name": "Test Mill",
    "owner_name": "Owner",
    "mobile": "9876543210",
    "gst_number": "",
    "address": "",
    "city": "",
    "state": "",
    "opening_balance": "0",
    "notes": "",
}


def mill_post(**overrides):
    """Valid POST data for the mill form."""
    data = dict(MILL_POST)
    data.update(overrides)
    return data


def make_company(name, username, role="owner"):
    """A company with one user, on a fresh trial."""
    company = Company.objects.create(
        company_name=name,
        owner_name=f"{name} Owner",
        email=f"{username}@example.com",
        mobile="9999999999",
        subscription_start=timezone.localdate(),
        subscription_end=timezone.localdate(),
    )
    user = User.objects.create_user(username=username, password="TestPass#2026")
    UserProfile.objects.create(user=user, company=company, role=role)
    start_trial(company)
    return company, user


class TenantIsolationTests(TestCase):
    """Company A must never reach company B's rows."""

    def setUp(self):
        self.company_a, self.user_a = make_company("Alpha Rice", "alpha")
        self.company_b, self.user_b = make_company("Beta Rice", "beta")

        self.mill_b = Mill.objects.create(
            company=self.company_b, mill_name="Beta Mill", mobile="1111111111"
        )
        self.client.login(username="alpha", password="TestPass#2026")

    def test_cannot_open_another_companys_mill_report(self):
        response = self.client.get(reverse("mill_report_detail", args=[self.mill_b.id]))
        self.assertEqual(response.status_code, 404)

    def test_cannot_export_another_companys_ledger_to_excel(self):
        # This one used to leak: the Excel export had no company filter.
        response = self.client.get(reverse("mill_report_excel", args=[self.mill_b.id]))
        self.assertEqual(response.status_code, 404)

    def test_cannot_export_another_companys_ledger_to_pdf(self):
        response = self.client.get(reverse("mill_report_pdf", args=[self.mill_b.id]))
        self.assertEqual(response.status_code, 404)

    def test_cannot_edit_or_delete_another_companys_mill(self):
        self.assertEqual(
            self.client.get(reverse("edit_mill", args=[self.mill_b.id])).status_code, 404
        )
        self.assertEqual(
            self.client.post(reverse("delete_mill", args=[self.mill_b.id])).status_code, 404
        )
        self.assertTrue(Mill.objects.filter(id=self.mill_b.id).exists())

    def test_list_pages_show_only_own_rows(self):
        Mill.objects.create(company=self.company_a, mill_name="Alpha Mill", mobile="2222222222")
        response = self.client.get(reverse("mill_list"))
        self.assertContains(response, "Alpha Mill")
        self.assertNotContains(response, "Beta Mill")

    def test_for_company_manager_scopes_queries(self):
        Mill.objects.create(company=self.company_a, mill_name="Alpha Mill", mobile="3333333333")
        self.assertEqual(Mill.objects.for_company(self.company_a).count(), 1)
        self.assertEqual(Mill.objects.for_company(self.company_b).count(), 1)
        self.assertEqual(Mill.objects.count(), 2)

    def test_for_company_on_child_models_follows_the_parent(self):
        # PurchaseItem and SaleItem have no company column of their own.
        self.assertEqual(Product.objects.for_company(self.company_a).count(), 0)


class SubscriptionTests(TestCase):
    """Trial, expiry, read-only mode and renewal."""

    def setUp(self):
        self.company, self.user = make_company("Gamma Rice", "gamma")
        self.client.login(username="gamma", password="TestPass#2026")
        self.plan = Plan.objects.create(
            name="Monthly", code="monthly", price=499, duration_days=30
        )

    def test_new_company_starts_on_a_trial(self):
        subscription = subscription_for(self.company)
        self.assertEqual(subscription.status, Subscription.TRIAL)
        self.assertGreater(subscription.days_left, 0)

    def expire(self):
        subscription = subscription_for(self.company)
        subscription.end_date = timezone.localdate() - timedelta(days=1)
        subscription.save()
        return subscription

    def test_expired_company_can_still_read(self):
        self.expire()
        self.assertEqual(self.client.get(reverse("mill_list")).status_code, 200)
        self.assertEqual(self.client.get(reverse("sale_list")).status_code, 200)

    def test_expired_company_cannot_write(self):
        self.expire()
        response = self.client.post(
            reverse("add_mill"), mill_post(mill_name="Should Not Save")
        )
        self.assertRedirects(response, reverse("billing:home"))
        self.assertFalse(Mill.objects.filter(mill_name="Should Not Save").exists())

    def test_active_company_can_write(self):
        response = self.client.post(
            reverse("add_mill"), mill_post(mill_name="Should Save")
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Mill.objects.filter(mill_name="Should Save").exists())

    def test_renewal_extends_from_the_current_end_date(self):
        subscription = subscription_for(self.company)
        old_end = subscription.end_date

        subscription.extend(days=30, plan=self.plan)

        self.assertEqual(subscription.end_date, old_end + timedelta(days=30))
        self.assertEqual(subscription.status, Subscription.ACTIVE)
        # The legacy Company fields are kept in step.
        self.company.refresh_from_db()
        self.assertEqual(self.company.subscription_end, subscription.end_date)

    def test_renewal_after_expiry_starts_from_today(self):
        subscription = self.expire()
        subscription.extend(days=30, plan=self.plan)
        self.assertEqual(subscription.end_date, timezone.localdate() + timedelta(days=30))

    def test_billing_page_opens(self):
        response = self.client.get(reverse("billing:home"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Monthly")


class RolePermissionTests(TestCase):
    """Staff may enter data; only owners and managers may delete."""

    def setUp(self):
        self.company, self.owner = make_company("Delta Rice", "delta_owner")

        self.staff_user = User.objects.create_user(
            username="delta_staff", password="TestPass#2026"
        )
        UserProfile.objects.create(
            user=self.staff_user, company=self.company, role="staff"
        )

        self.mill = Mill.objects.create(
            company=self.company, mill_name="Delta Mill", mobile="4444444444"
        )

    def test_staff_cannot_delete(self):
        self.client.login(username="delta_staff", password="TestPass#2026")
        response = self.client.post(
            reverse("delete_mill", args=[self.mill.id]), {"action": "delete"}
        )
        self.assertRedirects(response, reverse("dashboard"))
        self.assertTrue(Mill.objects.filter(id=self.mill.id).exists())

    def test_staff_can_add(self):
        self.client.login(username="delta_staff", password="TestPass#2026")
        response = self.client.post(
            reverse("add_mill"), mill_post(mill_name="Added By Staff")
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Mill.objects.filter(mill_name="Added By Staff").exists())

    def test_owner_can_delete_an_unused_mill(self):
        self.client.login(username="delta_owner", password="TestPass#2026")
        self.client.post(reverse("delete_mill", args=[self.mill.id]), {"action": "delete"})
        self.assertFalse(Mill.objects.filter(id=self.mill.id).exists())

    def test_owner_can_deactivate(self):
        self.client.login(username="delta_owner", password="TestPass#2026")
        self.client.post(reverse("delete_mill", args=[self.mill.id]), {"action": "deactivate"})
        self.mill.refresh_from_db()
        self.assertFalse(self.mill.is_active)

    def test_staff_cannot_reach_checkout(self):
        self.client.login(username="delta_staff", password="TestPass#2026")
        response = self.client.get(reverse("billing:checkout", args=["monthly"]))
        self.assertEqual(response.status_code, 302)


class InvoiceNumberTests(TestCase):
    """Each company runs its own invoice series."""

    def setUp(self):
        self.company_a, _ = make_company("Epsilon Rice", "epsilon")
        self.company_b, _ = make_company("Zeta Rice", "zeta")

    def test_each_company_starts_at_one(self):
        today = timezone.localdate().strftime("%Y%m%d")
        self.assertEqual(next_sale_invoice_no(self.company_a), f"SAL-{today}-0001")
        self.assertEqual(next_sale_invoice_no(self.company_b), f"SAL-{today}-0001")

    def test_numbers_increase_without_gaps(self):
        today = timezone.localdate().strftime("%Y%m%d")
        numbers = [next_sale_invoice_no(self.company_a) for _ in range(3)]
        self.assertEqual(
            numbers,
            [f"SAL-{today}-0001", f"SAL-{today}-0002", f"SAL-{today}-0003"],
        )

    def test_company_can_use_its_own_prefix(self):
        self.company_a.invoice_prefix = "EPS"
        self.company_a.save()
        self.assertTrue(next_sale_invoice_no(self.company_a).startswith("EPS-"))


class StaffScreenTests(TestCase):
    """The owner-of-the-product screens are not reachable by tenants."""

    def setUp(self):
        self.company, self.user = make_company("Eta Rice", "eta")
        self.plan = Plan.objects.create(
            name="Monthly", code="monthly", price=499, duration_days=30
        )

    def test_tenant_cannot_open_the_manage_screen(self):
        self.client.login(username="eta", password="TestPass#2026")
        response = self.client.get(reverse("billing:manage_companies"))
        self.assertNotEqual(response.status_code, 200)

    def test_staff_can_extend_a_subscription_manually(self):
        admin = User.objects.create_user(
            username="root", password="TestPass#2026", is_staff=True, is_superuser=True
        )
        UserProfile.objects.create(user=admin, company=self.company, role="owner")
        self.client.login(username="root", password="TestPass#2026")

        response = self.client.post(
            reverse("billing:extend_subscription", args=[self.company.id]),
            {"plan_code": "monthly", "note": "Paid by UPI"},
        )
        self.assertRedirects(response, reverse("billing:manage_companies"))

        # Re-read from the database: the in-memory Company still holds the
        # subscription object as it looked before the extend.
        subscription = Subscription.objects.get(company=self.company)
        self.assertEqual(subscription.status, Subscription.ACTIVE)
        self.assertEqual(subscription.plan, self.plan)
        self.assertGreater(subscription.days_left, 25)
        self.assertTrue(
            SubscriptionPayment.objects.filter(
                company=self.company, status=SubscriptionPayment.PAID
            ).exists()
        )


class MillModuleTests(TestCase):
    """The supplier module: validation, balances, soft delete, restore."""

    def setUp(self):
        self.company, self.user = make_company("Theta Rice", "theta")
        self.client.login(username="theta", password="TestPass#2026")

        self.mill = Mill.objects.create(
            company=self.company,
            mill_name="Satya Rice Mill",
            owner_name="Ramesh",
            mobile="9876543210",
            opening_balance=1000,
        )

    # ---------------- form validation ----------------

    def post_mill(self, **overrides):
        data = {
            "mill_name": "New Mill",
            "owner_name": "Owner",
            "mobile": "9876500000",
            "gst_number": "",
            "address": "",
            "city": "",
            "state": "",
            "opening_balance": "0",
            "notes": "",
        }
        data.update(overrides)
        return self.client.post(reverse("add_mill"), data)

    def test_valid_mill_is_created(self):
        response = self.post_mill(mill_name="Balaji Mill")
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Mill.objects.filter(company=self.company, mill_name="Balaji Mill").exists())

    def test_letters_are_rejected_as_a_mobile_number(self):
        response = self.post_mill(mobile="not-a-number")
        self.assertEqual(response.status_code, 200)   # form redisplayed with the error
        self.assertContains(response, "10-digit mobile")
        self.assertFalse(Mill.objects.filter(mill_name="New Mill").exists())

    def test_mobile_with_country_code_is_accepted_and_trimmed(self):
        self.post_mill(mill_name="Prefix Mill", mobile="+91 98765 11111")
        mill = Mill.objects.get(mill_name="Prefix Mill")
        self.assertEqual(mill.mobile, "9876511111")

    def test_bad_gst_number_is_rejected(self):
        response = self.post_mill(gst_number="INVALID123")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "does not look like a GST number")

    def test_good_gst_number_is_stored_uppercase(self):
        self.post_mill(mill_name="GST Mill", gst_number="10abcde1234f1z5")
        self.assertEqual(Mill.objects.get(mill_name="GST Mill").gst_number, "10ABCDE1234F1Z5")

    def test_duplicate_name_in_same_company_is_rejected(self):
        response = self.post_mill(mill_name="satya rice mill")   # different case
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "already have a supplier with this name")

    def test_same_name_allowed_in_a_different_company(self):
        other_company, other_user = make_company("Iota Rice", "iota")
        self.client.login(username="iota", password="TestPass#2026")
        response = self.post_mill(mill_name="Satya Rice Mill")
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Mill.objects.filter(company=other_company, mill_name="Satya Rice Mill").exists())

    def test_negative_opening_balance_is_rejected(self):
        response = self.post_mill(opening_balance="-500")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "cannot be negative")

    def test_non_numeric_opening_balance_does_not_crash(self):
        response = self.post_mill(opening_balance="abcd")
        self.assertEqual(response.status_code, 200)   # used to be a 500

    # ---------------- balances on the list ----------------

    def test_list_shows_opening_plus_purchases_minus_payments(self):
        purchase = Purchase.objects.create(
            company=self.company, mill=self.mill, invoice_no="P-1",
            purchase_date=timezone.localdate(), total_amount=5000,
        )
        Payment.objects.create(
            company=self.company, related_type="purchase", mill=self.mill,
            purchase=purchase, amount=2000, payment_mode="Cash",
            payment_date=timezone.localdate(),
        )

        from core.view.mill.mill_list import mill_queryset

        row = mill_queryset(self.company).get(pk=self.mill.pk)
        self.assertEqual(row.purchased, 5000)
        self.assertEqual(row.paid, 2000)
        self.assertEqual(row.balance, 4000)      # 1000 opening + 5000 - 2000

        response = self.client.get(reverse("mill_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Satya Rice Mill")

    def test_search_filters_the_list(self):
        Mill.objects.create(company=self.company, mill_name="Balaji Mill", mobile="9000000000")

        response = self.client.get(reverse("mill_list"), {"q": "balaji"})
        self.assertContains(response, "Balaji Mill")
        self.assertNotContains(response, "Satya Rice Mill")

    # ---------------- soft delete ----------------

    def test_mill_with_purchases_cannot_be_deleted(self):
        Purchase.objects.create(
            company=self.company, mill=self.mill, invoice_no="P-2",
            purchase_date=timezone.localdate(), total_amount=100,
        )

        response = self.client.post(reverse("delete_mill", args=[self.mill.id]), {"action": "delete"})

        self.mill.refresh_from_db()
        self.assertTrue(Mill.objects.filter(pk=self.mill.pk).exists())
        self.assertTrue(self.mill.is_active)      # not even deactivated
        self.assertEqual(response.status_code, 302)

    def test_deactivate_keeps_the_history(self):
        Purchase.objects.create(
            company=self.company, mill=self.mill, invoice_no="P-3",
            purchase_date=timezone.localdate(), total_amount=100,
        )

        self.client.post(reverse("delete_mill", args=[self.mill.id]), {"action": "deactivate"})

        self.mill.refresh_from_db()
        self.assertFalse(self.mill.is_active)
        self.assertEqual(Purchase.objects.filter(mill=self.mill).count(), 1)

    def test_inactive_mill_is_hidden_from_the_list_and_from_the_purchase_form(self):
        self.mill.is_active = False
        self.mill.save()

        response = self.client.get(reverse("mill_list"))
        self.assertNotContains(response, "Satya Rice Mill")

        response = self.client.get(reverse("mill_list"), {"status": "inactive"})
        self.assertContains(response, "Satya Rice Mill")

        response = self.client.get(reverse("add_purchase"))
        self.assertNotContains(response, "Satya Rice Mill")

    def test_unused_mill_can_be_deleted(self):
        response = self.client.post(reverse("delete_mill", args=[self.mill.id]), {"action": "delete"})
        self.assertRedirects(response, reverse("mill_list"))
        self.assertFalse(Mill.objects.filter(pk=self.mill.pk).exists())

    def test_restore_brings_a_mill_back(self):
        self.mill.is_active = False
        self.mill.save()

        self.client.post(reverse("restore_mill", args=[self.mill.id]))

        self.mill.refresh_from_db()
        self.assertTrue(self.mill.is_active)

    def test_another_company_cannot_deactivate_my_mill(self):
        make_company("Kappa Rice", "kappa")
        self.client.login(username="kappa", password="TestPass#2026")

        response = self.client.post(reverse("delete_mill", args=[self.mill.id]), {"action": "deactivate"})
        self.assertEqual(response.status_code, 404)

        self.mill.refresh_from_db()
        self.assertTrue(self.mill.is_active)

    def test_whatsapp_number_adds_the_country_code(self):
        self.assertEqual(self.mill.whatsapp_number, "919876543210")


class PurchaseGstTests(TestCase):
    """The money maths on a purchase bill."""

    def setUp(self):
        self.company, self.user = make_company("Lambda Rice", "lambda_user")
        self.client.login(username="lambda_user", password="TestPass#2026")

        self.mill = Mill.objects.create(
            company=self.company, mill_name="GST Mill", mobile="9876543210"
        )
        self.product = Product.objects.create(
            company=self.company, rice_name="Basmati", hsn_code="1006", gst_percent=5
        )

    def bill(self, **overrides):
        """A valid purchase POST: 200 bags x 50kg at 30/kg = 3,00,000."""
        data = {
            "mill": self.mill.id,
            "invoice_no": "MILL-001",
            "purchase_date": timezone.localdate().isoformat(),
            "tax_type": "cgst_sgst",
            "discount_amount": "0",
            "transport_amount": "",
            "labour_amount": "",
            "expense_other": "",
            "expense_other_note": "",
            "notes": "",
            "amount_paid_now": "",
            "payment_mode": "",
            "purchaseitem_set-TOTAL_FORMS": "1",
            "purchaseitem_set-INITIAL_FORMS": "0",
            "purchaseitem_set-MIN_NUM_FORMS": "0",
            "purchaseitem_set-MAX_NUM_FORMS": "1000",
            "purchaseitem_set-0-product": self.product.id,
            "purchaseitem_set-0-bag_weight": "50",
            "purchaseitem_set-0-bag_count": "200",
            "purchaseitem_set-0-purchase_price": "30",
            "purchaseitem_set-0-gst_percent": "5",
        }
        data.update(overrides)
        return data

    def test_cgst_sgst_split(self):
        self.client.post(reverse("add_purchase"), self.bill())

        purchase = Purchase.objects.get(invoice_no="MILL-001")
        self.assertEqual(purchase.goods_amount, Decimal("300000.00"))
        self.assertEqual(purchase.taxable_amount, Decimal("300000.00"))
        self.assertEqual(purchase.cgst_amount, Decimal("7500.00"))   # 2.5%
        self.assertEqual(purchase.sgst_amount, Decimal("7500.00"))   # 2.5%
        self.assertEqual(purchase.igst_amount, Decimal("0.00"))
        self.assertEqual(purchase.total_amount, Decimal("315000.00"))

    def test_igst_goes_in_one_line(self):
        self.client.post(reverse("add_purchase"), self.bill(tax_type="igst"))

        purchase = Purchase.objects.get(invoice_no="MILL-001")
        self.assertEqual(purchase.igst_amount, Decimal("15000.00"))
        self.assertEqual(purchase.cgst_amount, Decimal("0.00"))
        self.assertEqual(purchase.total_amount, Decimal("315000.00"))

    def test_no_gst_bill_charges_no_tax(self):
        self.client.post(reverse("add_purchase"), self.bill(tax_type="none"))

        purchase = Purchase.objects.get(invoice_no="MILL-001")
        self.assertEqual(purchase.gst_amount, Decimal("0.00"))
        self.assertEqual(purchase.total_amount, Decimal("300000.00"))

        item = purchase.purchaseitem_set.first()
        self.assertEqual(item.gst_percent, Decimal("0.00"))   # rate cleared too

    def test_discount_is_applied_before_gst(self):
        self.client.post(reverse("add_purchase"), self.bill(discount_amount="10000"))

        purchase = Purchase.objects.get(invoice_no="MILL-001")
        self.assertEqual(purchase.taxable_amount, Decimal("290000.00"))
        self.assertEqual(purchase.gst_amount, Decimal("14500.00"))       # 5% of 2,90,000
        self.assertEqual(purchase.total_amount, Decimal("304500.00"))

    def test_mill_charged_freight_and_labour_are_added_after_gst(self):
        self.client.post(reverse("add_purchase"), self.bill(
            transport_amount="5000", transport_by_mill="on",
            labour_amount="2000", labour_by_mill="on",
        ))

        purchase = Purchase.objects.get(invoice_no="MILL-001")
        self.assertEqual(purchase.gst_amount, Decimal("15000.00"))       # unchanged by charges
        self.assertEqual(purchase.total_amount, Decimal("322000.00"))    # 3,15,000 + 7,000

    def test_totals_are_rounded_to_whole_rupees(self):
        # 7 bags x 50kg x 33.33 = 11,665.50 + 5% = 12,248.775 -> 12,249
        self.client.post(reverse("add_purchase"), self.bill(**{
            "purchaseitem_set-0-bag_count": "7",
            "purchaseitem_set-0-purchase_price": "33.33",
        }))

        purchase = Purchase.objects.get(invoice_no="MILL-001")
        self.assertEqual(purchase.total_amount, Decimal("12249.00"))
        self.assertNotEqual(purchase.round_off, Decimal("0.00"))

    def test_line_values_are_stored_on_the_item(self):
        self.client.post(reverse("add_purchase"), self.bill())

        item = PurchaseItem.objects.get(purchase__invoice_no="MILL-001")
        self.assertEqual(item.total_kg, Decimal("10000.00"))
        self.assertEqual(item.taxable_amount, Decimal("300000.00"))
        self.assertEqual(item.gst_amount, Decimal("15000.00"))
        self.assertEqual(item.line_total, Decimal("315000.00"))

    def test_two_lines_split_the_discount_by_value(self):
        second = Product.objects.create(
            company=self.company, rice_name="Sona", hsn_code="1006", gst_percent=5
        )
        self.client.post(reverse("add_purchase"), self.bill(**{
            "purchaseitem_set-TOTAL_FORMS": "2",
            "purchaseitem_set-1-product": second.id,
            "purchaseitem_set-1-bag_weight": "50",
            "purchaseitem_set-1-bag_count": "100",
            "purchaseitem_set-1-purchase_price": "30",
            "purchaseitem_set-1-gst_percent": "5",
            "discount_amount": "3000",
        }))

        purchase = Purchase.objects.get(invoice_no="MILL-001")
        first, other = purchase.purchaseitem_set.order_by("id")

        # 3,00,000 and 1,50,000 -> the discount splits 2:1
        self.assertEqual(first.taxable_amount, Decimal("298000.00"))
        self.assertEqual(other.taxable_amount, Decimal("149000.00"))
        self.assertEqual(purchase.taxable_amount, Decimal("447000.00"))

    # ---------------- the bill itself ----------------

    def test_our_own_reference_is_generated(self):
        self.client.post(reverse("add_purchase"), self.bill())

        purchase = Purchase.objects.get(invoice_no="MILL-001")
        self.assertTrue(purchase.purchase_ref.startswith("PUR-"))

    def test_same_bill_number_from_same_mill_is_refused(self):
        self.client.post(reverse("add_purchase"), self.bill())
        response = self.client.post(reverse("add_purchase"), self.bill())

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "already has bill")
        self.assertEqual(Purchase.objects.filter(invoice_no="MILL-001").count(), 1)

    def test_same_bill_number_from_a_different_mill_is_fine(self):
        other_mill = Mill.objects.create(
            company=self.company, mill_name="Second Mill", mobile="9876500000"
        )
        self.client.post(reverse("add_purchase"), self.bill())
        self.client.post(reverse("add_purchase"), self.bill(mill=other_mill.id))

        self.assertEqual(Purchase.objects.filter(invoice_no="MILL-001").count(), 2)

    def test_future_dated_bill_is_refused(self):
        future = (timezone.localdate() + timedelta(days=3)).isoformat()
        response = self.client.post(reverse("add_purchase"), self.bill(purchase_date=future))

        self.assertContains(response, "cannot be in the future")
        self.assertFalse(Purchase.objects.filter(invoice_no="MILL-001").exists())

    def test_bill_with_no_lines_is_refused(self):
        response = self.client.post(reverse("add_purchase"), self.bill(**{
            "purchaseitem_set-0-product": "",
            "purchaseitem_set-0-bag_count": "",
            "purchaseitem_set-0-purchase_price": "",
        }))

        self.assertContains(response, "at least one rice line")
        self.assertFalse(Purchase.objects.filter(invoice_no="MILL-001").exists())

    def test_letters_in_quantity_do_not_crash(self):
        response = self.client.post(reverse("add_purchase"), self.bill(**{
            "purchaseitem_set-0-bag_count": "abc",
        }))
        self.assertEqual(response.status_code, 200)     # a form error, not a 500

    def test_payment_entered_with_the_bill_is_recorded(self):
        self.client.post(reverse("add_purchase"), self.bill(
            amount_paid_now="50000", payment_mode="UPI"
        ))

        purchase = Purchase.objects.get(invoice_no="MILL-001")
        payment = Payment.objects.get(purchase=purchase)

        self.assertEqual(payment.amount, Decimal("50000.00"))
        self.assertEqual(payment.payment_mode, "UPI")
        self.assertEqual(payment.related_type, "purchase")
        self.assertEqual(purchase.paid_amount, Decimal("50000.00"))
        self.assertEqual(purchase.due_amount, Decimal("265000.00"))

    def test_paid_amount_without_a_mode_is_refused(self):
        response = self.client.post(reverse("add_purchase"), self.bill(amount_paid_now="5000"))
        self.assertContains(response, "Choose how you paid")

    def test_a_bill_with_payments_cannot_be_deleted(self):
        self.client.post(reverse("add_purchase"), self.bill(
            amount_paid_now="1000", payment_mode="Cash"
        ))
        purchase = Purchase.objects.get(invoice_no="MILL-001")

        self.client.post(reverse("delete_purchase", args=[purchase.id]))

        self.assertTrue(Purchase.objects.filter(pk=purchase.pk).exists())

    def test_another_company_cannot_open_my_bill(self):
        self.client.post(reverse("add_purchase"), self.bill())
        purchase = Purchase.objects.get(invoice_no="MILL-001")

        make_company("Mu Rice", "mu_user")
        self.client.login(username="mu_user", password="TestPass#2026")

        self.assertEqual(
            self.client.get(reverse("purchase_detail", args=[purchase.id])).status_code, 404
        )
        self.assertEqual(
            self.client.get(reverse("edit_purchase", args=[purchase.id])).status_code, 404
        )

    def test_stock_comes_from_purchase_lines(self):
        self.client.post(reverse("add_purchase"), self.bill())

        response = self.client.get(reverse("product_report", args=[self.product.id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "200")      # 200 bags now in stock


class CostingTests(TestCase):
    """Landed cost per kg, and the selling price it implies."""

    def setUp(self):
        self.company, self.user = make_company("Nu Rice", "nu_user")
        self.company.default_margin_percent = 10
        self.company.save()
        self.client.login(username="nu_user", password="TestPass#2026")

        self.mill = Mill.objects.create(
            company=self.company, mill_name="Cost Mill", mobile="9876543210"
        )
        self.product = Product.objects.create(
            company=self.company, rice_name="Sona Masoori", hsn_code="1006", gst_percent=5
        )

    def make_bill(self, **overrides):
        """100 bags x 50kg at 30/kg = 1,50,000 goods, 5000 kg."""
        data = {
            "mill": self.mill.id,
            "invoice_no": "COST-1",
            "purchase_date": timezone.localdate().isoformat(),
            "tax_type": "cgst_sgst",
            "discount_amount": "0",
            "transport_amount": "",
            "labour_amount": "",
            "expense_other": "",
            "expense_other_note": "",
            "margin_percent": "10",
            "notes": "",
            "amount_paid_now": "",
            "payment_mode": "",
            "purchaseitem_set-TOTAL_FORMS": "1",
            "purchaseitem_set-INITIAL_FORMS": "0",
            "purchaseitem_set-MIN_NUM_FORMS": "0",
            "purchaseitem_set-MAX_NUM_FORMS": "1000",
            "purchaseitem_set-0-product": self.product.id,
            "purchaseitem_set-0-bag_weight": "50",
            "purchaseitem_set-0-bag_count": "100",
            "purchaseitem_set-0-purchase_price": "30",
            "purchaseitem_set-0-gst_percent": "5",
        }
        data.update(overrides)
        self.client.post(reverse("add_purchase"), data)
        return Purchase.objects.get(invoice_no="COST-1")

    def test_own_expenses_are_saved_but_not_owed_to_the_mill(self):
        purchase = self.make_bill(transport_amount="4000", labour_amount="1000")

        # The mill is owed only goods + GST.
        self.assertEqual(purchase.total_amount, Decimal("157500.00"))
        self.assertEqual(purchase.own_expense_total, Decimal("5000.00"))
        self.assertEqual(purchase.expenses.count(), 2)

    def test_cost_per_kg_includes_your_expenses(self):
        purchase = self.make_bill(transport_amount="4000", labour_amount="1000")
        costing = purchase_costing(purchase)

        # 1,50,000 goods + 5,000 expenses = 1,55,000 over 5,000 kg
        self.assertEqual(costing["landed_cost"], Decimal("155000.00"))
        self.assertEqual(costing["bill_rate_per_kg"], Decimal("30.00"))
        self.assertEqual(costing["cost_per_kg"], Decimal("31.00"))
        self.assertEqual(costing["extra_per_kg"], Decimal("1.00"))

    def test_gst_is_left_out_of_the_cost(self):
        purchase = self.make_bill()
        costing = purchase_costing(purchase)

        # GST of 7,500 is claimable, so cost stays at the goods value.
        self.assertEqual(costing["landed_cost"], Decimal("150000.00"))
        self.assertEqual(costing["cost_per_kg"], Decimal("30.00"))
        self.assertEqual(costing["gst_excluded"], Decimal("7500.00"))

    def test_suggested_selling_price_uses_the_margin(self):
        purchase = self.make_bill(transport_amount="5000")
        costing = purchase_costing(purchase, margin_percent=10)

        self.assertEqual(costing["cost_per_kg"], Decimal("31.00"))
        self.assertEqual(costing["suggested_per_kg"], Decimal("34.10"))
        self.assertEqual(costing["suggested_per_bag"], Decimal("1705.00"))   # 50 kg bag
        self.assertEqual(costing["profit_per_kg"], Decimal("3.10"))
        self.assertEqual(costing["profit_on_this_bill"], Decimal("15500.00"))

    def test_mill_charges_count_as_cost_too(self):
        purchase = self.make_bill(
            transport_amount="2500", transport_by_mill="on",
            labour_amount="2500", labour_by_mill="on",
        )
        costing = purchase_costing(purchase)

        self.assertEqual(costing["mill_charges"], Decimal("5000.00"))
        self.assertEqual(costing["cost_per_kg"], Decimal("31.00"))
        # ...and those two ARE owed to the mill, unlike your own expenses
        self.assertEqual(purchase.total_amount, Decimal("162500.00"))

    def test_expenses_are_shared_between_rice_types_by_value(self):
        cheap = Product.objects.create(
            company=self.company, rice_name="Cheap Rice", hsn_code="1006", gst_percent=5
        )
        purchase = self.make_bill(**{
            "transport_amount": "6000",
            "purchaseitem_set-TOTAL_FORMS": "2",
            "purchaseitem_set-1-product": cheap.id,
            "purchaseitem_set-1-bag_weight": "50",
            "purchaseitem_set-1-bag_count": "100",
            "purchaseitem_set-1-purchase_price": "10",
            "purchaseitem_set-1-gst_percent": "5",
        })

        rows = {row["product"].rice_name: row for row in line_costing(purchase)}

        # 1,50,000 and 50,000 -> the 6,000 transport splits 3:1
        self.assertEqual(rows["Sona Masoori"]["share_of_expenses"], Decimal("4500.00"))
        self.assertEqual(rows["Cheap Rice"]["share_of_expenses"], Decimal("1500.00"))
        self.assertEqual(rows["Sona Masoori"]["cost_per_kg"], Decimal("30.90"))
        self.assertEqual(rows["Cheap Rice"]["cost_per_kg"], Decimal("10.30"))

    def test_expense_can_be_added_after_the_bill(self):
        purchase = self.make_bill()

        self.client.post(reverse("add_purchase_expense", args=[purchase.id]), {
            "category": "transport",
            "amount": "3000",
            "paid_to": "Sharma Transport",
            "expense_date": timezone.localdate().isoformat(),
        })

        purchase.refresh_from_db()
        self.assertEqual(purchase.own_expense_total, Decimal("3000.00"))
        self.assertEqual(purchase_costing(purchase)["cost_per_kg"], Decimal("30.60"))

    def test_expense_can_be_removed(self):
        purchase = self.make_bill(transport_amount="3000")
        expense = purchase.expenses.first()

        self.client.post(reverse("delete_purchase_expense", args=[purchase.id, expense.id]))

        purchase.refresh_from_db()
        self.assertEqual(purchase.own_expense_total, 0)

    def test_product_cost_averages_across_bills(self):
        self.make_bill(transport_amount="5000")
        self.make_bill(invoice_no="COST-2", **{
            "purchaseitem_set-0-purchase_price": "40",
            "transport_amount": "0",
        })

        costing = product_costing(self.company, self.product)

        # 5,000 kg at a landed 31.00 and 5,000 kg at 40.00
        self.assertEqual(costing["total_kg_bought"], Decimal("10000.00"))
        self.assertEqual(costing["cost_per_kg"], Decimal("35.50"))
        self.assertEqual(costing["suggested_per_kg"], Decimal("39.05"))

    def test_another_company_cannot_add_an_expense_to_my_bill(self):
        purchase = self.make_bill()
        make_company("Xi Rice", "xi_user")
        self.client.login(username="xi_user", password="TestPass#2026")

        response = self.client.post(reverse("add_purchase_expense", args=[purchase.id]), {
            "category": "transport", "amount": "1000",
        })

        self.assertEqual(response.status_code, 404)
        purchase.refresh_from_db()
        self.assertEqual(purchase.own_expense_total, 0)


class ChargeOwnershipTests(TestCase):
    """The tick box decides whether a charge is owed to the mill or is your cost."""

    def setUp(self):
        self.company, self.user = make_company("Omicron Rice", "omicron")
        self.client.login(username="omicron", password="TestPass#2026")

        self.mill = Mill.objects.create(
            company=self.company, mill_name="Tick Mill", mobile="9876543210"
        )
        self.product = Product.objects.create(
            company=self.company, rice_name="IR64", hsn_code="1006", gst_percent=0
        )

    def bill(self, **overrides):
        """100 bags x 50kg at 20/kg = 1,00,000, no GST for simple numbers."""
        data = {
            "mill": self.mill.id,
            "invoice_no": "TICK-1",
            "purchase_date": timezone.localdate().isoformat(),
            "tax_type": "none",
            "discount_amount": "0",
            "transport_amount": "",
            "labour_amount": "",
            "expense_other": "",
            "expense_other_note": "",
            "margin_percent": "10",
            "notes": "",
            "amount_paid_now": "",
            "payment_mode": "",
            "purchaseitem_set-TOTAL_FORMS": "1",
            "purchaseitem_set-INITIAL_FORMS": "0",
            "purchaseitem_set-MIN_NUM_FORMS": "0",
            "purchaseitem_set-MAX_NUM_FORMS": "1000",
            "purchaseitem_set-0-product": self.product.id,
            "purchaseitem_set-0-bag_weight": "50",
            "purchaseitem_set-0-bag_count": "100",
            "purchaseitem_set-0-purchase_price": "20",
            "purchaseitem_set-0-gst_percent": "0",
        }
        data.update(overrides)
        self.client.post(reverse("add_purchase"), data)
        return Purchase.objects.get(invoice_no=data["invoice_no"])

    def test_unticked_transport_stays_out_of_the_mill_bill(self):
        purchase = self.bill(transport_amount="6000")

        # The mill is owed the rice only.
        self.assertEqual(purchase.total_amount, Decimal("100000.00"))
        self.assertEqual(purchase.freight_charge, Decimal("0.00"))

        # ...but it is recorded as your expense and counted in the cost.
        self.assertEqual(purchase.own_expense_total, Decimal("6000.00"))
        self.assertEqual(purchase_costing(purchase)["cost_per_kg"], Decimal("21.20"))

    def test_ticked_transport_is_added_to_the_mill_bill(self):
        purchase = self.bill(transport_amount="6000", transport_by_mill="on")

        self.assertEqual(purchase.freight_charge, Decimal("6000.00"))
        self.assertEqual(purchase.total_amount, Decimal("106000.00"))
        self.assertEqual(purchase.own_expense_total, 0)

        # Either way the rice costs the same to you.
        self.assertEqual(purchase_costing(purchase)["cost_per_kg"], Decimal("21.20"))

    def test_one_ticked_one_not(self):
        purchase = self.bill(
            transport_amount="6000", transport_by_mill="on", labour_amount="2000"
        )

        self.assertEqual(purchase.total_amount, Decimal("106000.00"))   # rice + mill transport
        self.assertEqual(purchase.own_expense_total, Decimal("2000.00"))  # your labour

        costing = purchase_costing(purchase)
        self.assertEqual(costing["mill_charges"], Decimal("6000.00"))
        self.assertEqual(costing["own_expenses"], Decimal("2000.00"))
        self.assertEqual(costing["landed_cost"], Decimal("108000.00"))
        self.assertEqual(costing["cost_per_kg"], Decimal("21.60"))

    def test_editing_can_move_a_charge_from_you_to_the_mill(self):
        purchase = self.bill(transport_amount="6000")
        self.assertEqual(purchase.own_expense_total, Decimal("6000.00"))

        item = purchase.purchaseitem_set.first()
        self.client.post(reverse("edit_purchase", args=[purchase.id]), {
            "mill": self.mill.id,
            "invoice_no": "TICK-1",
            "purchase_date": purchase.purchase_date.isoformat(),
            "tax_type": "none",
            "discount_amount": "0",
            "transport_amount": "6000",
            "transport_by_mill": "on",
            "labour_amount": "",
            "expense_other": "",
            "expense_other_note": "",
            "margin_percent": "10",
            "notes": "",
            "amount_paid_now": "",
            "payment_mode": "",
            "purchaseitem_set-TOTAL_FORMS": "1",
            "purchaseitem_set-INITIAL_FORMS": "1",
            "purchaseitem_set-MIN_NUM_FORMS": "0",
            "purchaseitem_set-MAX_NUM_FORMS": "1000",
            "purchaseitem_set-0-id": item.id,
            "purchaseitem_set-0-purchase": purchase.id,
            "purchaseitem_set-0-product": self.product.id,
            "purchaseitem_set-0-bag_weight": "50",
            "purchaseitem_set-0-bag_count": "100",
            "purchaseitem_set-0-purchase_price": "20",
            "purchaseitem_set-0-gst_percent": "0",
        })

        purchase.refresh_from_db()
        self.assertEqual(purchase.freight_charge, Decimal("6000.00"))
        self.assertEqual(purchase.total_amount, Decimal("106000.00"))
        self.assertEqual(purchase.own_expense_total, 0)      # no longer your expense


class PaymentAllocationTests(TestCase):
    """Money paid to a mill must reach the bills it settles."""

    def setUp(self):
        self.company, self.user = make_company("Pi Rice", "pi_user")
        self.client.login(username="pi_user", password="TestPass#2026")

        self.mill = Mill.objects.create(
            company=self.company, mill_name="Ledger Mill", mobile="9876543210"
        )
        self.product = Product.objects.create(
            company=self.company, rice_name="IR64", hsn_code="1006", gst_percent=0
        )

    def add_bill(self, invoice_no, amount, days_ago=0):
        purchase = Purchase.objects.create(
            company=self.company, mill=self.mill, invoice_no=invoice_no,
            purchase_date=timezone.localdate() - timedelta(days=days_ago),
            tax_type="none", goods_amount=amount, taxable_amount=amount,
            total_amount=amount,
        )
        PurchaseItem.objects.create(
            purchase=purchase, product=self.product, bag_weight=50,
            bag_count=int(amount / 1000), purchase_price=20,
            total_kg=int(amount / 1000) * 50, taxable_amount=amount, line_total=amount,
        )
        return purchase

    def pay(self, amount, purchase=None):
        return Payment.objects.create(
            company=self.company, related_type="purchase", mill=self.mill,
            purchase=purchase, amount=amount, payment_mode="UPI",
            payment_date=timezone.localdate(),
        )

    def test_payment_to_the_mill_reaches_the_oldest_bill(self):
        old = self.add_bill("OLD-1", Decimal("100000"), days_ago=10)
        new = self.add_bill("NEW-1", Decimal("50000"), days_ago=1)

        self.pay(Decimal("60000"))          # no bill named

        statement = mill_statement(self.company, self.mill)
        rows = {row["purchase"].invoice_no: row for row in statement["rows"]}

        self.assertEqual(rows["OLD-1"]["paid"], Decimal("60000"))
        self.assertEqual(rows["OLD-1"]["due"], Decimal("40000"))
        self.assertEqual(rows["NEW-1"]["paid"], Decimal("0"))
        self.assertEqual(rows["NEW-1"]["due"], Decimal("50000"))

    def test_invoice_dues_add_up_to_the_mill_balance(self):
        self.add_bill("A", Decimal("441000"))
        self.pay(Decimal("100000"), purchase=Purchase.objects.get(invoice_no="A"))
        self.pay(Decimal("100000"))         # to the mill, not the bill

        statement = mill_statement(self.company, self.mill)

        self.assertEqual(statement["total_paid"], Decimal("200000"))
        self.assertEqual(statement["total_due"], Decimal("241000"))
        self.assertEqual(statement["rows"][0]["paid"], Decimal("200000"))
        self.assertEqual(statement["rows"][0]["due"], Decimal("241000"))
        self.assertEqual(
            sum(row["due"] for row in statement["rows"]), statement["total_due"]
        )

    def test_opening_balance_is_settled_before_any_bill(self):
        self.mill.opening_balance = Decimal("30000")
        self.mill.save()
        self.add_bill("B", Decimal("50000"))

        self.pay(Decimal("40000"))

        statement = mill_statement(self.company, self.mill)
        self.assertEqual(statement["opening_paid"], Decimal("30000"))
        self.assertEqual(statement["opening_due"], Decimal("0"))
        self.assertEqual(statement["rows"][0]["paid"], Decimal("10000"))
        self.assertEqual(statement["total_due"], Decimal("40000"))

    def test_paying_more_than_everything_shows_as_advance(self):
        self.add_bill("C", Decimal("20000"))
        self.pay(Decimal("50000"))

        statement = mill_statement(self.company, self.mill)
        self.assertEqual(statement["rows"][0]["due"], Decimal("0"))
        self.assertEqual(statement["advance"], Decimal("30000"))
        self.assertEqual(statement["total_due"], Decimal("0"))

    def test_the_ledger_page_shows_the_applied_payment(self):
        purchase = self.add_bill("D", Decimal("100000"))
        self.pay(Decimal("40000"))

        response = self.client.get(reverse("mill_report_detail", args=[self.mill.id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "on account")

    def test_purchase_detail_counts_on_account_money(self):
        purchase = self.add_bill("E", Decimal("100000"))
        self.pay(Decimal("40000"))

        response = self.client.get(reverse("purchase_detail", args=[purchase.id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "applied automatically")
        self.assertContains(response, "Paid directly")
        self.assertContains(response, "Applied from other payments")


class ExportTests(TestCase):
    """The PDF and Excel statements must build for real data."""

    def setUp(self):
        self.company, self.user = make_company("Rho Rice", "rho_user")
        self.client.login(username="rho_user", password="TestPass#2026")

        self.mill = Mill.objects.create(
            company=self.company, mill_name="Export Mill", mobile="9876543210",
            owner_name="Owner", gst_number="10ABCDE1234F1Z5", city="Patna",
        )
        product = Product.objects.create(
            company=self.company, rice_name="Basmati", hsn_code="1006", gst_percent=5
        )
        purchase = Purchase.objects.create(
            company=self.company, mill=self.mill, invoice_no="EXP-1",
            purchase_date=timezone.localdate(), tax_type="cgst_sgst",
            goods_amount=Decimal("300000"), taxable_amount=Decimal("300000"),
            cgst_amount=Decimal("7500"), sgst_amount=Decimal("7500"),
            total_amount=Decimal("315000"),
        )
        PurchaseItem.objects.create(
            purchase=purchase, product=product, bag_weight=50, bag_count=200,
            purchase_price=30, gst_percent=5, total_kg=10000,
            taxable_amount=Decimal("300000"), gst_amount=Decimal("15000"),
            line_total=Decimal("315000"),
        )
        Payment.objects.create(
            company=self.company, related_type="purchase", mill=self.mill,
            amount=Decimal("100000"), payment_mode="UPI",
            payment_date=timezone.localdate(),
        )

    def test_pdf_statement_builds(self):
        response = self.client.get(reverse("mill_report_pdf", args=[self.mill.id]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertTrue(response.content.startswith(b"%PDF"))
        self.assertGreater(len(response.content), 3000)

    def test_excel_statement_builds_with_four_sheets(self):
        from io import BytesIO

        from openpyxl import load_workbook

        response = self.client.get(reverse("mill_report_excel", args=[self.mill.id]))
        self.assertEqual(response.status_code, 200)

        workbook = load_workbook(BytesIO(response.content))
        self.assertEqual(workbook.sheetnames, ["Summary", "Ledger", "Purchase bills", "Payments"])

        summary = {row[0]: row[1] for row in workbook["Summary"].iter_rows(values_only=True) if row[0]}
        self.assertEqual(summary["Supplier"], "Export Mill")
        self.assertEqual(summary["Total purchased"], Decimal("315000"))
        self.assertEqual(summary["Balance due"], Decimal("215000"))

    def test_another_company_cannot_download_my_statement(self):
        make_company("Sigma Rice", "sigma_user")
        self.client.login(username="sigma_user", password="TestPass#2026")

        self.assertEqual(
            self.client.get(reverse("mill_report_pdf", args=[self.mill.id])).status_code, 404
        )
        self.assertEqual(
            self.client.get(reverse("mill_report_excel", args=[self.mill.id])).status_code, 404
        )


class SettlementAndHistoryTests(TestCase):
    """A settled supplier stays settled, and its history stays visible."""

    def setUp(self):
        self.company, self.user = make_company("Tau Rice", "tau_user")
        self.client.login(username="tau_user", password="TestPass#2026")
        self.mill = Mill.objects.create(
            company=self.company, mill_name="History Mill", mobile="9876543210"
        )
        self.product = Product.objects.create(
            company=self.company, rice_name="IR64", hsn_code="1006", gst_percent=0
        )

    def bill(self, invoice_no, amount, days_ago=0):
        purchase = Purchase.objects.create(
            company=self.company, mill=self.mill, invoice_no=invoice_no,
            purchase_date=timezone.localdate() - timedelta(days=days_ago),
            tax_type="none", goods_amount=amount, taxable_amount=amount, total_amount=amount,
        )
        PurchaseItem.objects.create(
            purchase=purchase, product=self.product, bag_weight=50, bag_count=10,
            purchase_price=20, total_kg=500, taxable_amount=amount, line_total=amount,
        )
        return purchase

    def pay(self, amount, purchase=None, days_ago=0):
        return Payment.objects.create(
            company=self.company, related_type="purchase", mill=self.mill,
            purchase=purchase, amount=amount, payment_mode="Cash",
            payment_date=timezone.localdate() - timedelta(days=days_ago),
        )

    # ---------------- the bug from the Deepak Rice Mill data ----------------

    def test_overpaying_one_bill_settles_the_others(self):
        first = self.bill("01", Decimal("750000"), days_ago=3)
        second = self.bill("02", Decimal("151200"), days_ago=2)
        third = self.bill("03", Decimal("315000"), days_ago=1)

        self.pay(Decimal("100000"))                      # on account
        self.pay(Decimal("1000000"), purchase=second)    # far more than bill 02

        statement = mill_statement(self.company, self.mill)
        rows = {row["purchase"].invoice_no: row for row in statement["rows"]}

        self.assertEqual(rows["02"]["due"], 0)
        self.assertEqual(rows["01"]["due"], 0)                     # got the spill-over
        self.assertEqual(rows["03"]["due"], Decimal("116200"))     # the rest
        self.assertEqual(statement["total_due"], Decimal("116200"))
        self.assertEqual(statement["overpaid_on_bills"], Decimal("848800"))

    def test_paying_more_than_everything_becomes_an_advance(self):
        self.bill("01", Decimal("100000"))
        self.pay(Decimal("250000"))

        statement = mill_statement(self.company, self.mill)
        self.assertEqual(statement["total_due"], 0)
        self.assertEqual(statement["advance"], Decimal("150000"))

    # ---------------- history ----------------

    def test_history_lists_every_bill_and_payment_with_a_running_balance(self):
        first = self.bill("01", Decimal("100000"), days_ago=5)
        self.pay(Decimal("40000"), purchase=first, days_ago=4)
        self.bill("02", Decimal("50000"), days_ago=3)
        self.pay(Decimal("110000"), days_ago=1)          # settles everything

        history = mill_statement(self.company, self.mill)["history"]

        self.assertEqual([h["kind"] for h in history], ["opening", "bill", "payment", "bill", "payment"])
        self.assertEqual([h["balance"] for h in history],
                         [0, Decimal("100000"), Decimal("60000"), Decimal("110000"), Decimal("0")])

    def test_a_settled_supplier_still_shows_its_history(self):
        first = self.bill("01", Decimal("100000"))
        self.pay(Decimal("100000"), purchase=first)

        response = self.client.get(reverse("mill_report_detail", args=[self.mill.id]))

        self.assertContains(response, "Account history")
        self.assertContains(response, "Bill 01")
        self.assertContains(response, "Fully settled")

    # ---------------- the payment screens ----------------

    def test_bill_payment_is_saved_and_named(self):
        purchase = self.bill("01", Decimal("100000"))
        response = self.client.post(reverse("add_purchase_payment", args=[purchase.id]), {
            "amount": "40000", "payment_mode": "UPI",
            "payment_date": timezone.localdate().isoformat(), "notes": "ref 123",
        })

        self.assertRedirects(response, reverse("purchase_detail", args=[purchase.id]))
        payment = Payment.objects.get(purchase=purchase)
        self.assertEqual(payment.amount, Decimal("40000"))
        self.assertEqual(payment.mill, self.mill)
        self.assertEqual(payment.company, self.company)

    def test_letters_in_the_amount_do_not_crash(self):
        purchase = self.bill("01", Decimal("100000"))
        response = self.client.post(reverse("add_purchase_payment", args=[purchase.id]), {
            "amount": "abc", "payment_mode": "UPI",
            "payment_date": timezone.localdate().isoformat(),
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Enter the amount paid")
        self.assertFalse(Payment.objects.exists())

    def test_zero_or_future_payments_are_refused(self):
        purchase = self.bill("01", Decimal("100000"))
        url = reverse("add_purchase_payment", args=[purchase.id])

        self.client.post(url, {"amount": "0", "payment_mode": "Cash",
                               "payment_date": timezone.localdate().isoformat()})
        future = (timezone.localdate() + timedelta(days=2)).isoformat()
        response = self.client.post(url, {"amount": "100", "payment_mode": "Cash",
                                          "payment_date": future})

        self.assertContains(response, "cannot be dated in the future")
        self.assertFalse(Payment.objects.exists())

    def test_nobody_can_pay_into_another_companys_bill(self):
        purchase = self.bill("01", Decimal("100000"))

        make_company("Upsilon Rice", "upsilon")
        self.client.login(username="upsilon", password="TestPass#2026")

        response = self.client.post(reverse("add_purchase_payment", args=[purchase.id]), {
            "amount": "5000", "payment_mode": "Cash",
            "payment_date": timezone.localdate().isoformat(),
        })

        self.assertEqual(response.status_code, 404)
        self.assertFalse(Payment.objects.exists())

    def test_mill_payment_page_shows_what_is_owed(self):
        self.bill("01", Decimal("100000"))
        response = self.client.get(reverse("add_mill_payment", args=[self.mill.id]))
        self.assertContains(response, "You owe History Mill")


class CustomerPageTests(TestCase):
    """The customer edit and delete pages used to crash - their templates were missing."""

    def setUp(self):
        from core.models import Customer

        self.company, self.user = make_company("Phi Rice", "phi_user")
        self.client.login(username="phi_user", password="TestPass#2026")
        self.customer = Customer.objects.create(company=self.company, customer_name="Sharma Traders")

    def test_edit_page_opens(self):
        response = self.client.get(reverse("edit_customer", args=[self.customer.id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Sharma Traders")

    def test_delete_page_opens_and_deactivates(self):
        response = self.client.get(reverse("delete_customer", args=[self.customer.id]))
        self.assertEqual(response.status_code, 200)

        self.client.post(reverse("delete_customer", args=[self.customer.id]))
        self.customer.refresh_from_db()
        self.assertFalse(self.customer.is_active)

    def test_add_page_opens(self):
        self.assertEqual(self.client.get(reverse("add_customer")).status_code, 200)



class BillPaymentExplanationTests(TestCase):
    """A bill must separate what was paid against it from money applied to it."""

    def setUp(self):
        self.company, self.user = make_company("Chi Rice", "chi_user")
        self.client.login(username="chi_user", password="TestPass#2026")
        self.mill = Mill.objects.create(company=self.company, mill_name="Explain Mill", mobile="9876543210")
        self.product = Product.objects.create(company=self.company, rice_name="IR64", hsn_code="1006", gst_percent=0)

    def bill(self, invoice_no, amount):
        purchase = Purchase.objects.create(
            company=self.company, mill=self.mill, invoice_no=invoice_no,
            purchase_date=timezone.localdate(), tax_type="none",
            goods_amount=amount, taxable_amount=amount, total_amount=amount,
        )
        PurchaseItem.objects.create(
            purchase=purchase, product=self.product, bag_weight=50, bag_count=10,
            purchase_price=20, total_kg=500, taxable_amount=amount, line_total=amount,
        )
        return purchase

    def test_overpayment_on_another_bill_is_named(self):
        first = self.bill("A1", Decimal("100000"))
        second = self.bill("B2", Decimal("400000"))

        # 3,00,000 entered against A1, a 1,00,000 bill
        Payment.objects.create(company=self.company, related_type="purchase", mill=self.mill,
                               purchase=first, amount=Decimal("300000"), payment_mode="Cash",
                               payment_date=timezone.localdate())
        Payment.objects.create(company=self.company, related_type="purchase", mill=self.mill,
                               purchase=second, amount=Decimal("100000"), payment_mode="Bank",
                               payment_date=timezone.localdate())

        response = self.client.get(reverse("purchase_detail", args=[second.id]))
        html = response.content.decode()

        # Paid directly: only what was entered against B2
        self.assertEqual(response.context["entered_against_bill"], Decimal("100000"))
        # Applied: the 2,00,000 extra from A1
        self.assertEqual(response.context["applied_from_account"], Decimal("200000"))
        self.assertEqual(response.context["paid"], Decimal("300000"))
        self.assertEqual(response.context["due"], Decimal("100000"))

        self.assertIn("A1", html)                 # the source bill is named
        self.assertIn("more than bill", html)

    def test_form_pages_are_marked_so_back_skips_them(self):
        purchase = self.bill("C3", Decimal("50000"))

        form_page = self.client.get(reverse("add_purchase_payment", args=[purchase.id]))
        self.assertContains(form_page, 'data-nav="form"')

        normal_page = self.client.get(reverse("purchase_detail", args=[purchase.id]))
        self.assertContains(normal_page, 'data-nav="page"')
        # and falls back to its parent, the purchase list
        self.assertContains(normal_page, f'data-back-fallback="{reverse("purchase_list")}"')
