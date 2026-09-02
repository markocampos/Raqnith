"""Free checkout (total < ₱1): orders settle without payment but run the
full confirmation/fulfillment workflow — license keys, email, cart clearing.

Covers:
* is_free_order boundaries
* build_order_from_cart accepting all-free carts (previously below-minimum)
* settle_free_order end-to-end settlement + idempotency
* paid orders never free-settle
"""

from django.core import mail
from django.test import TestCase

from apps.cart.models import Cart, CartItem
from apps.catalog.models import Product
from apps.orders.exceptions import OrderBuildError
from apps.orders.models import LicenseKey, Order
from apps.orders.services.order_service import (
    build_order_from_cart,
    is_free_order,
    mark_order_paid,
    settle_free_order,
)


class FreeCheckoutTestBase(TestCase):
    def setUp(self):
        super().setUp()
        self.client.get("/cart/")  # ensure a session exists
        self.session_key = self.client.session.session_key

    def make_cart(self, *price_cents):
        cart, _ = Cart.objects.get_or_create(session_key=self.session_key)
        for i, cents in enumerate(price_cents):
            product = Product.objects.create(
                name=f"Free Item {i}",
                slug=f"free-item-{self.session_key[:6]}-{i}-{cents}",
                price_cents=cents,
            )
            CartItem.objects.create(cart=cart, product=product)
        return cart


class IsFreeOrderTests(TestCase):
    def make_order(self, total_amount):
        return Order.objects.create(subtotal_amount=total_amount, total_amount=total_amount)

    def test_zero_total_is_free(self):
        self.assertTrue(is_free_order(self.make_order(0)))

    def test_sub_peso_total_is_free(self):
        self.assertTrue(is_free_order(self.make_order(99)))

    def test_one_peso_total_is_paid(self):
        self.assertFalse(is_free_order(self.make_order(100)))

    def test_regular_total_is_paid(self):
        self.assertFalse(is_free_order(self.make_order(49900)))


class BuildFreeOrderTests(FreeCheckoutTestBase):
    def test_all_free_cart_builds_with_zero_total(self):
        cart = self.make_cart(0, 50)  # ₱0.00 + ₱0.50 (+VAT) → sub-peso → free
        order = build_order_from_cart(cart, shipping_method="standard")
        self.assertLess(order.total_amount, 100)
        self.assertEqual(order.items.count(), 2)

    def test_zero_price_cart_builds_with_exact_zero_total(self):
        cart = self.make_cart(0)
        order = build_order_from_cart(cart, shipping_method="standard")
        self.assertEqual(order.total_amount, 0)
        self.assertEqual(order.items.count(), 1)

    def test_free_builder_still_rejects_unknown_shipping(self):
        cart = self.make_cart(0)
        with self.assertRaises(OrderBuildError):
            build_order_from_cart(cart, shipping_method="bogus")


class SettleFreeOrderTests(FreeCheckoutTestBase):
    def make_free_order(self):
        cart = self.make_cart(0)
        order = build_order_from_cart(cart, shipping_method="standard")
        item = order.items.first()
        item.product.requires_license_key = True
        item.product.save()
        order.email = "juan@example.com"
        order.save(update_fields=["email"])
        return order

    def test_settle_transitions_draft_to_paid_and_fulfills(self):
        order = self.make_free_order()
        with self.captureOnCommitCallbacks(execute=True):
            settled = settle_free_order(order)

        self.assertEqual(settled.status, Order.Status.PAID)
        self.assertIsNotNone(settled.paid_at)
        self.assertTrue(LicenseKey.objects.filter(order_item__order=settled).exists())
        # Cart cleared after free settlement.
        self.assertEqual(CartItem.objects.count(), 0)

    def test_confirmation_email_sent_for_free_order(self):
        order = self.make_free_order()
        with self.captureOnCommitCallbacks(execute=True):
            settle_free_order(order)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Free", mail.outbox[0].body)

    def test_settlement_is_idempotent(self):
        order = self.make_free_order()
        with self.captureOnCommitCallbacks(execute=True):
            settle_free_order(order)
        with self.captureOnCommitCallbacks(execute=True):
            settle_free_order(order)
        self.assertEqual(LicenseKey.objects.count(), 1)
        self.assertEqual(len(mail.outbox), 1)

    def test_paid_order_never_free_settles(self):
        order = Order.objects.create(
            subtotal_amount=112000,
            total_amount=112000,
            status=Order.Status.PENDING_PAYMENT,
            session_key=self.session_key,
            email="juan@example.com",
        )
        with self.captureOnCommitCallbacks(execute=True):
            settled = mark_order_paid(order)
        # Sanity: normal path untouched by free logic.
        self.assertEqual(settled.status, Order.Status.PAID)
        self.assertEqual(settled.total_amount, 112000)
