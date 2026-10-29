from collections import Counter

from django.db import migrations


def forwards(apps, schema_editor):
    """
    Existing companies are rice traders: give them the default units, mark
    their products as "bag, priced per kg", and use the bag size they buy most
    as each product's pack size.
    """
    from core.services.catalog import seed_company_catalog

    Company = apps.get_model("core", "Company")
    Unit = apps.get_model("core", "Unit")
    ProductCategory = apps.get_model("core", "ProductCategory")
    Product = apps.get_model("core", "Product")
    PurchaseItem = apps.get_model("core", "PurchaseItem")

    for company in Company.objects.all():
        has_products = Product.objects.filter(company=company).exists()
        if has_products and company.industry == "general":
            company.industry = "rice"
            company.save(update_fields=["industry"])

        units = seed_company_catalog(company, Unit, ProductCategory)
        rice = ProductCategory.objects.filter(company=company, name="Rice").first()

        for product in Product.objects.filter(company=company):
            sizes = Counter(
                PurchaseItem.objects.filter(product=product).values_list("bag_weight", flat=True)
            )
            product.unit = units["Bag"]
            product.rate_unit = units["Kilogram"]
            product.default_pack_size = sizes.most_common(1)[0][0] if sizes else 50
            if rice and not product.category_id:
                product.category = rice
            product.save(update_fields=["unit", "rate_unit", "default_pack_size", "category"])


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0014_generic_products_freight_gst"),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
