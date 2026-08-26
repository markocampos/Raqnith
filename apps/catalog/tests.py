from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import TestCase
from django.urls import reverse

from apps.catalog.models import Category, Product
from apps.catalog.services.pricing import (
    add_centavos,
    apply_percent_discount,
    percent_of,
    subtract_centavos,
    validate_minimum,
)


class ProductTests(TestCase):
    def test_product_creation(self):
        product = Product.objects.create(name="Widget", slug="widget", price_cents=2500)
        self.assertTrue(product.is_available)
        self.assertEqual(product.price_cents, 2500)

    def test_category_relationship(self):
        category = Category.objects.create(name="Tools", slug="tools")
        product = Product.objects.create(
            name="Hammer", slug="hammer", price_cents=5000, category=category
        )
        self.assertEqual(product.category, category)

    def test_product_slug_unique(self):
        Product.objects.create(name="Widget", slug="widget", price_cents=2500)
        with self.assertRaises(IntegrityError):
            Product.objects.create(name="Other", slug="widget", price_cents=3000)

    def test_negative_price_validation(self):
        product = Product(name="Bad", slug="bad", price_cents=-1)
        with self.assertRaises(ValidationError):
            product.full_clean()

    def test_product_available_by_default(self):
        product = Product.objects.create(name="Widget", slug="widget-2", price_cents=1000)
        self.assertTrue(product.is_available)


class PricingTests(TestCase):
    def test_add_centavos(self):
        self.assertEqual(add_centavos(100, 200, 50), 350)
        self.assertEqual(add_centavos(), 0)

    def test_subtract_centavos(self):
        self.assertEqual(subtract_centavos(500, 200), 300)
        with self.assertRaises(ValueError):
            subtract_centavos(100, 200)

    def test_percent_of_rounding(self):
        self.assertEqual(percent_of(100, 12), 12)
        self.assertEqual(percent_of(999, 10), 100)  # 99.9 -> 100 (half-up)
        self.assertEqual(percent_of(1, 50), 1)
        self.assertEqual(percent_of(1, 49), 0)

    def test_apply_percent_discount(self):
        self.assertEqual(apply_percent_discount(1000, 10), 900)
        self.assertEqual(apply_percent_discount(999, 10), 899)

    def test_validate_minimum(self):
        self.assertEqual(validate_minimum(100), 100)
        with self.assertRaises(ValueError):
            validate_minimum(99)

    def test_money_rejects_float(self):
        with self.assertRaises(ValueError):
            add_centavos(1.5)
        with self.assertRaises(ValueError):
            apply_percent_discount(100.0, 10)


class CatalogViewTests(TestCase):
    def setUp(self):
        self.product = Product.objects.create(
            name="Widget", slug="view-widget", price_cents=2500
        )

    def test_landing_page_renders(self):
        resp = self.client.get(reverse("catalog:home"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Widget")
        self.assertContains(resp, "Digital Products Ready to Download Instantly")

    def test_product_list_renders(self):
        resp = self.client.get(reverse("catalog:product_list"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Widget")

    def test_product_list_category_filtering(self):
        cat1 = Category.objects.create(name="Templates", slug="templates")
        cat2 = Category.objects.create(name="Plugins", slug="plugins")

        p1 = Product.objects.create(name="Theme Kit", slug="theme-kit", price_cents=3000, category=cat1)
        p2 = Product.objects.create(name="Auth Plugin", slug="auth-plugin", price_cents=4000, category=cat2)

        # Filter by templates
        resp = self.client.get(reverse("catalog:product_list"), {"category": "templates"})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Theme Kit")
        self.assertNotContains(resp, "Auth Plugin")

        # Filter by plugins
        resp2 = self.client.get(reverse("catalog:product_list"), {"category": "plugins"})
        self.assertEqual(resp2.status_code, 200)
        self.assertContains(resp2, "Auth Plugin")
        self.assertNotContains(resp2, "Theme Kit")

    def test_product_detail_renders(self):
        resp = self.client.get(reverse("catalog:product_detail", args=["view-widget"]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Widget")
        self.assertContains(resp, "₱25.00")



class CatalogAdminTests(TestCase):
    def setUp(self):
        from django.contrib.auth import get_user_model

        User = get_user_model()
        self.admin = User.objects.create_superuser(
            username="admin",
            email="admin@raqnith.test",
            password="AdminPass123!",
        )
        self.priced = Product.objects.create(
            name="Priced Kit", slug="priced-kit", price_cents=49_900
        )
        self.bare = Product.objects.create(
            name="Bare Kit", slug="bare-kit", price_cents=10_000
        )

    def _login(self):
        self.client.force_login(self.admin)

    def test_changelist_shows_peso_price_and_missing_files(self):
        self._login()
        resp = self.client.get(reverse("admin:catalog_product_changelist"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "\u20b1499.00")
        self.assertContains(resp, "Missing")

    def test_add_product_takes_pesos_stores_centavos(self):
        self._login()
        resp = self.client.post(
            reverse("admin:catalog_product_add"),
            {
                "name": "Pesos Product",
                "slug": "pesos-product",
                "product_type": "digital_download",
                "price": "249.50",
                "description": "Test description for the pesos product.",
                "is_available": "on",
                "files-TOTAL_FORMS": "0",
                "files-INITIAL_FORMS": "0",
                "files-MIN_NUM_FORMS": "0",
                "files-MAX_NUM_FORMS": "1000",
            },
        )
        self.assertEqual(resp.status_code, 302)
        created = Product.objects.get(slug="pesos-product")
        self.assertEqual(created.price_cents, 24_950)

    def test_change_page_prefills_peso_price(self):
        self._login()
        resp = self.client.get(
            reverse("admin:catalog_product_change", args=[self.priced.pk])
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'value="499.00"')

    def test_missing_files_filter(self):
        from apps.catalog.models import ProductFile

        ProductFile.objects.create(product=self.priced, name="Main", kind="download")
        self._login()
        resp = self.client.get(
            reverse("admin:catalog_product_changelist") + "?files=missing"
        )
        self.assertContains(resp, "Bare Kit")
        self.assertNotContains(resp, "Priced Kit")

    def test_category_counts_render(self):
        from apps.catalog.models import Category

        category = Category.objects.create(name="Admin Cat", slug="admin-cat")
        Product.objects.filter(slug="priced-kit").update(category=category)
        Product.objects.filter(slug="bare-kit").update(
            category=category, is_available=False
        )

        self._login()
        resp = self.client.get(reverse("admin:catalog_category_changelist"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "1 live / 2 total")


class ProductAdminFormTests(TestCase):
    """Staff can price products at ₱0 (or below ₱1) for free checkout."""

    BASE_DATA = {
        "name": "Free Starter Guide",
        "slug": "free-starter-guide",
        "product_type": "digital_download",
        "is_available": "on",
    }

    def test_zero_price_saves_as_free(self):
        from apps.catalog.admin import ProductAdminForm

        form = ProductAdminForm(data={**self.BASE_DATA, "price": "0"})
        self.assertTrue(form.is_valid(), form.errors)
        product = form.save()
        self.assertEqual(product.price_cents, 0)

    def test_sub_peso_price_is_accepted(self):
        from apps.catalog.admin import ProductAdminForm

        form = ProductAdminForm(data={**self.BASE_DATA, "price": "0.50"})
        self.assertTrue(form.is_valid(), form.errors)
        product = form.save()
        self.assertEqual(product.price_cents, 50)

    def test_negative_price_rejected(self):
        from apps.catalog.admin import ProductAdminForm

        form = ProductAdminForm(data={**self.BASE_DATA, "price": "-1"})
        self.assertFalse(form.is_valid())
        self.assertIn("price", form.errors)

    def test_regular_price_still_saves(self):
        from apps.catalog.admin import ProductAdminForm

        form = ProductAdminForm(data={**self.BASE_DATA, "price": "499"})
        self.assertTrue(form.is_valid(), form.errors)
        product = form.save()
        self.assertEqual(product.price_cents, 49900)
