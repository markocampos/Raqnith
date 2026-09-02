from django.apps import AppConfig
from django.db.models.signals import post_migrate


def auto_seed_default_categories(sender, **kwargs):
    if sender.name != "apps.catalog":
        return
    try:
        from apps.catalog.models import Category

        default_categories = [
            {"name": "Smoke & Test Products", "slug": "smoke-test", "icon": "zap"},
            {"name": "Templates & Themes", "slug": "templates-themes", "icon": "panels-top-left"},
            {"name": "Dev Kits & APIs", "slug": "dev-kits-apis", "icon": "code-xml"},
            {"name": "Software & Tools", "slug": "software-tools", "icon": "terminal"},
            {"name": "Guides & Docs", "slug": "guides-docs", "icon": "book-open"},
            {"name": "Digital Assets & Bundles", "slug": "digital-assets-bundles", "icon": "box"},
        ]
        for cat_data in default_categories:
            cat, created = Category.objects.get_or_create(
                slug=cat_data["slug"],
                defaults={"name": cat_data["name"], "icon": cat_data["icon"]},
            )
            if not created and not cat.icon:
                cat.icon = cat_data["icon"]
                cat.save(update_fields=["icon"])
    except Exception:
        pass


class CatalogConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.catalog"

    def ready(self):
        post_migrate.connect(auto_seed_default_categories, sender=self)
