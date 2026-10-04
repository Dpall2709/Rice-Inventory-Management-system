"""
Create the starter set of subscription plans.

    python manage.py seed_plans

Safe to run more than once: it updates the plans instead of duplicating them.
Change the prices here to whatever you decide to charge.
"""

from django.core.management.base import BaseCommand

from billing.models import Plan

PLANS = [
    {
        "code": "monthly",
        "name": "Monthly",
        "price": 499,
        "billing_period": "monthly",
        "duration_days": 30,
        "max_users": 3,
        "sort_order": 1,
        "features": "Purchases, sales and GST invoices\nMill and stock reports\n3 users\nEmail support",
    },
    {
        "code": "quarterly",
        "name": "Quarterly",
        "price": 1299,
        "billing_period": "quarterly",
        "duration_days": 90,
        "max_users": 5,
        "sort_order": 2,
        "features": "Everything in Monthly\n5 users\nSave 13% against monthly\nWhatsApp support",
    },
    {
        "code": "yearly",
        "name": "Yearly",
        "price": 4499,
        "billing_period": "yearly",
        "duration_days": 365,
        "max_users": 0,
        "sort_order": 3,
        "features": "Everything in Quarterly\nUnlimited users\nSave 25% against monthly\nPriority support",
    },
]


class Command(BaseCommand):
    help = "Create or update the default subscription plans."

    def handle(self, *args, **options):
        for data in PLANS:
            plan, created = Plan.objects.update_or_create(
                code=data["code"],
                defaults=data,
            )
            word = "Created" if created else "Updated"
            self.stdout.write(self.style.SUCCESS(f"{word} plan: {plan.name} - Rs {plan.price}"))
