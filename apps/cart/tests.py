from django.db import IntegrityError
from django.test import TestCase
from django.urls import reverse

from apps.cart.models import Cart, CartItem
from apps.catalog.models import Product


class CartTests(TestCase):
    def setUp(self):
        self.product = Product.objects.create(name="Widget", slug="widget", price_cents=2500)

    def test_cart_and_item_creation(self):
        cart = Cart.objects.create(session_key="abc123")
        item = CartItem.objects.create(cart=cart, product=self.product)
        self.assertEqual(item.line_total_cents, 2500)

    def test_cart_session_key_unique(self):
        Cart.objects.create(session_key="unique-key")
        with self.assertRaises(IntegrityError):
            Cart.objects.create(session_key="unique-key")

    def test_cart_product_unique_together(self):
        cart = Cart.objects.create(session_key="dup-test")
        CartItem.objects.create(cart=cart, product=self.product)
        with self.assertRaises(IntegrityError):
            CartItem.objects.create(cart=cart, product=self.product)


class CartViewTests(TestCase):
    def setUp(self):
        self.product = Product.objects.create(
            name="Widget", slug="view-widget", price_cents=2500
        )

    def _add(self):
        return self.client.post(reverse("cart:add"), {"product": self.product.id})

    def test_add_to_cart_creates_item(self):
        resp = self._add()
        self.assertRedirects(resp, reverse("cart:detail"))
        item = CartItem.objects.get()
        self.assertEqual(item.product, self.product)

    def test_add_to_cart_duplicate_is_noop(self):
        self._add()
        self._add()
        self.assertEqual(CartItem.objects.count(), 1)

    def test_view_cart_empty(self):
        resp = self.client.get(reverse("cart:detail"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Your cart is waiting for something great")

    def test_view_cart_shows_items(self):
        self._add()
        resp = self.client.get(reverse("cart:detail"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Widget")
        self.assertContains(resp, "₱25.00")

    def test_remove_item(self):
        self._add()
        item = CartItem.objects.get()
        self.client.post(reverse("cart:remove", args=[item.id]))
        self.assertEqual(CartItem.objects.count(), 0)


class CartAdminTests(TestCase):
    def setUp(self):
        from django.contrib.auth import get_user_model

        User = get_user_model()
        self.admin = User.objects.create_superuser(
            username="admin",
            email="admin@raqnith.test",
            password="AdminPass123!",
        )
        self.product = Product.objects.create(
            name="Admin Kit", slug="admin-kit", price_cents=150_00
        )

    def _login(self):
        self.client.force_login(self.admin)

    def test_changelist_shows_owner_items_and_value(self):
        from django.contrib.auth import get_user_model

        User = get_user_model()
        buyer = User.objects.create_user(username="juan", password="x")
        cart = Cart.objects.create(user=buyer)
        CartItem.objects.create(cart=cart, product=self.product)

        self._login()
        resp = self.client.get(reverse("admin:cart_cart_changelist"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "juan")
        self.assertContains(resp, "\u20b1150.00")
        self.assertContains(resp, "1")

    def test_guest_cart_shows_session_label(self):
        Cart.objects.create(session_key="abcdefgh2345678")
        self._login()
        resp = self.client.get(reverse("admin:cart_cart_changelist"))
        self.assertContains(resp, "Guest (abcdefgh\u2026)")

    def test_stale_activity_filter(self):
        from django.utils import timezone
        from datetime import timedelta

        old = Cart.objects.create(session_key="old-cart")
        Cart.objects.filter(pk=old.pk).update(
            updated_at=timezone.now() - timedelta(days=45)
        )
        fresh = Cart.objects.create(session_key="fresh-cart")

        self._login()
        resp = self.client.get(
            reverse("admin:cart_cart_changelist") + "?activity=stale"
        )
        self.assertContains(resp, "old-cart")
        self.assertNotContains(resp, "fresh-cart")

    def test_change_page_renders_inline(self):
        cart = Cart.objects.create(session_key="inline-check")
        CartItem.objects.create(cart=cart, product=self.product)
        self._login()
        resp = self.client.get(
            reverse("admin:cart_cart_change", args=[cart.pk])
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Admin Kit")
