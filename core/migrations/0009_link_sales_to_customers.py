"""
Bring sales made before the Customer link up to date.

Old sales stored the buyer as typed text. For each one:
  - link it to the company's customer with the same name (ignoring case),
    creating that customer if none exists, so every sale shows in a ledger;
  - fill the new per-line GST figures and the CGST/SGST split from the old
    single GST rate on the sale;
  - store the bag count on the sale header.

Nothing is deleted and no amount the customer was billed is changed.
"""

from decimal import Decimal

from django.db import migrations


def forwards(apps, schema_editor):
    Sale = apps.get_model("core", "Sale")
    SaleItem = apps.get_model("core", "SaleItem")
    Customer = apps.get_model("core", "Customer")

    for sale in Sale.objects.filter(customer__isnull=True).order_by("id"):
        name = (sale.customer_name or "").strip() or "Walk-in customer"

        customer = (
            Customer.objects
            .filter(company_id=sale.company_id, customer_name__iexact=name)
            .order_by("id")
            .first()
        )
        if customer is None:
            customer = Customer.objects.create(
                company_id=sale.company_id,
                customer_name=name,
                gst_number=(sale.customer_gst or "").strip().upper(),
            )

        sale.customer_id = customer.id
        if not sale.billing_address:
            parts = [customer.billing_address, customer.city, customer.state, customer.pincode]
            sale.billing_address = ", ".join(p.strip() for p in parts if p and p.strip())
        if not sale.shipping_address:
            sale.shipping_address = (customer.shipping_address or "").strip() or sale.billing_address
        if not sale.place_of_supply:
            sale.place_of_supply = customer.state or ""

        gst = Decimal(sale.gst_amount or 0)
        if gst > 0:
            sale.tax_type = "cgst_sgst"
            sale.cgst_amount = (gst / 2).quantize(Decimal("0.01"))
            sale.sgst_amount = gst - sale.cgst_amount
        else:
            sale.tax_type = "none"

        items = list(SaleItem.objects.filter(sale_id=sale.id))
        sale.total_bags = sum(int(item.bag_count or 0) for item in items)

        for item in items:
            item.gst_percent = sale.gst_percent or 0
            kg = Decimal(item.bag_count or 0) * Decimal(item.bag_weight or 0)
            item.total_weight = kg
            item.amount = (kg * Decimal(item.rate_per_kg or 0)).quantize(Decimal("0.01"))
            item.gst_amount = (item.amount * Decimal(item.gst_percent) / 100).quantize(Decimal("0.01"))
            item.line_total = item.amount + item.gst_amount
            item.save()

        sale.save()


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0008_sale_customer_broker_lots"),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
