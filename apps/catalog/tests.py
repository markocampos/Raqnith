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
        self.assertContains(resp, "Philippine Digital Commerce")

    def test_product_list_renders(self):
        resp = self.client.get(reverse("catalog:product_list"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Widget")

    def test_product_detail_renders(self):
        resp = self.client.get(reverse("catalog:product_detail", args=["view-widget"]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Widget")
        self.assertContains(resp, "₱25.00")

