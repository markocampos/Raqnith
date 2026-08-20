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
        self.assertContains(resp, "Your cart is empty")

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
