"""Rename the 'code-2' lucide icon to its official name 'code-xml'.

The lucide package deprecated the 'code-2' alias; existing Category rows
are migrated first so stored values stay valid against the new choices.
"""

from django.db import migrations, models


def forwards(apps, schema_editor):
    Category = apps.get_model("catalog", "Category")
    Category.objects.filter(icon="code-2").update(icon="code-xml")


def backwards(apps, schema_editor):
    Category = apps.get_model("catalog", "Category")
    Category.objects.filter(icon="code-xml").update(icon="code-2")


class Migration(migrations.Migration):

    dependencies = [
        ("catalog", "0007_product_membership_duration_days_and_more"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
        migrations.AlterField(
            model_name="category",
            name="icon",
            field=models.CharField(
                choices=[
                    ("zap", "⚡ Zap (Smoke / Test Products)"),
                    ("panels-top-left", "📐 Layout (Templates / Themes)"),
                    ("code-xml", "💻 Code (Dev Kits / APIs)"),
                    ("terminal", "⌨️ Terminal (Software / Tools)"),
                    ("book-open", "📚 Book (Guides / Docs)"),
                    ("box", "📦 Box (Digital Assets & Bundles)"),
                ],
                default="box",
                help_text="Lucide icon for visual card banners.",
                max_length=50,
            ),
        ),
    ]
