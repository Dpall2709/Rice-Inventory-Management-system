"""
Tests for the rules that protect the product and its customers.

Run them with:  python manage.py test

These cover the three things that must never break in a multi-company SaaS:

    1. one company can never see or touch another company's data
    2. an expired subscription can read but not write
    3. each company gets its own invoice number series
"""

from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from billing.models import Plan, Subscription, SubscriptionPayment
from billing.services import start_trial, subscription_for
from core.models import Company, Mill, Product, UserProfile
from core.services.invoice_number import next_sale_invoice_no


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
            reverse("add_mill"), {"mill_name": "Should Not Save", "mobile": "1"}
        )
        self.assertRedirects(response, reverse("billing:home"))
        self.assertFalse(Mill.objects.filter(mill_name="Should Not Save").exists())

    def test_active_company_can_write(self):
        response = self.client.post(
            reverse("add_mill"), {"mill_name": "Should Save", "mobile": "1"}
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
        response = self.client.post(reverse("delete_mill", args=[self.mill.id]))
        self.assertRedirects(response, reverse("dashboard"))
        self.assertTrue(Mill.objects.filter(id=self.mill.id).exists())

    def test_staff_can_add(self):
        self.client.login(username="delta_staff", password="TestPass#2026")
        response = self.client.post(
            reverse("add_mill"), {"mill_name": "Added By Staff", "mobile": "1"}
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Mill.objects.filter(mill_name="Added By Staff").exists())

    def test_owner_can_delete(self):
        self.client.login(username="delta_owner", password="TestPass#2026")
        self.client.post(reverse("delete_mill", args=[self.mill.id]))
        self.assertFalse(Mill.objects.filter(id=self.mill.id).exists())

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
