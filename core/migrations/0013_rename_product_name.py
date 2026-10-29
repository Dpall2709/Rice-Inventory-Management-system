from django.db import migrations


class Migration(migrations.Migration):
    """The product name is no longer rice-specific."""

    dependencies = [
        ("core", "0012_broker_collection"),
    ]

    operations = [
        migrations.RenameField(model_name="product", old_name="rice_name", new_name="name"),
    ]
