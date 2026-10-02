"""Page-structure checks that are easy to break while restyling templates."""

from django.test import TestCase
from django.urls import reverse

from core.tests import make_company


class FormLayoutTests(TestCase):

    def setUp(self):
        self.company, self.user = make_company("Upsilon Rice", "upsilon_user")
        self.client.login(username="upsilon_user", password="TestPass#2026")

    def test_sale_form_renders_each_field_once(self):
        # `field.name in '...'` is a substring test: "customer" matched
        # "transport_paid_by_customer" and the customer dropdown appeared twice,
        # so the empty second copy could override the first on save.
        page = self.client.get(reverse("add_sale")).content.decode()
        self.assertEqual(page.count('name="customer"'), 1)
        self.assertEqual(page.count('name="broker"'), 1)

    def test_purchase_form_renders_each_field_once(self):
        page = self.client.get(reverse("add_purchase")).content.decode()
        self.assertEqual(page.count('name="mill"'), 1)
        self.assertEqual(page.count('name="payment_mode"'), 1)


class AuthPageTests(TestCase):

    def test_login_signup_and_reset_pages_render(self):
        for name in ("login", "register", "password_reset"):
            with self.subTest(page=name):
                page = self.client.get(reverse(name))
                self.assertEqual(page.status_code, 200)
                self.assertContains(page, "core/style.css")       # same theme as the app
                self.assertContains(page, "data-toggle-theme")    # dark mode switch
                self.assertContains(page, 'class="lang-switch"')  # English / Hindi

    def test_failed_login_keeps_the_username(self):
        page = self.client.post(reverse("login"), {"username": "someone", "password": "wrong"})
        self.assertContains(page, 'value="someone"')
