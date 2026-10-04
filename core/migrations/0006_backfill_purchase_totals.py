"""
Fill the new purchase fields for bills that were entered before GST existed.

Those bills recorded only `total_amount` (bags x weight x rate), with no tax.
So they are marked as "No GST" and their goods value is taken as the taxable
amount - which keeps every old total exactly as it was.
"""

from decimal import Decimal

from django.db import migrations


def backfill(apps, schema_editor):
    Purchase = apps.get_model("core", "Purchase")
    PurchaseItem = apps.get_model("core", "PurchaseItem")

    for purchase in Purchase.objects.all():
        goods = Decimal("0")

        for item in PurchaseItem.objects.filter(purchase=purchase):
            item.total_kg = Decimal(item.bag_count or 0) * Decimal(item.bag_weight or 0)
            item.taxable_amount = item.total_kg * Decimal(item.purchase_price or 0)
            item.gst_percent = Decimal("0")
            item.gst_amount = Decimal("0")
            item.line_total = item.taxable_amount
            item.save(update_fields=[
                "total_kg", "taxable_amount", "gst_percent", "gst_amount", "line_total",
            ])
            goods += item.taxable_amount

        purchase.goods_amount = goods
        purchase.taxable_amount = goods
        purchase.tax_type = "none"          # no tax was recorded on these bills

        # Keep the stored total if it was already set; otherwise use the goods value.
        if not purchase.total_amount:
            purchase.total_amount = goods

        if not purchase.purchase_ref:
            date_part = purchase.purchase_date.strftime("%Y%m%d")
            purchase.purchase_ref = f"PUR-{date_part}-{purchase.id:04d}"

        purchase.save(update_fields=[
            "goods_amount", "taxable_amount", "tax_type", "total_amount", "purchase_ref",
        ])


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0005_alter_purchase_options_purchase_cgst_amount_and_more"),
    ]

    operations = [
        migrations.RunPython(backfill, noop),
    ]
